"""买卖建议报告生成 — 量化信号 + LLM 智能裁决"""

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console

from src.analysis.indicators import get_technical_summary
from src.analysis.market_regime import detect_market_regime
from src.config import CONFIG
from src.data.market_data import get_latest_index_snapshot
from src.memory.database import classify_fund, execute_query, execute_write, get_fund_nav_history
from src.report.templates import recommendation_template
from src.risk.cost_calculator import estimate_round_trip_cost
from src.risk.drawdown import get_portfolio_drawdown
from src.risk.position_sizing import calculate_position_size
from src.strategy.portfolio import generate_composite_signals

console = Console()

import pandas as pd


def _get_llm_decision(
    regime_data: dict,
    signals: list,
    holdings: list[dict],
    total_value: float,
    cash: float,
    total_invested: float,
    drawdown_val: float,
) -> tuple[dict | None, int]:
    """调用 LLM 智能体进行决策

    Returns:
        (decision_dict, tokens_used) 或 (None, 0)
    """
    try:
        from src.agent.brain import analyze_market, make_decision, save_agent_decision
        from src.agent.llm import get_provider, get_critical_model
    except ImportError:
        console.print("  [dim]LLM 模块未安装，使用纯量化模式[/]")
        return None, 0

    # 1. 获取市场数据
    indices = get_latest_index_snapshot()
    fund_flow_signals = []
    try:
        from src.analysis.fund_flow import get_fund_flow_composite
        flow = get_fund_flow_composite()
        fund_flow_signals = flow.get("signals", [])
    except Exception:
        pass

    hotspots = []
    try:
        from src.memory.database import execute_query as eq
        hotspots = eq(
            "SELECT * FROM hotspots WHERE status = 'active' ORDER BY score DESC LIMIT 5"
        )
    except Exception:
        pass

    # 2. LLM 市场分析 (Haiku)
    console.print("  [dim]LLM 市场分析中...[/]")
    total_tokens = 0
    assessment, tokens = analyze_market(
        regime_data or {"regime": "ranging", "description": "", "trend_score": 0, "volatility": 0},
        indices or [],
        fund_flow_signals,
        hotspots,
    )
    total_tokens += tokens
    if assessment:
        console.print(f"  [dim]市场情绪: {assessment.sentiment} ({tokens} tokens)[/]")
        market_summary = assessment.narrative
    else:
        market_summary = f"市场状态: {regime_data.get('regime', 'unknown')}" if regime_data else "数据不足"

    # 3. 准备量化信号 (含资产类别标签)
    quant_signals = []
    category_signal_counts: dict[str, dict[str, int]] = {}
    for sig in signals[:10]:
        fund_info = execute_query(
            "SELECT fund_name FROM funds WHERE fund_code = ?",
            (sig.fund_code,),
        )
        fund_name = fund_info[0]["fund_name"] if fund_info else f"基金{sig.fund_code}"
        category = sig.metadata.get("category") if sig.metadata else classify_fund(sig.fund_code)
        quant_signals.append({
            "fund_code": sig.fund_code,
            "fund_name": fund_name,
            "category": category,
            "signal_type": sig.signal_type.name,
            "confidence": sig.confidence,
            "reason": sig.reason,
            "strategy_name": sig.strategy_name,
        })
        # 统计各类别信号方向
        if category not in category_signal_counts:
            category_signal_counts[category] = {"BUY": 0, "SELL": 0, "HOLD": 0}
        if sig.is_buy:
            category_signal_counts[category]["BUY"] += 1
        elif sig.is_sell:
            category_signal_counts[category]["SELL"] += 1
        else:
            category_signal_counts[category]["HOLD"] += 1

    # 4. 获取历史教训
    knowledge = []
    try:
        from src.agent.reflection import get_relevant_knowledge
        knowledge = get_relevant_knowledge(regime_data.get("regime", "ranging") if regime_data else "ranging")
    except Exception:
        pass

    # 5. LLM 决策 (Sonnet) — 注入跨资产配置上下文
    console.print("  [dim]LLM 决策推理中 (三步反思)...[/]")

    # 获取当前资产配置
    try:
        from src.risk.asset_allocation import get_current_allocation, get_target_allocation
        current_alloc = get_current_allocation()
        target_alloc = get_target_allocation()
    except Exception:
        current_alloc = {"equity": 0, "bond": 0, "cash": 1.0}
        target_alloc = {"equity": 0.45, "bond": 0.25, "cash": 0.30}

    # 构建资产配置摘要
    CATEGORY_NAMES = {"equity": "偏股", "bond": "债券", "index": "指数", "gold": "黄金", "qdii": "QDII"}
    signal_summary_parts = []
    for cat, counts in category_signal_counts.items():
        cat_name = CATEGORY_NAMES.get(cat, cat)
        parts = []
        if counts["BUY"] > 0:
            parts.append(f"{counts['BUY']} BUY")
        if counts["SELL"] > 0:
            parts.append(f"{counts['SELL']} SELL")
        if parts:
            signal_summary_parts.append(f"{cat_name}: {' / '.join(parts)}")

    allocation_context = (
        f"各类别信号汇总: {'; '.join(signal_summary_parts) if signal_summary_parts else '无信号'}\n"
        f"当前配置: 偏股 {current_alloc.get('equity', 0):.0%} | 债券 {current_alloc.get('bond', 0):.0%} | 现金 {current_alloc.get('cash', 1):.0%}\n"
        f"目标配置: 偏股 {target_alloc.get('equity', 0.45):.0%} | 债券 {target_alloc.get('bond', 0.25):.0%} | 现金 {target_alloc.get('cash', 0.30):.0%}\n"
        f"你需要在不同资产类别间做配置决策，优先修复配置偏差。"
    )

    # ── 增强上下文: 估值/宏观/情绪/新闻 ──
    enhanced_parts = []
    try:
        from src.data.valuation import get_valuation_signal
        v = get_valuation_signal()
        enhanced_parts.append(f"估值: {v.get('narrative', '')}")
    except Exception:
        pass
    try:
        from src.data.macro import get_macro_snapshot
        m = get_macro_snapshot()
        enhanced_parts.append(f"宏观: {m.get('narrative', '')}")
    except Exception:
        pass
    try:
        from src.data.sentiment import get_sentiment_snapshot
        s = get_sentiment_snapshot()
        enhanced_parts.append(f"情绪: {s.get('narrative', '')}")
    except Exception:
        pass
    try:
        from src.agent.news import summarize_news_for_llm
        news = summarize_news_for_llm(max_items=5)
        if news and news != "暂无最新新闻数据":
            enhanced_parts.append(f"新闻:\n{news}")
    except Exception:
        pass
    enhanced_context = "\n".join(enhanced_parts) if enhanced_parts else ""

    # ── MI 市场情报 ──
    mi_context = ""
    try:
        from src.agent.market_intel import get_latest_intel, format_intel_for_decision
        intel = get_latest_intel()
        if intel:
            mi_context = format_intel_for_decision(intel)
    except Exception:
        pass

    portfolio_state = {
        "total_value": total_value,
        "cash": cash,
        "invested": total_invested,
        "drawdown": drawdown_val,
        "holdings": holdings,
        "allocation_context": allocation_context,
        "enhanced_context": enhanced_context,
        "mi_context": mi_context,
    }
    decision, tokens = make_decision(
        market_summary=market_summary,
        quant_signals=quant_signals,
        portfolio_state=portfolio_state,
        knowledge=knowledge,
    )
    total_tokens += tokens

    if decision:
        console.print(f"  [dim]决策完成 ({tokens} tokens, 总计 {total_tokens} tokens)[/]")

        # 6. 保存决策记录
        llm_config = CONFIG.get("llm", {})
        save_agent_decision(
            decision=decision,
            market_context=market_summary,
            quant_signals_json=json.dumps(quant_signals, ensure_ascii=False),
            model_used=f"{get_provider()}:{get_critical_model()}",
            tokens_used=total_tokens,
        )

    return decision, total_tokens


def generate_recommendation() -> str | None:
    """生成今日交易建议报告

    Returns:
        报告文件路径，无建议时返回 None
    """
    console.print("[bold]生成交易建议...[/]")

    # 0. 检查是否为交易日
    from datetime import datetime
    today = datetime.now()
    if today.weekday() >= 5:
        console.print("[yellow]今日为周末，非交易日，暂缓执行交易调仓。[/yellow]")
        return None
        
    try:
        import akshare as ak
        trade_dates = ak.tool_trade_date_hist_sina()
        today_str = today.strftime("%Y-%m-%d")
        if "trade_date" in trade_dates.columns and today_str not in trade_dates["trade_date"].astype(str).values:
            console.print(f"[yellow]今日 ({today_str}) 为法定节假日/非交易日，A股休市，暂缓执行交易调仓。[/yellow]")
            return None
    except Exception as e:
        console.print(f"  [dim]交易日历校验失败: {e}，继续执行流程[/]")

    # 1. 市场分析
    regime_data = detect_market_regime()
    regime = regime_data["regime"] if regime_data else "ranging"

    # 1b. 季节性因子
    from src.analysis.seasonal import get_seasonal_modifier
    seasonal_mod, seasonal_reason = get_seasonal_modifier()

    # 2. 生成信号
    signals = generate_composite_signals()
    # 应用季节性修正: 仅限A股权益及指数基金，调整信号置信度
    if seasonal_mod != 0 and signals:
        for sig in signals:
            if classify_fund(sig.fund_code) not in ("equity", "index"):
                continue
            if sig.is_buy:
                sig.confidence = round(min(0.95, max(0.1, sig.confidence + seasonal_mod)), 2)
            elif sig.is_sell:
                sig.confidence = round(min(0.95, max(0.1, sig.confidence - seasonal_mod)), 2)
    if not signals:
        console.print("[yellow]当前无明确交易信号[/]")
        # 仍然生成 HOLD 报告
        return _generate_hold_report(regime_data)

    # 3. 获取账户状态
    holdings = execute_query(
        "SELECT * FROM portfolio WHERE status = 'holding'"
    )
    holding_codes = {h["fund_code"] for h in holdings}
    existing_positions = len(holdings)

    # 计算当前总资产
    total_invested = sum(
        (h.get("current_nav") or h["cost_price"]) * h["shares"]
        for h in holdings
    )
    snapshots = execute_query("SELECT cash FROM account_snapshots ORDER BY snapshot_date DESC LIMIT 1")
    cash = snapshots[0]["cash"] if snapshots else CONFIG["current_cash"]
    total_value = cash + total_invested

    drawdown = get_portfolio_drawdown()
    drawdown_val = drawdown["current_drawdown"]

    # 4. LLM 智能决策
    llm_decision = None
    llm_tokens = 0
    llm_config = CONFIG.get("llm", {})
    try:
        llm_decision, llm_tokens = _get_llm_decision(
            regime_data, signals, holdings,
            total_value, cash, total_invested, drawdown_val,
        )
    except Exception as e:
        console.print(f"  [yellow]LLM 决策跳过: {e}[/]")

    # 5. 组装建议 — LLM 增强或纯量化回退
    recommendations = []

    if llm_decision and llm_decision.get("recommendations"):
        # LLM 增强模式: 使用 LLM 的推荐，补充量化细节
        remaining_cash_llm = cash
        batch_positions_llm = existing_positions
        batch_holdings_llm = [h["fund_code"] for h in holdings]

        for llm_rec in llm_decision["recommendations"]:
            fund_code = llm_rec.get("fund_code", "")
            action = llm_rec.get("action", "hold")

            rec = {
                "fund_code": fund_code,
                "fund_name": llm_rec.get("fund_name", f"基金{fund_code}"),
                "confidence": llm_rec.get("confidence", 0.5),
                "reason": llm_rec.get("reasoning", ""),
                "llm_key_factors": llm_rec.get("key_factors", []),
                "llm_risks": llm_rec.get("risks", []),
                "llm_stop_loss": llm_rec.get("stop_loss_trigger", ""),
            }

            # 映射动作
            if action == "buy":
                rec["action_label"] = "买入"
                amount = llm_rec.get("amount", 0)
                if amount <= 0:
                    amount = calculate_position_size(
                        total_capital=total_value,
                        current_cash=remaining_cash_llm,
                        confidence=rec["confidence"],
                        regime=regime,
                        existing_positions=batch_positions_llm,
                        fund_code=fund_code,
                        existing_holdings=batch_holdings_llm,
                    )
                # 无论 LLM 建议多少，不超过可用现金
                amount = min(amount, remaining_cash_llm * 0.9)
                rec["amount"] = amount
                if amount > 0:
                    rec["cost"] = estimate_round_trip_cost(amount)
                    remaining_cash_llm -= amount
                    batch_positions_llm += 1
                    batch_holdings_llm.append(fund_code)
            elif action == "sell":
                rec["action_label"] = "卖出"
                fund_holdings = [h for h in holdings if h["fund_code"] == fund_code]
                if fund_holdings:
                    h = fund_holdings[0]
                    rec["amount"] = (h.get("current_nav") or h["cost_price"]) * h["shares"]
                else:
                    rec["amount"] = 0
                    rec["action_label"] = "观望（未持有）"
            elif action == "watch":
                rec["action_label"] = "观望"
                rec["amount"] = 0
            else:
                rec["action_label"] = "持有"
                rec["amount"] = 0

            # 技术指标
            nav_history = get_fund_nav_history(fund_code)
            if nav_history:
                navs = pd.Series([r["nav"] for r in nav_history])
                tech = get_technical_summary(navs)
                rec["tech_summary"] = tech

            # 风险评估
            rec["risk"] = {
                "max_loss_pct": -CONFIG["single_fund_stop_loss"] * 100,
                "position_pct": rec.get("amount", 0) / total_value if total_value > 0 else 0,
            }

            recommendations.append(rec)
    else:
        # 纯量化回退模式 — 追踪累计分配，避免超配
        remaining_cash = cash
        batch_positions = existing_positions
        batch_holdings = [h["fund_code"] for h in holdings]

        for sig in signals[:5]:
            rec = {
                "fund_code": sig.fund_code,
                "confidence": sig.confidence,
                "reason": sig.reason,
            }

            fund_info = execute_query(
                "SELECT fund_name FROM funds WHERE fund_code = ?",
                (sig.fund_code,),
            )
            rec["fund_name"] = fund_info[0]["fund_name"] if fund_info else f"基金{sig.fund_code}"

            if sig.is_buy:
                rec["action_label"] = "买入"
                amount = calculate_position_size(
                    total_capital=total_value,
                    current_cash=remaining_cash,
                    confidence=sig.confidence,
                    regime=regime,
                    existing_positions=batch_positions,
                    fund_code=sig.fund_code,
                    existing_holdings=batch_holdings,
                )
                rec["amount"] = amount
                if amount > 0:
                    rec["cost"] = estimate_round_trip_cost(amount)
                    remaining_cash -= amount  # 扣减已分配
                    batch_positions += 1
                    batch_holdings.append(sig.fund_code)
            elif sig.is_sell:
                rec["action_label"] = "卖出"
                fund_holdings = [h for h in holdings if h["fund_code"] == sig.fund_code]
                if fund_holdings:
                    h = fund_holdings[0]
                    rec["amount"] = (h.get("current_nav") or h["cost_price"]) * h["shares"]
                else:
                    rec["amount"] = 0
                    rec["action_label"] = "观望（未持有）"
            else:
                rec["action_label"] = "持有"
                rec["amount"] = 0

            nav_history = get_fund_nav_history(sig.fund_code)
            if nav_history:
                navs = pd.Series([r["nav"] for r in nav_history])
                tech = get_technical_summary(navs)
                rec["tech_summary"] = tech

            rec["risk"] = {
                "max_loss_pct": -CONFIG["single_fund_stop_loss"] * 100,
                "position_pct": rec.get("amount", 0) / total_value if total_value > 0 else 0,
            }

            recommendations.append(rec)

        # 过滤掉金额为 0 的买入建议
        recommendations = [r for r in recommendations if r.get("amount", 0) > 0 or r["action_label"] not in ("买入",)]

    # 6. 组装报告数据
    indices = get_latest_index_snapshot()

    # 资金流向信号
    fund_flow_signals = []
    try:
        from src.analysis.fund_flow import get_fund_flow_composite
        flow = get_fund_flow_composite()
        fund_flow_signals = flow.get("signals", [])
    except Exception:
        pass

    # 获取配置数据
    try:
        from src.risk.asset_allocation import get_current_allocation, get_target_allocation
        _current_alloc = get_current_allocation()
        _target_alloc = get_target_allocation()
    except Exception:
        _current_alloc = {"equity": 0, "bond": 0, "cash": 1.0}
        _target_alloc = {"equity": 0.45, "bond": 0.25, "cash": 0.30}

    report_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "recommendations": recommendations,
        "market": {
            "regime": regime,
            "description": regime_data.get("description", "") if regime_data else "",
            "trend_score": regime_data.get("trend_score", 0) if regime_data else 0,
            "volatility": regime_data.get("volatility", 0) if regime_data else 0,
            "indices": indices,
            "fund_flow_signals": fund_flow_signals,
        },
        "account": {
            "total_value": total_value,
            "cash": cash,
            "invested": total_invested,
            "drawdown": drawdown_val,
        },
        "asset_allocation": {
            "current": _current_alloc,
            "target": _target_alloc,
        },
    }

    # LLM 分析内容注入报告
    if llm_decision:
        thinking = llm_decision.get("thinking_process", {})
        assessment = llm_decision.get("market_assessment", {})
        report_data["llm_analysis"] = {
            "initial_judgment": thinking.get("initial_judgment", ""),
            "challenge": thinking.get("challenge", ""),
            "final_conclusion": thinking.get("final_conclusion", ""),
            "market_narrative": assessment.get("narrative", ""),
            "sentiment": assessment.get("sentiment", ""),
            "portfolio_advice": llm_decision.get("portfolio_advice", ""),
            "confidence_summary": llm_decision.get("confidence_summary", ""),
            "tokens_used": llm_tokens,
        }

    # 7. 生成报告文件
    report_md = recommendation_template(report_data)
    report_path = _save_report(report_md, "recommendation")

    # 8. 记录建议到数据库
    for rec in recommendations:
        if rec.get("amount", 0) > 0 and rec["action_label"] in ("买入", "卖出"):
            action = "buy" if rec["action_label"] == "买入" else "sell"
            nav_history = get_fund_nav_history(rec["fund_code"])
            nav = nav_history[-1]["nav"] if nav_history else 0
            execute_write(
                """INSERT INTO trades
                   (trade_date, fund_code, action, amount, nav, confidence, reason, report_path, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    datetime.now().strftime("%Y-%m-%d"),
                    rec["fund_code"],
                    action,
                    rec["amount"],
                    nav,
                    rec["confidence"],
                    rec["reason"][:500],
                    report_path,
                ),
            )

    # 显示摘要
    mode = "LLM 增强" if llm_decision else "量化"
    console.print(f"\n[bold]═══ 今日建议 ({regime}, {mode}模式) ═══[/]")
    for rec in recommendations:
        action = rec["action_label"]
        color = "green" if action == "买入" else "red" if action == "卖出" else "yellow"
        console.print(
            f"  [{color}]{action}[/] {rec['fund_name']} ({rec['fund_code']}) "
            f"— {rec.get('amount', 0):,.2f} RMB "
            f"(置信度: {rec['confidence']:.0%})"
        )

    if llm_decision:
        thinking = llm_decision.get("thinking_process", {})
        if thinking.get("final_conclusion"):
            console.print(f"\n  [dim]LLM 结论: {thinking['final_conclusion'][:200]}[/]")

    # 记录分析日志
    execute_write(
        """INSERT INTO analysis_log (analysis_date, analysis_type, summary, doc_path)
           VALUES (?, 'daily', ?, ?)""",
        (
            datetime.now().strftime("%Y-%m-%d"),
            f"市场状态: {regime}, {mode}模式, 生成 {len(recommendations)} 条建议",
            report_path,
        ),
    )

    return report_path


def _generate_hold_report(regime_data: dict | None) -> str | None:
    """无信号时生成持有报告"""
    indices = get_latest_index_snapshot()
    regime = regime_data["regime"] if regime_data else "ranging"

    # 资金流向信号
    fund_flow_signals = []
    try:
        from src.analysis.fund_flow import get_fund_flow_composite
        flow = get_fund_flow_composite()
        fund_flow_signals = flow.get("signals", [])
    except Exception:
        pass

    try:
        from src.memory.database import execute_query
        snapshots = execute_query("SELECT cash, invested FROM account_snapshots ORDER BY snapshot_date DESC LIMIT 1")
        if snapshots:
            account_cash = snapshots[0]["cash"]
            total_value = snapshots[0]["cash"] + snapshots[0]["invested"]
        else:
            account_cash = CONFIG["current_cash"]
            total_value = CONFIG["initial_capital"]
    except Exception:
        account_cash = CONFIG["current_cash"]
        total_value = CONFIG["initial_capital"]

    report_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "recommendations": [{
            "fund_code": "-",
            "fund_name": "-",
            "action_label": "持有/观望",
            "confidence": 0,
            "amount": 0,
            "reason": "当前各策略未产生一致性信号，建议保持现有仓位观望",
        }],
        "market": {
            "regime": regime,
            "description": regime_data.get("description", "") if regime_data else "",
            "trend_score": regime_data.get("trend_score", 0) if regime_data else 0,
            "volatility": regime_data.get("volatility", 0) if regime_data else 0,
            "indices": indices,
            "fund_flow_signals": fund_flow_signals,
        },
        "account": {
            "total_value": total_value,
            "cash": account_cash,
            "invested": total_value - account_cash,
            "drawdown": 0,
        },
    }

    report_md = recommendation_template(report_data)
    return _save_report(report_md, "recommendation")


def _save_report(content: str, report_type: str) -> str:
    """保存报告到文件"""
    reports_dir = Path(CONFIG["reports_dir"])
    date_dir = reports_dir / datetime.now().strftime("%Y-%m")
    date_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{datetime.now().strftime('%Y%m%d_%H%M')}_{report_type}.md"
    path = date_dir / filename
    path.write_text(content, encoding="utf-8")

    console.print(f"  报告已保存: [dim]{path}[/]")
    return str(path)
