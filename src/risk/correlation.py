"""持仓相关性管理 — 真正的分散而不是假分散

核心逻辑：
- 计算持仓之间的净值相关性
- 相关性 > 0.8 的基金视为"同一仓位"
- 组合平均相关性应 < 0.6
- 建议持有不同风格的基金 (成长/价值/债券/商品)
"""

import numpy as np
import pandas as pd
from rich.console import Console

from src.memory.database import execute_query, get_fund_nav_history

console = Console()


def calculate_fund_correlation(fund_codes: list[str], lookback_days: int = 120) -> pd.DataFrame:
    """计算基金之间的收益率相关性矩阵

    Args:
        fund_codes: 基金代码列表
        lookback_days: 回看天数

    Returns:
        相关性矩阵 DataFrame
    """
    if len(fund_codes) < 2:
        return pd.DataFrame()

    # 收集各基金的日收益率
    returns_dict = {}
    for code in fund_codes:
        nav_history = get_fund_nav_history(code)
        if nav_history and len(nav_history) >= lookback_days:
            navs = pd.Series(
                [r["nav"] for r in nav_history[-lookback_days:]],
                index=[r["nav_date"] for r in nav_history[-lookback_days:]],
            )
            returns_dict[code] = navs.pct_change().dropna()

    if len(returns_dict) < 2:
        return pd.DataFrame()

    # 对齐日期
    returns_df = pd.DataFrame(returns_dict)
    returns_df = returns_df.dropna()

    if returns_df.empty or len(returns_df) < 30:
        return pd.DataFrame()

    return returns_df.corr()


def analyze_portfolio_correlation() -> dict:
    """分析当前持仓的相关性

    Returns:
        {
            correlation_matrix: DataFrame,
            avg_correlation: float,
            high_corr_pairs: [(code1, code2, corr)],
            diversification_score: float (0-100),
            suggestions: [str],
        }
    """
    holdings = execute_query(
        "SELECT fund_code FROM portfolio WHERE status = 'holding'"
    )

    if len(holdings) < 2:
        return {
            "avg_correlation": 0,
            "high_corr_pairs": [],
            "diversification_score": 100,
            "suggestions": ["持仓不足 2 只，无需相关性分析"],
        }

    fund_codes = [h["fund_code"] for h in holdings]
    corr_matrix = calculate_fund_correlation(fund_codes)

    if corr_matrix.empty:
        return {
            "avg_correlation": 0,
            "high_corr_pairs": [],
            "diversification_score": 50,
            "suggestions": ["数据不足，无法计算相关性"],
        }

    # 提取上三角 (排除对角线)
    n = len(fund_codes)
    correlations = []
    high_corr_pairs = []

    for i in range(n):
        for j in range(i + 1, n):
            corr = float(corr_matrix.iloc[i, j])
            correlations.append(corr)
            if corr > 0.8:
                high_corr_pairs.append((fund_codes[i], fund_codes[j], round(corr, 3)))

    avg_corr = float(np.mean(correlations)) if correlations else 0

    # 分散化得分 (0-100)
    # 完全负相关 = 100, 完全正相关 = 0
    diversification_score = max(0, min(100, (1 - avg_corr) * 100))

    suggestions = []
    if avg_corr > 0.7:
        suggestions.append("持仓高度相关，实际等于集中持仓一个方向，建议增加不同风格的基金")
    if high_corr_pairs:
        for c1, c2, corr in high_corr_pairs:
            suggestions.append(f"{c1} 和 {c2} 相关性 {corr:.2f}，建议保留其一")
    if avg_corr < 0.3:
        suggestions.append("持仓分散度优秀")

    return {
        "avg_correlation": round(avg_corr, 3),
        "high_corr_pairs": high_corr_pairs,
        "diversification_score": round(diversification_score, 1),
        "suggestions": suggestions,
    }


def get_correlation_penalty(fund_code: str, existing_holdings: list[str]) -> float:
    """计算新基金与现有持仓的相关性惩罚

    用于调整新买入的仓位大小——如果新基金与已有持仓高度相关，降低仓位。

    Args:
        fund_code: 待买入基金
        existing_holdings: 现有持仓代码列表

    Returns:
        仓位乘数 (0.3 - 1.0)，相关性越高乘数越小
    """
    if not existing_holdings:
        return 1.0

    all_codes = existing_holdings + [fund_code]
    corr_matrix = calculate_fund_correlation(all_codes)

    if corr_matrix.empty or fund_code not in corr_matrix.columns:
        return 1.0

    # 新基金与所有已有持仓的平均相关性
    correlations = []
    for code in existing_holdings:
        if code in corr_matrix.columns:
            corr = float(corr_matrix.loc[fund_code, code])
            correlations.append(corr)

    if not correlations:
        return 1.0

    avg_corr = np.mean(correlations)

    # 相关性 > 0.8: 大幅缩减 (×0.3)
    # 相关性 0.5-0.8: 适度缩减 (×0.5-0.8)
    # 相关性 < 0.3: 全额 (×1.0)
    if avg_corr > 0.8:
        return 0.3
    elif avg_corr > 0.5:
        return round(1.0 - avg_corr * 0.7, 2)
    else:
        return 1.0
