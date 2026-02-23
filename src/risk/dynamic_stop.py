"""动态止损 — ATR-based，让止损随波动率调整

核心逻辑：
- 止损线 = 买入价 - N × ATR(20日)
- 波动大的基金给更宽的容忍度 (如诺安成长 ATR 大)
- 波动小的基金用更紧的止损 (如债券基金)
- 移动止盈: 从峰值回落 trailing_atr × ATR 触发

相比固定 8% 止损的优势：
- 不会被正常波动洗出去
- 自适应不同类型的基金
"""

import pandas as pd
import numpy as np

from src.memory.database import get_fund_nav_history


def calculate_atr(navs: pd.Series, period: int = 20) -> float:
    """计算 Average True Range (简化版，基金无最高最低价，用日收益率标准差代替)

    Args:
        navs: 净值序列
        period: ATR 周期

    Returns:
        ATR 值 (绝对金额)
    """
    if len(navs) < period + 1:
        return 0.0

    # 基金只有收盘价，用绝对日变动作为 TR
    daily_change = navs.diff().abs()
    atr = float(daily_change.tail(period).mean())
    return atr


def get_dynamic_stop_loss(
    fund_code: str,
    cost_price: float,
    atr_multiplier: float = 2.0,
) -> dict:
    """计算动态止损线

    Args:
        fund_code: 基金代码
        cost_price: 买入成本价
        atr_multiplier: ATR 乘数 (默认 2.0)

    Returns:
        {stop_loss_price, stop_loss_pct, atr, atr_pct, method}
    """
    nav_history = get_fund_nav_history(fund_code)
    if not nav_history or len(nav_history) < 25:
        # 降级为固定止损
        return {
            "stop_loss_price": cost_price * 0.92,
            "stop_loss_pct": -8.0,
            "atr": 0,
            "atr_pct": 0,
            "method": "fixed_fallback",
        }

    navs = pd.Series([r["nav"] for r in nav_history])
    atr = calculate_atr(navs)

    if atr <= 0:
        return {
            "stop_loss_price": cost_price * 0.92,
            "stop_loss_pct": -8.0,
            "atr": 0,
            "atr_pct": 0,
            "method": "fixed_fallback",
        }

    stop_distance = atr * atr_multiplier
    stop_loss_price = cost_price - stop_distance
    stop_loss_pct = (stop_loss_price - cost_price) / cost_price * 100

    # 安全网：止损不超过 -15%
    if stop_loss_pct < -15:
        stop_loss_pct = -15.0
        stop_loss_price = cost_price * 0.85

    # 下限：止损不能太紧 (至少 -3%)
    if stop_loss_pct > -3:
        stop_loss_pct = -3.0
        stop_loss_price = cost_price * 0.97

    atr_pct = atr / cost_price * 100

    return {
        "stop_loss_price": round(stop_loss_price, 4),
        "stop_loss_pct": round(stop_loss_pct, 2),
        "atr": round(atr, 4),
        "atr_pct": round(atr_pct, 2),
        "method": "atr_dynamic",
    }


def get_trailing_stop(
    fund_code: str,
    peak_nav: float,
    atr_multiplier: float = 2.5,
) -> dict:
    """计算移动止盈线

    Args:
        fund_code: 基金代码
        peak_nav: 持仓期间净值最高点
        atr_multiplier: ATR 乘数 (移动止盈用更大的乘数)

    Returns:
        {trailing_stop_price, trailing_stop_pct}
    """
    nav_history = get_fund_nav_history(fund_code)
    if not nav_history or len(nav_history) < 25:
        return {
            "trailing_stop_price": peak_nav * 0.90,
            "trailing_stop_pct": -10.0,
        }

    navs = pd.Series([r["nav"] for r in nav_history])
    atr = calculate_atr(navs)

    if atr <= 0:
        return {
            "trailing_stop_price": peak_nav * 0.90,
            "trailing_stop_pct": -10.0,
        }

    stop_distance = atr * atr_multiplier
    trailing_stop = peak_nav - stop_distance
    trailing_pct = (trailing_stop - peak_nav) / peak_nav * 100

    # 安全网
    trailing_pct = max(-20.0, min(-5.0, trailing_pct))
    trailing_stop = peak_nav * (1 + trailing_pct / 100)

    return {
        "trailing_stop_price": round(trailing_stop, 4),
        "trailing_stop_pct": round(trailing_pct, 2),
    }


def check_progressive_drawdown(current_drawdown: float) -> dict:
    """渐进式回撤响应 — 不是 0 或 100 的二元选择

    Args:
        current_drawdown: 当前回撤比例 (负数)

    Returns:
        {level, action, reduce_pct, narrative}
    """
    dd = abs(current_drawdown)

    if dd < 0.03:
        return {
            "level": "normal",
            "action": "正常操作",
            "reduce_pct": 0,
            "narrative": f"回撤 {dd:.1%}，组合健康",
        }
    elif dd < 0.05:
        return {
            "level": "caution",
            "action": "警惕，不加仓",
            "reduce_pct": 0,
            "narrative": f"回撤 {dd:.1%}，进入警戒区，暂停新买入",
        }
    elif dd < 0.08:
        return {
            "level": "warning",
            "action": "减仓 20%",
            "reduce_pct": 20,
            "narrative": f"回撤 {dd:.1%}，执行第一阶减仓 20%",
        }
    elif dd < 0.10:
        return {
            "level": "danger",
            "action": "减仓 50%",
            "reduce_pct": 50,
            "narrative": f"回撤 {dd:.1%}，执行第二阶减仓至半仓",
        }
    else:
        return {
            "level": "critical",
            "action": "清仓",
            "reduce_pct": 100,
            "narrative": f"回撤 {dd:.1%}，触发硬止损，清仓保护本金",
        }
