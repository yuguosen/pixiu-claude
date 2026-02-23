"""基金专项数据获取与管理"""

from rich.console import Console

from src.data.fetcher import fetch_fund_info, fetch_fund_nav
from src.memory.database import (
    get_fund_nav_history,
    upsert_fund_info,
    upsert_fund_nav,
)

console = Console()


def update_fund_nav(fund_code: str, start_date: str = None) -> int:
    """更新单只基金净值到数据库

    Args:
        fund_code: 基金代码
        start_date: 起始日期 'YYYY-MM-DD'，不传则获取全部

    Returns:
        新增/更新的记录数
    """
    console.print(f"  获取基金 [cyan]{fund_code}[/] 净值数据...")
    df = fetch_fund_nav(fund_code, start_date=start_date)
    if df.empty:
        console.print(f"  [yellow]基金 {fund_code} 无数据[/]")
        return 0

    records = df.to_dict(orient="records")
    upsert_fund_nav(fund_code, records)
    console.print(f"  [green]基金 {fund_code}: 更新 {len(records)} 条净值记录[/]")
    return len(records)


def update_fund_info(fund_code: str) -> dict | None:
    """更新基金基本信息到数据库"""
    try:
        info = fetch_fund_info(fund_code)
        if info:
            upsert_fund_info(info)
        return info
    except Exception as e:
        console.print(f"  [yellow]获取基金 {fund_code} 信息失败: {e}[/]")
        return None


def get_fund_details(fund_code: str) -> dict:
    """获取基金完整详情（合并基本信息和近期净值）"""
    info = update_fund_info(fund_code)
    if not info:
        info = {"fund_code": fund_code, "fund_name": f"基金{fund_code}"}

    nav_history = get_fund_nav_history(fund_code)
    if nav_history:
        latest = nav_history[-1]
        info["latest_nav"] = latest["nav"]
        info["latest_nav_date"] = latest["nav_date"]
        info["total_records"] = len(nav_history)

        # 计算近期收益率
        if len(nav_history) >= 2:
            current_nav = nav_history[-1]["nav"]
            for period_name, days in [
                ("return_1w", 5),
                ("return_1m", 22),
                ("return_3m", 66),
                ("return_6m", 132),
                ("return_1y", 250),
            ]:
                if len(nav_history) > days:
                    past_nav = nav_history[-1 - days]["nav"]
                    if past_nav and past_nav > 0:
                        info[period_name] = round(
                            (current_nav - past_nav) / past_nav * 100, 2
                        )

    return info


def batch_update_funds(fund_codes: list[str], start_date: str = None) -> dict:
    """批量更新多只基金数据

    Returns:
        dict: {fund_code: record_count}
    """
    results = {}
    for code in fund_codes:
        try:
            count = update_fund_nav(code, start_date=start_date)
            results[code] = count
        except Exception as e:
            console.print(f"  [red]基金 {code} 更新失败: {e}[/]")
            results[code] = -1
    return results
