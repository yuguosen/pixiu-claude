"""基金综合评分与筛选"""

import numpy as np
import pandas as pd
from rich.console import Console

from src.analysis.indicators import (
    calculate_max_drawdown,
    calculate_sharpe_ratio,
    calculate_volatility,
)
from src.config import CONFIG
from src.memory.database import classify_fund, execute_query, get_fund_nav_history

console = Console()


def score_fund(fund_code: str) -> dict | None:
    """对单只基金进行综合评分

    评分维度:
    - 收益 (40分): 近1月/3月/6月/1年收益率
    - 风险 (30分): 最大回撤、波动率、夏普比率
    - 稳定性 (20分): 收益一致性
    - 费用 (10分): 综合费率

    Returns:
        dict with total_score, sub_scores, and metrics
    """
    nav_history = get_fund_nav_history(fund_code)
    if not nav_history or len(nav_history) < 60:
        return None

    navs = pd.Series([r["nav"] for r in nav_history])
    dates = [r["nav_date"] for r in nav_history]
    returns = navs.pct_change().dropna()

    # 获取基金分类和对应评分阈值
    category = classify_fund(fund_code)
    targets = CONFIG.get("scoring_targets", {}).get(category, {})
    return_target = targets.get("return_target", 0.20)  # 年化收益目标
    vol_cap = targets.get("vol_cap", 0.40)              # 波动率上限
    dd_cap = targets.get("dd_cap", 0.30)                # 回撤上限

    current_nav = float(navs.iloc[-1])
    result = {
        "fund_code": fund_code,
        "category": category,
        "latest_nav": current_nav,
        "latest_date": dates[-1],
        "data_points": len(navs),
    }

    # --- 收益维度 (40分) ---
    return_score = 0
    return_periods = {
        "return_1m": min(22, len(navs) - 1),
        "return_3m": min(66, len(navs) - 1),
        "return_6m": min(132, len(navs) - 1),
        "return_1y": min(250, len(navs) - 1),
    }

    for key, days in return_periods.items():
        if days > 0:
            past_nav = float(navs.iloc[-1 - days])
            if past_nav > 0:
                ret = (current_nav - past_nav) / past_nav * 100
                result[key] = round(ret, 2)

    # 收益评分：根据各期收益率打分
    weights = {"return_1m": 0.15, "return_3m": 0.25, "return_6m": 0.30, "return_1y": 0.30}
    for key, weight in weights.items():
        ret = result.get(key, 0)
        # 年化对齐
        if key == "return_1m":
            annualized = ret * 12
        elif key == "return_3m":
            annualized = ret * 4
        elif key == "return_6m":
            annualized = ret * 2
        else:
            annualized = ret

        # 评分：年化 return_target*100% 以上满分，0% 为基准
        target_pct = return_target * 100  # 如 equity=20%, bond=5%
        period_score = min(40, max(0, (annualized + target_pct) / (target_pct * 2) * 40))
        return_score += period_score * weight

    result["return_score"] = round(return_score, 1)

    # --- 风险维度 (30分) ---
    risk_score = 30.0

    # 最大回撤
    max_dd, dd_start, dd_end = calculate_max_drawdown(navs)
    result["max_drawdown"] = round(max_dd * 100, 2)
    result["dd_start"] = dd_start
    result["dd_end"] = dd_end
    # 回撤越小越好：0%满分，超过 dd_cap 扣满
    dd_penalty = min(30, max(0, abs(max_dd) / dd_cap * 15))
    risk_score -= dd_penalty

    # 波动率
    vol = calculate_volatility(navs)
    if not vol.empty:
        current_vol = float(vol.iloc[-1]) if not np.isnan(vol.iloc[-1]) else 0
        result["volatility"] = round(current_vol, 4)
        # 波动率越低越好：低于 vol_cap*0.25 满分，超过 vol_cap 扣满
        vol_floor = vol_cap * 0.25
        vol_penalty = min(10, max(0, (current_vol - vol_floor) / (vol_cap - vol_floor) * 10)) if vol_cap > vol_floor else 0
        risk_score -= vol_penalty

    # 夏普比率
    sharpe = calculate_sharpe_ratio(returns)
    result["sharpe_ratio"] = round(sharpe, 2)
    # 夏普>2加分，<0减分
    sharpe_bonus = min(5, max(-5, (sharpe - 0.5) / 1.5 * 5))
    risk_score += sharpe_bonus

    result["risk_score"] = round(max(0, risk_score), 1)

    # --- 稳定性维度 (20分) ---
    stability_score = 20.0

    # 月度收益一致性（正收益月数比例）
    monthly_returns = navs.resample("ME").last().pct_change().dropna() if hasattr(navs.index, 'freq') else pd.Series(dtype=float)
    if monthly_returns.empty:
        # 手动计算月度收益
        step = 22
        monthly_rets = []
        for i in range(step, len(navs), step):
            mr = (float(navs.iloc[i]) - float(navs.iloc[i - step])) / float(navs.iloc[i - step])
            monthly_rets.append(mr)
        if monthly_rets:
            positive_months = sum(1 for r in monthly_rets if r > 0)
            win_rate = positive_months / len(monthly_rets)
            result["monthly_win_rate"] = round(win_rate * 100, 1)
            # 胜率>70%满分，<30%最低
            stability_score = min(20, max(0, (win_rate - 0.30) / 0.40 * 20))

    result["stability_score"] = round(stability_score, 1)

    # --- 费用维度 (10分) ---
    fund_info = execute_query("SELECT * FROM funds WHERE fund_code = ?", (fund_code,))
    fee_score = 7.0  # 默认中等
    if fund_info:
        fee_rate = fund_info[0].get("subscription_fee_rate")
        if fee_rate is not None:
            # 费率越低越好
            fee_score = min(10, max(0, (2.0 - fee_rate) / 2.0 * 10))
    result["fee_score"] = round(fee_score, 1)

    # --- 总分 ---
    result["total_score"] = round(
        result["return_score"] + result["risk_score"]
        + result["stability_score"] + result["fee_score"],
        1,
    )

    return result


def screen_and_score_funds() -> list[dict]:
    """筛选并评分所有已存储的基金

    Returns:
        按综合评分降序排列的基金列表
    """
    # 获取所有有净值数据的基金
    funds = execute_query(
        """SELECT DISTINCT fn.fund_code, f.fund_name
           FROM fund_nav fn
           LEFT JOIN funds f ON fn.fund_code = f.fund_code
           GROUP BY fn.fund_code
           HAVING COUNT(*) >= 60"""
    )

    if not funds:
        console.print("[yellow]数据库中无足够净值数据的基金[/]")
        return []

    scored = []
    for fund in funds:
        code = fund["fund_code"]
        try:
            result = score_fund(code)
            if result:
                result["fund_name"] = fund.get("fund_name") or f"基金{code}"
                scored.append(result)
        except Exception as e:
            console.print(f"  [yellow]评分基金 {code} 失败: {e}[/]")

    scored.sort(key=lambda x: x["total_score"], reverse=True)
    return scored
