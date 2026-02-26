"""业务适配层 — 调用现有 Pixiu 模块, 返回卡片数据"""

import logging
from datetime import datetime

from src.bot import cards

logger = logging.getLogger(__name__)


def handle_help() -> dict:
    return cards.help_card()


def handle_portfolio() -> dict:
    """查询持仓并构建卡片"""
    from src.config import CONFIG
    from src.memory.database import execute_query

    holdings = execute_query(
        "SELECT * FROM portfolio WHERE status = 'holding' ORDER BY buy_date"
    )

    if not holdings:
        return cards.portfolio_card([], CONFIG["current_cash"], 0, 0)

    total_invested = 0.0
    total_current = 0.0
    for h in holdings:
        cost = h["cost_price"]
        current = h["current_nav"] or cost
        total_invested += cost * h["shares"]
        total_current += current * h["shares"]

    snapshots = execute_query(
        "SELECT cash FROM account_snapshots ORDER BY snapshot_date DESC LIMIT 1"
    )
    cash = snapshots[0]["cash"] if snapshots else CONFIG["current_cash"]

    return cards.portfolio_card(holdings, cash, total_invested, total_current)


def handle_history(limit: int = 20) -> dict:
    """查询交易历史"""
    from src.memory.database import execute_query

    trades = execute_query(
        "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    return cards.history_card(trades, limit)


def handle_market() -> dict:
    """市场快照"""
    regime = None
    snapshots = None

    try:
        from src.data.market_data import get_latest_index_snapshot
        snapshots = get_latest_index_snapshot()
    except Exception as e:
        logger.warning("获取指数快照失败: %s", e)

    # 回退: DB 无数据时从 AKShare 实时获取
    if not snapshots:
        try:
            from src.data.market_data import get_realtime_index_snapshot
            snapshots = get_realtime_index_snapshot()
        except Exception as e:
            logger.warning("实时指数获取失败: %s", e)

    try:
        from src.analysis.market_regime import detect_market_regime
        regime = detect_market_regime()
    except Exception as e:
        logger.warning("检测市场状态失败: %s", e)

    return cards.market_card(regime, snapshots)


def handle_market_sector(keyword: str) -> dict:
    """按关键词查询行业/概念板块行情"""
    try:
        from src.analysis.sector_rotation import search_sector_or_concept, get_board_detail

        match = search_sector_or_concept(keyword)
        if not match:
            return cards.error_card(
                f"未找到匹配 \"{keyword}\" 的板块\n\n"
                "试试: 半导体、光伏、白酒、新能源车、DeepSeek"
            )

        detail = get_board_detail(
            match["name"], match["type"],
            cached_realtime=match.get("realtime_row"),
        )
        if not detail:
            return cards.error_card(f"获取 {match['name']} 数据失败")

        return cards.sector_market_card(keyword, match, detail)
    except Exception as e:
        logger.exception("板块行情查询失败")
        return cards.error_card(f"板块行情查询失败: {e}")


def handle_recommend() -> dict:
    """生成交易建议 (耗时操作)"""
    try:
        from src.report.recommendation import generate_recommendation
        report_path = generate_recommendation()
        if report_path:
            # 尝试从数据库获取本次建议
            from src.memory.database import execute_query
            today = datetime.now().strftime("%Y-%m-%d")
            recs = execute_query(
                "SELECT * FROM trades WHERE trade_date = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 5",
                (today,),
            )
            rec_list = []
            for r in recs:
                fund_info = execute_query(
                    "SELECT fund_name FROM funds WHERE fund_code = ?",
                    (r["fund_code"],),
                )
                rec_list.append({
                    "fund_code": r["fund_code"],
                    "fund_name": fund_info[0]["fund_name"] if fund_info else r["fund_code"],
                    "action_label": "买入" if r["action"] == "buy" else "卖出",
                    "amount": r["amount"],
                    "confidence": r.get("confidence", 0),
                    "reason": r.get("reason", ""),
                })
            return cards.recommendation_card(report_path, rec_list or None)
        else:
            return cards.error_card("今日无交易建议 (非交易日或无信号)")
    except Exception as e:
        logger.exception("生成建议失败")
        return cards.error_card(f"生成建议失败: {e}")


def handle_daily() -> dict:
    """完整日常流程 (耗时操作)"""
    try:
        from src.main import cmd_daily
        cmd_daily([])

        summary = _extract_daily_summary()
        return cards.daily_summary_card(True, summary=summary)
    except Exception as e:
        logger.exception("日报流程失败")
        return cards.daily_summary_card(False, error=str(e))


def _extract_daily_summary() -> dict:
    """从数据库提取日报关键数据"""
    from src.memory.database import execute_query

    summary: dict = {}
    today = datetime.now().strftime("%Y-%m-%d")

    # 1. 市场状态
    try:
        from src.analysis.market_regime import detect_market_regime
        regime = detect_market_regime()
        if regime:
            summary["regime"] = regime
    except Exception:
        pass

    # 2. 指数快照
    try:
        from src.data.market_data import get_latest_index_snapshot, get_realtime_index_snapshot
        indices = get_latest_index_snapshot()
        if not indices:
            indices = get_realtime_index_snapshot()
        if indices:
            summary["indices"] = indices
    except Exception:
        pass

    # 3. 今日建议
    try:
        recs = execute_query(
            """SELECT t.fund_code, t.action, t.amount, t.confidence, t.reason,
                      f.fund_name
               FROM trades t
               LEFT JOIN funds f ON t.fund_code = f.fund_code
               WHERE t.trade_date = ? AND t.status = 'pending'
               ORDER BY t.created_at DESC""",
            (today,),
        )
        if recs:
            summary["recommendations"] = recs
    except Exception:
        pass

    # 4. LLM 决策结论
    try:
        decisions = execute_query(
            """SELECT reasoning FROM agent_decisions
               WHERE decision_date = ? ORDER BY id DESC LIMIT 1""",
            (today,),
        )
        if decisions and decisions[0].get("reasoning"):
            summary["llm_conclusion"] = decisions[0]["reasoning"]
    except Exception:
        pass

    # 5. 报告路径
    from pathlib import Path
    from src.config import CONFIG
    reports_dir = Path(CONFIG["reports_dir"])
    date_dir = reports_dir / datetime.now().strftime("%Y-%m")
    if date_dir.exists():
        reports = sorted(date_dir.glob("*_recommendation.md"), reverse=True)
        if reports:
            summary["report_path"] = str(reports[0])

    return summary


def handle_allocation() -> dict:
    """资产配置检查"""
    try:
        from src.risk.asset_allocation import check_allocation_compliance

        pe_pct = 50.0
        try:
            from src.data.valuation import get_valuation_signal
            v = get_valuation_signal()
            pe_pct = v.get("pe_percentile", 50)
        except Exception:
            pass

        regime = "ranging"
        try:
            from src.analysis.market_regime import detect_market_regime
            rd = detect_market_regime()
            regime = rd["regime"] if rd else "ranging"
        except Exception:
            pass

        result = check_allocation_compliance(regime, pe_pct)
        return cards.allocation_card(result, regime, pe_pct)
    except Exception as e:
        logger.exception("配置检查失败")
        return cards.error_card(f"配置检查失败: {e}")


def handle_search(keyword: str) -> dict:
    """按关键词搜索基金 (耗时操作)"""
    try:
        from src.data.fund_discovery import discover_by_theme

        keywords = keyword.split()
        results = discover_by_theme(keywords)
        return cards.search_card(keyword, results)
    except Exception as e:
        logger.exception("搜索失败")
        return cards.error_card(f"搜索失败: {e}")


def handle_trade_record(trade_data: dict) -> dict:
    """将交易录入写入数据库"""
    try:
        from src.memory.database import execute_write

        fund_code = trade_data["fund_code"]
        action = trade_data["action"]
        amount = trade_data["amount"]
        nav = trade_data["nav"]
        trade_date = trade_data["trade_date"]
        reason = trade_data.get("reason", "")
        shares = amount / nav if nav > 0 else 0

        execute_write(
            """INSERT INTO trades (trade_date, fund_code, action, amount, nav, shares, reason, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'executed')""",
            (trade_date, fund_code, action, amount, nav, shares, reason),
        )

        if action == "buy":
            execute_write(
                """INSERT INTO portfolio (fund_code, shares, cost_price, current_nav, buy_date, status)
                   VALUES (?, ?, ?, ?, ?, 'holding')""",
                (fund_code, shares, nav, nav, trade_date),
            )

        return cards.trade_success_card(trade_data)
    except Exception as e:
        logger.exception("交易记录失败")
        return cards.error_card(f"交易记录失败: {e}")
