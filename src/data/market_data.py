"""市场指数与宏观数据获取"""

from rich.console import Console

from src.config import CONFIG
from src.data.fetcher import fetch_index_daily
from src.memory.database import upsert_market_index

console = Console()


def update_all_indices(start_date: str = None) -> dict:
    """更新所有关注的市场指数

    Args:
        start_date: 起始日期 'YYYY-MM-DD'

    Returns:
        dict: {index_code: record_count}
    """
    results = {}
    for idx in CONFIG["benchmark_indices"]:
        code = idx["code"]
        name = idx["name"]
        try:
            console.print(f"  获取指数 [cyan]{name}[/] ({code}) 数据...")
            df = fetch_index_daily(code, start_date=start_date)
            if df.empty:
                console.print(f"  [yellow]{name} 无数据[/]")
                results[code] = 0
                continue

            records = df.to_dict(orient="records")
            upsert_market_index(code, records)
            console.print(f"  [green]{name}: 更新 {len(records)} 条记录[/]")
            results[code] = len(records)
        except Exception as e:
            console.print(f"  [red]{name} 更新失败: {e}[/]")
            results[code] = -1

    return results


def get_latest_index_snapshot() -> list[dict]:
    """获取各指数最新数据快照"""
    from src.memory.database import execute_query

    snapshots = []
    for idx in CONFIG["benchmark_indices"]:
        rows = execute_query(
            """SELECT * FROM market_indices
               WHERE index_code = ?
               ORDER BY trade_date DESC LIMIT 1""",
            (idx["code"],),
        )
        if rows:
            row = rows[0]
            # 计算涨跌幅
            prev_rows = execute_query(
                """SELECT close FROM market_indices
                   WHERE index_code = ? AND trade_date < ?
                   ORDER BY trade_date DESC LIMIT 1""",
                (idx["code"], row["trade_date"]),
            )
            change_pct = None
            if prev_rows and prev_rows[0]["close"]:
                prev_close = prev_rows[0]["close"]
                change_pct = round((row["close"] - prev_close) / prev_close * 100, 2)

            snapshots.append({
                "code": idx["code"],
                "name": idx["name"],
                "close": row["close"],
                "trade_date": row["trade_date"],
                "change_pct": change_pct,
                "volume": row["volume"],
            })
    return snapshots
