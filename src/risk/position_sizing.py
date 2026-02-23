"""仓位计算 — 基于半凯利准则"""

from src.config import CONFIG


def calculate_kelly_position(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fraction: float = None,
) -> float:
    """计算凯利仓位

    Args:
        win_rate: 历史胜率 (0-1)
        avg_win: 平均盈利比例
        avg_loss: 平均亏损比例 (正数)
        fraction: 凯利分数 (默认半凯利)

    Returns:
        建议仓位比例 (0-1)
    """
    if fraction is None:
        fraction = CONFIG["kelly_fraction"]

    if avg_loss == 0:
        return 0

    # Kelly criterion: f* = (bp - q) / b
    # b = avg_win / avg_loss, p = win_rate, q = 1 - win_rate
    b = avg_win / avg_loss
    p = win_rate
    q = 1 - p
    kelly = (b * p - q) / b

    # 应用分数凯利
    position = kelly * fraction

    # 限制范围
    return max(0, min(position, CONFIG["max_single_position_pct"]))


def calculate_position_size(
    total_capital: float,
    current_cash: float,
    confidence: float,
    regime: str = "ranging",
    existing_positions: int = 0,
    fund_code: str = "",
    existing_holdings: list[str] | None = None,
) -> float:
    """计算具体的交易金额

    集成了资产配置限制、估值修正、相关性惩罚。

    Args:
        total_capital: 总资产
        current_cash: 可用现金
        confidence: 信号置信度 (0-1)
        regime: 市场状态
        existing_positions: 已有持仓数量
        fund_code: 待买入基金代码 (用于相关性检查)
        existing_holdings: 已持有基金代码列表 (用于相关性检查)

    Returns:
        建议交易金额 (RMB)
    """
    # 保留最低现金
    min_cash = total_capital * CONFIG["min_cash_reserve_pct"]
    available = max(0, current_cash - min_cash)

    if available <= 0:
        return 0

    # 基础仓位：根据市场状态调整
    regime_multipliers = {
        "bull_strong": 0.90,
        "bull_weak": 0.70,
        "ranging": 0.50,
        "bear_weak": 0.35,
        "bear_strong": 0.20,
    }
    base_pct = regime_multipliers.get(regime, 0.50)

    # 根据置信度调整
    position_pct = base_pct * confidence

    # 单基金仓位上限
    max_single = total_capital * CONFIG["max_single_position_pct"]

    # 如果已有多个持仓，减少新仓位
    if existing_positions >= 3:
        position_pct *= 0.5
    elif existing_positions >= 2:
        position_pct *= 0.7

    # ── 估值修正 ──
    try:
        from src.data.valuation import get_valuation_signal
        v_signal = get_valuation_signal()
        position_multiplier = v_signal.get("position_multiplier", 1.0)
        position_pct *= position_multiplier
    except Exception:
        pass

    # ── 资产配置硬性限制 ──
    try:
        from src.risk.asset_allocation import get_max_equity_amount
        max_equity = get_max_equity_amount(total_capital, regime)
        max_single = min(max_single, max_equity)
    except Exception:
        pass

    # ── 相关性惩罚 ──
    if fund_code and existing_holdings:
        try:
            from src.risk.correlation import get_correlation_penalty
            corr_multiplier = get_correlation_penalty(fund_code, existing_holdings)
            position_pct *= corr_multiplier
        except Exception:
            pass

    amount = min(available * position_pct, max_single)

    # 最小交易金额 100 RMB
    if amount < 100:
        return 0

    return round(amount, 2)
