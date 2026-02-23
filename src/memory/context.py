"""智能体上下文构建 — 汇总当前状态供分析使用"""

from datetime import datetime

from src.config import CONFIG
from src.memory.database import execute_query
from src.memory.trade_journal import get_recent_analysis, get_trade_statistics


def build_context() -> dict:
    """构建完整的分析上下文

    汇总：当前组合状态、最近分析结论、交易统计、市场快照
    """
    # 当前持仓
    holdings = execute_query(
        "SELECT p.*, f.fund_name FROM portfolio p "
        "LEFT JOIN funds f ON p.fund_code = f.fund_code "
        "WHERE p.status = 'holding'"
    )

    total_invested = sum(
        (h.get("current_nav") or h["cost_price"]) * h["shares"]
        for h in holdings
    )

    # 交易统计
    trade_stats = get_trade_statistics()

    # 最近分析
    recent_analyses = get_recent_analysis(5)

    # 最近快照
    snapshots = execute_query(
        "SELECT * FROM account_snapshots ORDER BY snapshot_date DESC LIMIT 1"
    )
    current_cash = snapshots[0]["cash"] if snapshots else CONFIG["current_cash"]

    # 观察池
    watchlist = execute_query("SELECT * FROM watchlist")

    return {
        "timestamp": datetime.now().isoformat(),
        "account": {
            "initial_capital": CONFIG["initial_capital"],
            "current_cash": current_cash,
            "total_invested": total_invested,
            "total_value": current_cash + total_invested,
            "holdings_count": len(holdings),
        },
        "holdings": [
            {
                "fund_code": h["fund_code"],
                "fund_name": h.get("fund_name", ""),
                "shares": h["shares"],
                "cost_price": h["cost_price"],
                "current_nav": h.get("current_nav"),
                "buy_date": h["buy_date"],
            }
            for h in holdings
        ],
        "trade_stats": trade_stats,
        "recent_analyses": [
            {
                "date": a["analysis_date"],
                "type": a["analysis_type"],
                "summary": a["summary"],
            }
            for a in recent_analyses
        ],
        "latest_snapshot": dict(snapshots[0]) if snapshots else None,
        "watchlist": [w["fund_code"] for w in watchlist],
        "risk_params": {
            "max_single_position": CONFIG["max_single_position_pct"],
            "max_total_position": CONFIG["max_total_position_pct"],
            "stop_loss": CONFIG["single_fund_stop_loss"],
            "max_drawdown_hard": CONFIG["max_drawdown_hard"],
        },
    }


def format_context_summary(ctx: dict) -> str:
    """将上下文格式化为可读摘要"""
    lines = [
        f"## 系统状态 ({ctx['timestamp'][:16]})",
        "",
        f"### 账户",
        f"- 初始资金: {ctx['account']['initial_capital']:,.2f} RMB",
        f"- 现金: {ctx['account']['current_cash']:,.2f} RMB",
        f"- 已投资: {ctx['account']['total_invested']:,.2f} RMB",
        f"- 总资产: {ctx['account']['total_value']:,.2f} RMB",
        f"- 持仓数: {ctx['account']['holdings_count']}",
        "",
    ]

    if ctx["holdings"]:
        lines.append("### 持仓")
        for h in ctx["holdings"]:
            pnl = ""
            if h["current_nav"] and h["cost_price"]:
                pnl_pct = (h["current_nav"] - h["cost_price"]) / h["cost_price"] * 100
                pnl = f" ({pnl_pct:+.2f}%)"
            lines.append(f"- {h['fund_name']} ({h['fund_code']}): {h['shares']:.2f}份{pnl}")
        lines.append("")

    stats = ctx["trade_stats"]
    if stats["total_trades"] > 0:
        lines.extend([
            "### 交易统计",
            f"- 总交易: {stats['total_trades']}次",
            f"- 胜率: {stats['win_rate']:.1f}%",
            "",
        ])

    if ctx["recent_analyses"]:
        lines.append("### 最近分析")
        for a in ctx["recent_analyses"][:3]:
            lines.append(f"- [{a['date']}] {a['summary']}")
        lines.append("")

    return "\n".join(lines)
