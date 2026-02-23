"""组合状态报告生成"""

from datetime import datetime
from pathlib import Path

from rich.console import Console

from src.config import CONFIG
from src.memory.database import execute_query, execute_write
from src.report.templates import portfolio_template
from src.risk.drawdown import get_portfolio_drawdown

console = Console()


def generate_portfolio_report() -> str | None:
    """生成组合状态报告"""
    holdings = execute_query(
        "SELECT p.*, f.fund_name FROM portfolio p "
        "LEFT JOIN funds f ON p.fund_code = f.fund_code "
        "WHERE p.status = 'holding' ORDER BY p.buy_date"
    )

    total_invested = 0
    total_current = 0
    holdings_data = []

    for h in holdings:
        cost = h["cost_price"]
        current = h["current_nav"] or cost
        shares = h["shares"]
        pnl_pct = (current - cost) / cost * 100 if cost > 0 else 0

        total_invested += cost * shares
        total_current += current * shares

        holdings_data.append({
            "fund_code": h["fund_code"],
            "fund_name": h.get("fund_name") or f"基金{h['fund_code']}",
            "shares": shares,
            "cost_price": cost,
            "current_nav": current,
            "profit_loss_pct": round(pnl_pct, 2),
            "buy_date": h["buy_date"],
        })

    cash = CONFIG["current_cash"]
    total_value = cash + total_current
    total_return = (total_value - CONFIG["initial_capital"]) / CONFIG["initial_capital"] * 100

    drawdown = get_portfolio_drawdown()

    report_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "account": {
            "total_value": total_value,
            "cash": cash,
            "invested": total_current,
            "total_return": round(total_return, 2),
            "max_drawdown": drawdown["max_drawdown"] * 100,
        },
        "holdings": holdings_data,
    }

    report_md = portfolio_template(report_data)

    # 保存报告
    reports_dir = Path(CONFIG["reports_dir"])
    date_dir = reports_dir / datetime.now().strftime("%Y-%m")
    date_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M')}_portfolio.md"
    path = date_dir / filename
    path.write_text(report_md, encoding="utf-8")

    # 保存快照
    import json
    execute_write(
        """INSERT OR REPLACE INTO account_snapshots
           (snapshot_date, total_value, cash, invested, total_profit_loss, total_return_pct, max_drawdown_pct, holdings_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().strftime("%Y-%m-%d"),
            total_value,
            cash,
            total_current,
            total_value - CONFIG["initial_capital"],
            total_return,
            drawdown["max_drawdown"] * 100,
            json.dumps(holdings_data, ensure_ascii=False, default=str),
        ),
    )

    console.print(f"  组合报告已保存: [dim]{path}[/]")
    return str(path)
