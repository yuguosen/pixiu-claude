"""基金经理数据 — 买基金就是买基金经理"""

import pandas as pd
from rich.console import Console

from src.data.fetcher import fetch_with_cache, fetch_with_retry
from src.memory.database import execute_query, get_connection

console = Console()


def fetch_fund_manager_info(fund_code: str) -> dict | None:
    """获取基金的基金经理信息

    Returns:
        {manager_name, start_date, tenure_years, ...} or None
    """
    import akshare as ak

    try:
        df = fetch_with_retry(ak.fund_individual_basic_info_xq, symbol=fund_code)
        if df is None or df.empty:
            return None

        info = dict(zip(df.iloc[:, 0], df.iloc[:, 1]))
        manager_name = info.get("基金经理", info.get("基金经理/管理人", ""))

        return {
            "fund_code": fund_code,
            "manager_name": manager_name,
            "company": info.get("基金管理人", ""),
            "fund_type": info.get("基金类型", ""),
            "establishment_date": info.get("成立日期", ""),
        }
    except Exception:
        return None


def evaluate_fund_manager(fund_code: str) -> dict:
    """评估基金经理质量

    综合任职时间、历史回撤、业绩稳定性给出评分。

    Returns:
        {manager_name, tenure_years, score, grade, reasons}
    """
    from src.memory.database import get_fund_nav_history
    from src.analysis.indicators import calculate_max_drawdown, calculate_sharpe_ratio

    result = {
        "fund_code": fund_code,
        "score": 50,
        "grade": "C",
        "reasons": [],
    }

    # 获取基金经理基本信息
    info = fetch_fund_manager_info(fund_code)
    if info:
        result["manager_name"] = info.get("manager_name", "未知")
        result["company"] = info.get("company", "")

    # 用净值历史评估业绩
    nav_history = get_fund_nav_history(fund_code)
    if not nav_history or len(nav_history) < 120:
        result["reasons"].append("数据不足 (<120 天)")
        return result

    navs = pd.Series([r["nav"] for r in nav_history])
    returns = navs.pct_change().dropna()

    score = 50

    # 1. 数据长度 (代理任职时间) — 越长越好
    years = len(nav_history) / 250
    result["data_years"] = round(years, 1)
    if years >= 5:
        score += 15
        result["reasons"].append(f"数据覆盖 {years:.1f} 年，穿越多个周期")
    elif years >= 3:
        score += 10
        result["reasons"].append(f"数据覆盖 {years:.1f} 年")
    elif years >= 1:
        score += 5

    # 2. 年化收益
    total_return = (float(navs.iloc[-1]) / float(navs.iloc[0]) - 1)
    annualized = (1 + total_return) ** (1 / max(years, 0.5)) - 1
    result["annualized_return"] = round(annualized * 100, 2)
    if annualized > 0.15:
        score += 15
        result["reasons"].append(f"年化 {annualized:.1%}，优秀")
    elif annualized > 0.08:
        score += 10
        result["reasons"].append(f"年化 {annualized:.1%}，良好")
    elif annualized > 0:
        score += 5

    # 3. 最大回撤
    max_dd, _, _ = calculate_max_drawdown(navs)
    result["max_drawdown"] = round(max_dd * 100, 2)
    if max_dd > -0.20:
        score += 10
        result["reasons"].append(f"最大回撤 {max_dd:.1%}，控制良好")
    elif max_dd > -0.30:
        score += 5
    else:
        score -= 5
        result["reasons"].append(f"最大回撤 {max_dd:.1%}，较大")

    # 4. 夏普比率
    sharpe = calculate_sharpe_ratio(returns)
    result["sharpe_ratio"] = round(sharpe, 2)
    if sharpe > 1.5:
        score += 10
        result["reasons"].append(f"夏普 {sharpe:.2f}，风险调整收益优秀")
    elif sharpe > 0.8:
        score += 5

    # 5. 风格稳定性 (月度收益标准差的稳定性)
    if len(returns) >= 60:
        rolling_vol = returns.rolling(20).std()
        vol_of_vol = rolling_vol.std() / rolling_vol.mean() if rolling_vol.mean() > 0 else 1
        if vol_of_vol < 0.3:
            score += 5
            result["reasons"].append("风格稳定，波动率一致")

    result["score"] = min(100, max(0, score))

    # 评级
    if result["score"] >= 80:
        result["grade"] = "A"
    elif result["score"] >= 65:
        result["grade"] = "B"
    elif result["score"] >= 50:
        result["grade"] = "C"
    else:
        result["grade"] = "D"

    return result


def screen_managers(min_score: int = 65) -> list[dict]:
    """筛选优质基金经理管理的基金

    Returns:
        按评分排序的基金列表
    """
    from src.memory.database import execute_query

    # 获取观察池中的所有基金
    funds = execute_query(
        """SELECT DISTINCT fund_code FROM fund_nav
           GROUP BY fund_code HAVING COUNT(*) >= 120"""
    )

    results = []
    for f in funds:
        try:
            eval_result = evaluate_fund_manager(f["fund_code"])
            if eval_result["score"] >= min_score:
                results.append(eval_result)
        except Exception:
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def save_manager_evaluation(evaluations: list[dict]):
    """保存基金经理评估结果到数据库"""
    conn = get_connection()
    try:
        for e in evaluations:
            conn.execute(
                """INSERT OR REPLACE INTO fund_managers
                   (manager_id, manager_name, company, annual_return, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    e.get("fund_code", ""),
                    e.get("manager_name", ""),
                    e.get("company", ""),
                    e.get("annualized_return"),
                ),
            )
        conn.commit()
    finally:
        conn.close()
