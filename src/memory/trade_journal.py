"""交易日志 — 记录和分析历史交易"""

from rich.console import Console
from rich.table import Table

from src.memory.database import execute_query

console = Console()


def get_trade_statistics() -> dict:
    """获取交易统计数据"""
    executed = execute_query(
        "SELECT * FROM trades WHERE status = 'executed' ORDER BY trade_date"
    )

    if not executed:
        return {
            "total_trades": 0,
            "buy_trades": 0,
            "sell_trades": 0,
            "win_rate": 0,
            "avg_profit": 0,
            "avg_loss": 0,
            "profit_factor": 0,
        }

    buys = [t for t in executed if t["action"] == "buy"]
    sells = [t for t in executed if t["action"] == "sell"]

    # 分析已关闭的持仓
    closed = execute_query(
        "SELECT * FROM portfolio WHERE status = 'sold'"
    )
    profits = [p["profit_loss_pct"] for p in closed if p.get("profit_loss_pct", 0) > 0]
    losses = [p["profit_loss_pct"] for p in closed if p.get("profit_loss_pct", 0) <= 0]

    win_count = len(profits)
    loss_count = len(losses)
    total_closed = win_count + loss_count

    return {
        "total_trades": len(executed),
        "buy_trades": len(buys),
        "sell_trades": len(sells),
        "closed_positions": total_closed,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_count / total_closed * 100, 1) if total_closed > 0 else 0,
        "avg_profit": round(sum(profits) / len(profits), 2) if profits else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        "total_invested": round(sum(t["amount"] for t in buys), 2),
    }


def print_trade_journal():
    """输出交易日志摘要"""
    stats = get_trade_statistics()

    table = Table(title="交易统计")
    table.add_column("指标", style="cyan")
    table.add_column("数值")

    table.add_row("总交易次数", str(stats["total_trades"]))
    table.add_row("买入次数", str(stats["buy_trades"]))
    table.add_row("卖出次数", str(stats["sell_trades"]))
    table.add_row("已关闭持仓", str(stats.get("closed_positions", 0)))
    table.add_row("胜率", f"{stats['win_rate']:.1f}%")
    table.add_row("平均盈利", f"{stats['avg_profit']:+.2f}%")
    table.add_row("平均亏损", f"{stats['avg_loss']:+.2f}%")

    console.print(table)


def get_recent_analysis(n: int = 5) -> list[dict]:
    """获取最近 N 条分析记录"""
    return execute_query(
        "SELECT * FROM analysis_log ORDER BY created_at DESC LIMIT ?",
        (n,),
    )
