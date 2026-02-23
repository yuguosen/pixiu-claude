"""资产配置保护层 — 永远保持底线

核心规则 (不可违反):
- 现金/货币基金 ≥ 20% (抄底弹药)
- 债券基金 ≥ 10% (对冲股市下跌)
- 股票型基金 ≤ 70% (即使极度看多)

根据市场状态动态调整：
- 牛市: 股 60% / 债 15% / 现金 25%
- 震荡: 股 45% / 债 25% / 现金 30%
- 熊市: 股 25% / 债 35% / 现金 40%
"""

from rich.console import Console

from src.config import CONFIG
from src.memory.database import execute_query, get_connection

console = Console()

# 硬性底线 (绝对不可突破)
HARD_LIMITS = {
    "equity_max": 0.70,
    "cash_min": 0.20,
    "bond_min": 0.10,
}

# 按市场状态的目标配置
REGIME_ALLOCATIONS = {
    "bull_strong": {"equity": 0.60, "bond": 0.15, "cash": 0.25},
    "bull_weak":   {"equity": 0.55, "bond": 0.20, "cash": 0.25},
    "ranging":     {"equity": 0.45, "bond": 0.25, "cash": 0.30},
    "bear_weak":   {"equity": 0.35, "bond": 0.30, "cash": 0.35},
    "bear_strong": {"equity": 0.25, "bond": 0.35, "cash": 0.40},
}

# 估值修正 (叠加在 regime 之上)
VALUATION_ADJUSTMENTS = {
    # pe_percentile 范围: (equity_delta, bond_delta, cash_delta)
    (0, 20):   (+0.10, -0.05, -0.05),   # 极度低估: 加股减债减现
    (20, 30):  (+0.05, -0.03, -0.02),   # 低估
    (70, 80):  (-0.05, +0.03, +0.02),   # 高估
    (80, 100): (-0.10, +0.05, +0.05),   # 极度高估: 减股加债加现
}


def get_target_allocation(regime: str = "ranging", pe_percentile: float = 50) -> dict:
    """获取目标资产配置

    Args:
        regime: 市场状态
        pe_percentile: PE 分位 (0-100)

    Returns:
        {equity, bond, cash} 目标配比
    """
    # 基础配置
    base = REGIME_ALLOCATIONS.get(regime, REGIME_ALLOCATIONS["ranging"]).copy()

    # 估值修正
    for (low, high), (eq_d, bd_d, ca_d) in VALUATION_ADJUSTMENTS.items():
        if low <= pe_percentile < high:
            base["equity"] += eq_d
            base["bond"] += bd_d
            base["cash"] += ca_d
            break

    # 应用硬性底线
    base["equity"] = min(base["equity"], HARD_LIMITS["equity_max"])
    base["cash"] = max(base["cash"], HARD_LIMITS["cash_min"])
    base["bond"] = max(base["bond"], HARD_LIMITS["bond_min"])

    # 归一化确保总和为 1
    total = base["equity"] + base["bond"] + base["cash"]
    if total != 1.0:
        base["equity"] = round(base["equity"] / total, 3)
        base["bond"] = round(base["bond"] / total, 3)
        base["cash"] = round(1.0 - base["equity"] - base["bond"], 3)

    return base


def get_current_allocation() -> dict:
    """获取当前实际资产配置

    Returns:
        {equity, bond, cash, total_value, details}
    """
    holdings = execute_query(
        "SELECT * FROM portfolio WHERE status = 'holding'"
    )

    total_invested = sum(
        (h.get("current_nav") or h["cost_price"]) * h["shares"]
        for h in holdings
    )
    snapshots = execute_query(
        "SELECT cash FROM account_snapshots ORDER BY snapshot_date DESC LIMIT 1"
    )
    cash = snapshots[0]["cash"] if snapshots else CONFIG["current_cash"]
    total_value = cash + total_invested

    if total_value <= 0:
        return {
            "equity": 0, "bond": 0, "cash": 1.0,
            "total_value": cash,
        }

    # 分类持仓 (简化: 基于基金类型或名称关键词)
    equity_value = 0
    bond_value = 0

    for h in holdings:
        value = (h.get("current_nav") or h["cost_price"]) * h["shares"]
        fund_info = execute_query(
            "SELECT fund_type, fund_name FROM funds WHERE fund_code = ?",
            (h["fund_code"],),
        )
        fund_type = ""
        fund_name = ""
        if fund_info:
            fund_type = (fund_info[0].get("fund_type") or "").lower()
            fund_name = (fund_info[0].get("fund_name") or "").lower()

        is_bond = ("债" in fund_name or "bond" in fund_type
                   or "纯债" in fund_name or "利率" in fund_name)

        if is_bond:
            bond_value += value
        else:
            equity_value += value

    return {
        "equity": round(equity_value / total_value, 3) if total_value > 0 else 0,
        "bond": round(bond_value / total_value, 3) if total_value > 0 else 0,
        "cash": round(cash / total_value, 3) if total_value > 0 else 1.0,
        "equity_value": round(equity_value, 2),
        "bond_value": round(bond_value, 2),
        "cash_value": round(cash, 2),
        "total_value": round(total_value, 2),
    }


def check_allocation_compliance(
    regime: str = "ranging",
    pe_percentile: float = 50,
) -> dict:
    """检查资产配置合规性

    Returns:
        {
            compliant: bool,
            target: {equity, bond, cash},
            current: {equity, bond, cash},
            deviations: {equity, bond, cash},
            violations: [str],
            suggestions: [str],
        }
    """
    target = get_target_allocation(regime, pe_percentile)
    current = get_current_allocation()

    deviations = {
        "equity": round(current["equity"] - target["equity"], 3),
        "bond": round(current["bond"] - target["bond"], 3),
        "cash": round(current["cash"] - target["cash"], 3),
    }

    violations = []
    suggestions = []

    # 检查硬性底线
    if current["equity"] > HARD_LIMITS["equity_max"]:
        violations.append(f"股票仓位 {current['equity']:.0%} 超过上限 {HARD_LIMITS['equity_max']:.0%}")
        suggestions.append(f"减少股票基金仓位至 {HARD_LIMITS['equity_max']:.0%} 以下")

    if current["cash"] < HARD_LIMITS["cash_min"]:
        violations.append(f"现金比例 {current['cash']:.0%} 低于底线 {HARD_LIMITS['cash_min']:.0%}")
        suggestions.append(f"增加现金储备至 {HARD_LIMITS['cash_min']:.0%} 以上")

    if current["bond"] < HARD_LIMITS["bond_min"]:
        violations.append(f"债券比例 {current['bond']:.0%} 低于底线 {HARD_LIMITS['bond_min']:.0%}")
        suggestions.append("配置债券基金作为组合压舱石")

    # 检查与目标的偏离
    for asset_class, dev in deviations.items():
        if abs(dev) > 0.10:
            direction = "偏高" if dev > 0 else "偏低"
            suggestions.append(
                f"{asset_class} 配置 {direction} {abs(dev):.0%}，"
                f"目标 {target[asset_class]:.0%}，当前 {current[asset_class]:.0%}"
            )

    return {
        "compliant": len(violations) == 0,
        "target": target,
        "current": current,
        "deviations": deviations,
        "violations": violations,
        "suggestions": suggestions,
    }


def get_max_equity_amount(
    total_value: float,
    regime: str = "ranging",
    pe_percentile: float = 50,
) -> float:
    """获取当前允许的最大股票型基金投资金额

    用于限制 position_sizing 的上限。
    """
    target = get_target_allocation(regime, pe_percentile)
    current = get_current_allocation()

    max_equity_pct = min(target["equity"] + 0.05, HARD_LIMITS["equity_max"])
    current_equity_value = current.get("equity_value", 0)
    max_equity_value = total_value * max_equity_pct

    available = max(0, max_equity_value - current_equity_value)
    return round(available, 2)
