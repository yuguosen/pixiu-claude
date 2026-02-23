"""市场状态检测 — 判断当前市场处于牛/熊/震荡"""

import numpy as np
import pandas as pd
from rich.console import Console

from src.analysis.indicators import calculate_ma, calculate_volatility
from src.config import CONFIG
from src.memory.database import get_index_history

console = Console()

# 市场状态定义
REGIMES = {
    "bull_strong": "强势上涨 — 均线多头排列，趋势强劲",
    "bull_weak": "弱势上涨 — 短期均线在长期均线上方，但动能减弱",
    "ranging": "震荡盘整 — 无明确方向，均线交织",
    "bear_weak": "弱势下跌 — 短期均线开始下穿长期均线",
    "bear_strong": "强势下跌 — 均线空头排列，趋势向下",
}


def detect_market_regime(index_code: str = "000300", category: str = "equity") -> dict | None:
    """检测当前市场状态

    基于相应资产类别的代表标的（指数或联接基金）的均线系统和波动率进行判断。

    Args:
        index_code: 默认 A 股参考指数 000300
        category: 资产类别 (equity/bond/gold/qdii/index)

    Returns:
        dict: {regime, description, trend_score, volatility, details}
    """
    # 代理映射
    proxy_map = {
        "bond": "217022",    # 招商产业债A
        "gold": "000307",    # 易方达黄金ETF联接A
        "qdii": "270042",    # 广发纳指100A
        "equity": index_code,
        "index": index_code,
    }

    query_code = proxy_map.get(category, index_code)

    if category in ("bond", "gold", "qdii"):
        # 基金代码到数据库查询
        from src.memory.database import get_fund_nav_history
        history = get_fund_nav_history(query_code)
        if not history or len(history) < 120:
            console.print(f"[yellow]代理基金 {query_code} 数据不足 (需至少120条)[/]")
            return None
        closes = pd.Series([r["nav"] for r in history])
        dates = [r["nav_date"] for r in history]
    else:
        history = get_index_history(query_code)
        if not history or len(history) < 120:
            console.print(f"[yellow]指数 {query_code} 数据不足 (需至少120条)[/]")
            return None
        closes = pd.Series([r["close"] for r in history])
        dates = [r["trade_date"] for r in history]

    # 计算均线
    mas = calculate_ma(closes, [5, 10, 20, 60, 120])
    current = float(closes.iloc[-1])

    # 获取各均线最新值
    ma_latest = {}
    for key, ma in mas.items():
        if not ma.empty and not np.isnan(ma.iloc[-1]):
            ma_latest[key] = float(ma.iloc[-1])

    # --- 趋势评分 (-100 到 +100) ---
    trend_score = 0.0

    # 1. 价格与均线的关系 (最多 ±40)
    for ma_key, weight in [("MA20", 10), ("MA60", 15), ("MA120", 15)]:
        if ma_key in ma_latest and ma_latest[ma_key] > 0:
            pct_above = (current - ma_latest[ma_key]) / ma_latest[ma_key]
            # 限制在 ±weight 范围
            trend_score += max(-weight, min(weight, pct_above * 100))

    # 2. 均线斜率 (最多 ±30)
    for ma_key, weight in [("MA20", 10), ("MA60", 10), ("MA120", 10)]:
        if ma_key in mas:
            ma_series = mas[ma_key].dropna()
            if len(ma_series) >= 10:
                slope = (float(ma_series.iloc[-1]) - float(ma_series.iloc[-10])) / float(ma_series.iloc[-10])
                trend_score += max(-weight, min(weight, slope * 500))

    # 3. 均线排列 (最多 ±30)
    if all(k in ma_latest for k in ["MA5", "MA10", "MA20", "MA60"]):
        vals = [ma_latest["MA5"], ma_latest["MA10"], ma_latest["MA20"], ma_latest["MA60"]]
        # 检查多头排列程度
        sorted_desc = sorted(vals, reverse=True)
        sorted_asc = sorted(vals)
        if vals == sorted_desc:
            trend_score += 30  # 完美多头排列
        elif vals == sorted_asc:
            trend_score -= 30  # 完美空头排列
        else:
            # 部分排列：计算有多少对是正确排列的
            correct_pairs = 0
            total_pairs = 0
            for i in range(len(vals)):
                for j in range(i + 1, len(vals)):
                    total_pairs += 1
                    if vals[i] > vals[j]:
                        correct_pairs += 1
            alignment = (correct_pairs / total_pairs * 2 - 1) * 15
            trend_score += alignment

    if category in ("equity", "index"):
        # 4. 北向资金流向 (最多 ±15)
        north_flow_score = _get_northbound_score()
        trend_score += north_flow_score

        # 5. 资金流向综合 (最多 ±15)
        fund_flow_score = _get_fund_flow_score()
        trend_score += fund_flow_score

    # 波动率
    vol = calculate_volatility(closes)
    current_vol = float(vol.iloc[-1]) if not vol.empty and not np.isnan(vol.iloc[-1]) else 0.2

    # --- 判断市场状态 ---
    if trend_score > 40:
        regime = "bull_strong"
    elif trend_score > 15:
        regime = "bull_weak"
    elif trend_score > -15:
        regime = "ranging"
    elif trend_score > -40:
        regime = "bear_weak"
    else:
        regime = "bear_strong"

    # 高波动率下调整
    if current_vol > 0.30 and regime in ("bull_weak", "bear_weak"):
        # 高波动可能意味着趋势转换
        regime = "ranging"

    return {
        "regime": regime,
        "description": REGIMES[regime],
        "trend_score": round(trend_score, 1),
        "volatility": round(current_vol, 4),
        "current_price": current,
        "ma_values": ma_latest,
        "index_code": index_code,
        "latest_date": dates[-1],
    }


def _get_northbound_score() -> float:
    """获取北向资金净流入评分 (±15)

    逻辑: 近5日净买入总额判断外资态度
    - 持续流入 → 看好A股 → 正分
    - 持续流出 → 看空A股 → 负分
    """
    try:
        import akshare as ak
        # 获取沪股通 + 深股通数据
        df_sh = ak.stock_hsgt_hist_em(symbol="沪股通")
        df_sz = ak.stock_hsgt_hist_em(symbol="深股通")

        if df_sh.empty and df_sz.empty:
            return 0

        # 取最近 20 个有数据的交易日
        for df in [df_sh, df_sz]:
            df["当日成交净买额"] = pd.to_numeric(df["当日成交净买额"], errors="coerce")

        # 合并北向总流入
        sh_recent = df_sh.dropna(subset=["当日成交净买额"]).tail(20)
        sz_recent = df_sz.dropna(subset=["当日成交净买额"]).tail(20)

        if sh_recent.empty and sz_recent.empty:
            return 0

        # 近5日和近20日净流入 (单位: 亿)
        sh_5d = sh_recent["当日成交净买额"].tail(5).sum() / 1e8 if not sh_recent.empty else 0
        sz_5d = sz_recent["当日成交净买额"].tail(5).sum() / 1e8 if not sz_recent.empty else 0
        total_5d = sh_5d + sz_5d

        sh_20d = sh_recent["当日成交净买额"].sum() / 1e8 if not sh_recent.empty else 0
        sz_20d = sz_recent["当日成交净买额"].sum() / 1e8 if not sz_recent.empty else 0
        total_20d = sh_20d + sz_20d

        score = 0
        # 近5日趋势 (权重较大)
        if total_5d > 100:     # 5日净流入超100亿
            score += 10
        elif total_5d > 30:
            score += 5
        elif total_5d < -100:
            score -= 10
        elif total_5d < -30:
            score -= 5

        # 近20日趋势 (长期确认)
        if total_20d > 200:
            score += 5
        elif total_20d < -200:
            score -= 5

        return max(-15, min(15, score))

    except Exception:
        return 0  # 获取失败不影响主流程


def _get_fund_flow_score() -> float:
    """获取资金流向综合评分 (±15)

    综合市场主力资金流 + 基金仓位估计
    """
    try:
        from src.analysis.fund_flow import get_market_fund_flow, get_fund_position_estimate

        score = 0

        # 市场主力资金流
        market_flow = get_market_fund_flow()
        if market_flow:
            # 将 -15~+15 的原始分压缩到 -10~+10
            score += max(-10, min(10, int(market_flow["score"] * 0.67)))

        # 基金仓位 (逆向信号)
        position = get_fund_position_estimate()
        if position:
            # 将 -10~+10 的原始分压缩到 -5~+5
            score += max(-5, min(5, int(position["score"] * 0.5)))

        return max(-15, min(15, score))

    except Exception:
        return 0


def get_regime_allocation(regime: str) -> dict:
    """根据市场状态返回建议的资产配置比例

    Returns:
        dict: {equity_pct, bond_pct, cash_pct, strategy_weights}
    """
    allocations = {
        "bull_strong": {
            "equity_pct": 0.60,
            "bond_pct": 0.15,
            "cash_pct": 0.25,
            "strategy_weights": {
                "trend_following": 0.30,
                "momentum": 0.25,
                "mean_reversion": 0.10,
                "valuation": 0.15,
                "macro_cycle": 0.10,
                "manager_alpha": 0.10,
            },
        },
        "bull_weak": {
            "equity_pct": 0.55,
            "bond_pct": 0.20,
            "cash_pct": 0.25,
            "strategy_weights": {
                "trend_following": 0.25,
                "momentum": 0.20,
                "mean_reversion": 0.20,
                "valuation": 0.15,
                "macro_cycle": 0.10,
                "manager_alpha": 0.10,
            },
        },
        "ranging": {
            "equity_pct": 0.45,
            "bond_pct": 0.25,
            "cash_pct": 0.30,
            "strategy_weights": {
                "trend_following": 0.15,
                "momentum": 0.15,
                "mean_reversion": 0.30,
                "valuation": 0.20,
                "macro_cycle": 0.10,
                "manager_alpha": 0.10,
            },
        },
        "bear_weak": {
            "equity_pct": 0.35,
            "bond_pct": 0.30,
            "cash_pct": 0.35,
            "strategy_weights": {
                "trend_following": 0.15,
                "momentum": 0.10,
                "mean_reversion": 0.25,
                "valuation": 0.25,
                "macro_cycle": 0.15,
                "manager_alpha": 0.10,
            },
        },
        "bear_strong": {
            "equity_pct": 0.25,
            "bond_pct": 0.35,
            "cash_pct": 0.40,
            "strategy_weights": {
                "trend_following": 0.15,
                "momentum": 0.05,
                "mean_reversion": 0.25,
                "valuation": 0.30,
                "macro_cycle": 0.15,
                "manager_alpha": 0.10,
            },
        },
    }
    return allocations.get(regime, allocations["ranging"])
