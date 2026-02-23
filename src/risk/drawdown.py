"""回撤监控与控制"""

from src.config import CONFIG
from src.memory.database import execute_query


def get_portfolio_drawdown() -> dict:
    """计算当前组合的回撤情况

    Returns:
        dict: {current_drawdown, max_drawdown, peak_value, current_value, alert_level}
    """
    snapshots = execute_query(
        "SELECT * FROM account_snapshots ORDER BY snapshot_date DESC LIMIT 250"
    )

    if not snapshots:
        return {
            "current_drawdown": 0,
            "max_drawdown": 0,
            "peak_value": CONFIG["initial_capital"],
            "current_value": CONFIG["initial_capital"],
            "alert_level": "normal",
        }

    values = [s["total_value"] for s in reversed(snapshots)]
    current_value = values[-1]
    peak_value = max(values)
    current_dd = (current_value - peak_value) / peak_value if peak_value > 0 else 0

    # 历史最大回撤
    running_max = 0
    max_dd = 0
    for v in values:
        running_max = max(running_max, v)
        dd = (v - running_max) / running_max
        max_dd = min(max_dd, dd)

    # 警报级别
    abs_dd = abs(current_dd)
    if abs_dd >= CONFIG["max_drawdown_hard"]:
        alert_level = "critical"
    elif abs_dd >= CONFIG["max_drawdown_soft"]:
        alert_level = "warning"
    else:
        alert_level = "normal"

    return {
        "current_drawdown": round(current_dd, 4),
        "max_drawdown": round(max_dd, 4),
        "peak_value": round(peak_value, 2),
        "current_value": round(current_value, 2),
        "alert_level": alert_level,
    }


def check_single_fund_stop_loss(fund_code: str) -> dict | None:
    """检查单只基金是否触发止损

    Returns:
        dict if stop loss triggered, None otherwise
    """
    holdings = execute_query(
        "SELECT * FROM portfolio WHERE fund_code = ? AND status = 'holding'",
        (fund_code,),
    )

    if not holdings:
        return None

    from src.memory.database import get_fund_nav_history
    import pandas as pd
    from src.analysis.indicators import get_technical_summary

    for h in holdings:
        cost = h["cost_price"]
        current = h["current_nav"] or cost
        loss_pct = (current - cost) / cost if cost > 0 else 0

        # 获取动态止损比例
        stop_loss_pct = CONFIG["single_fund_stop_loss"]
        nav_history = get_fund_nav_history(fund_code)
        if nav_history:
            navs = pd.Series([r["nav"] for r in nav_history])
            tech = get_technical_summary(navs)
            if tech:
                vol = tech.get("volatility", 0.01)
                # 与回测逻辑保持一致：3% ~ 15% 动态调整
                stop_loss_pct = max(0.03, min(vol * 15, 0.15))

        if loss_pct < -stop_loss_pct:
            return {
                "fund_code": fund_code,
                "cost_price": cost,
                "current_nav": current,
                "loss_pct": round(loss_pct * 100, 2),
                "threshold": -stop_loss_pct * 100,
                "action": "建议止损卖出",
            }

    return None


def get_drawdown_actions(alert_level: str) -> list[str]:
    """根据回撤级别返回建议操作"""
    if alert_level == "critical":
        return [
            "立即减仓至 50% 以下",
            "优先卖出亏损最大的持仓",
            "暂停新的买入操作",
            "等待市场企稳后再考虑加仓",
        ]
    elif alert_level == "warning":
        return [
            "谨慎操作，不建议加仓",
            "检查各持仓止损线",
            "准备减仓计划",
        ]
    else:
        return ["组合回撤正常，可正常操作"]
