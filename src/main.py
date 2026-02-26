"""貔貅 (Pixiu) - 智能基金交易分析系统 CLI 入口"""

import sys
from datetime import datetime, timedelta

from rich.console import Console
from rich.table import Table

from src.config import CONFIG
from src.memory.database import init_db

console = Console()


def cmd_update(args: list[str]):
    """更新市场数据"""
    from src.data.fund_data import batch_update_funds
    from src.data.market_data import update_all_indices

    # 默认获取近1年数据
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    if args and args[0].startswith("--from="):
        start_date = args[0].split("=")[1]

    console.print("\n[bold]更新市场指数数据...[/]")
    index_results = update_all_indices(start_date=start_date)

    # 更新观察池中的基金
    from src.memory.database import execute_query
    watchlist = execute_query("SELECT fund_code FROM watchlist")
    fund_codes = [w["fund_code"] for w in watchlist]

    # 如果观察池为空，提供一些默认基金
    if not fund_codes:
        fund_codes = [
            "110011",  # 易方达中小盘
            "161725",  # 招商中证白酒指数
            "003834",  # 华夏能源革新
            "005827",  # 易方达蓝筹精选
            "320007",  # 诺安成长混合
        ]
        console.print(f"\n[bold]观察池为空，使用默认基金列表 ({len(fund_codes)} 只)...[/]")

    if fund_codes:
        console.print(f"\n[bold]更新基金净值数据 ({len(fund_codes)} 只)...[/]")
        batch_update_funds(fund_codes, start_date=start_date)

    console.print("\n[bold green]数据更新完成![/]")


def cmd_fund(args: list[str]):
    """查看单只基金详情"""
    if not args:
        console.print("[red]请指定基金代码，如: uv run src/main.py fund 110011[/]")
        return

    from src.data.fund_data import get_fund_details

    fund_code = args[0]
    console.print(f"\n[bold]查询基金 {fund_code} ...[/]")

    details = get_fund_details(fund_code)

    table = Table(title=f"基金详情 - {details.get('fund_name', fund_code)}")
    table.add_column("项目", style="cyan")
    table.add_column("数值", style="green")

    table.add_row("基金代码", details.get("fund_code", ""))
    table.add_row("基金名称", details.get("fund_name", ""))
    table.add_row("基金类型", details.get("fund_type", ""))
    table.add_row("基金公司", details.get("management_company", ""))
    table.add_row("成立日期", details.get("establishment_date", ""))
    table.add_row("业绩基准", str(details.get("benchmark", "")))

    if "latest_nav" in details:
        table.add_row("最新净值", f"{details['latest_nav']:.4f}")
        table.add_row("净值日期", details.get("latest_nav_date", ""))
        table.add_row("数据条数", str(details.get("total_records", 0)))

    for label, key in [
        ("近1周", "return_1w"),
        ("近1月", "return_1m"),
        ("近3月", "return_3m"),
        ("近6月", "return_6m"),
        ("近1年", "return_1y"),
    ]:
        if key in details:
            val = details[key]
            color = "green" if val >= 0 else "red"
            table.add_row(f"{label}收益", f"[{color}]{val:+.2f}%[/]")

    console.print(table)


def cmd_portfolio(args: list[str]):
    """查看当前组合状态"""
    from src.memory.database import execute_query

    holdings = execute_query(
        "SELECT * FROM portfolio WHERE status = 'holding' ORDER BY buy_date"
    )

    if not holdings:
        console.print("\n[yellow]当前无持仓[/]")
        console.print(f"现金: [green]{CONFIG['current_cash']:,.2f} RMB[/]")
        return

    table = Table(title="当前持仓")
    table.add_column("基金代码", style="cyan")
    table.add_column("份额")
    table.add_column("成本价")
    table.add_column("当前净值")
    table.add_column("盈亏")
    table.add_column("买入日期")

    total_invested = 0
    total_current = 0
    for h in holdings:
        shares = h["shares"]
        cost = h["cost_price"]
        current = h["current_nav"] or cost
        pl = (current - cost) * shares
        pl_pct = (current - cost) / cost * 100 if cost > 0 else 0
        total_invested += cost * shares
        total_current += current * shares

        color = "green" if pl >= 0 else "red"
        table.add_row(
            h["fund_code"],
            f"{shares:.2f}",
            f"{cost:.4f}",
            f"{current:.4f}",
            f"[{color}]{pl:+.2f} ({pl_pct:+.2f}%)[/]",
            h["buy_date"],
        )

    console.print(table)
    total_pl = total_current - total_invested
    color = "green" if total_pl >= 0 else "red"
    console.print(f"投资总额: {total_invested:,.2f} RMB")
    console.print(f"当前市值: {total_current:,.2f} RMB")
    console.print(f"总盈亏: [{color}]{total_pl:+,.2f} RMB[/]")


def cmd_history(args: list[str]):
    """查看交易历史"""
    from src.memory.database import execute_query

    limit = 20
    if args and args[0].isdigit():
        limit = int(args[0])

    trades = execute_query(
        "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
    )

    if not trades:
        console.print("\n[yellow]暂无交易记录[/]")
        return

    table = Table(title=f"最近 {limit} 条交易记录")
    table.add_column("日期", style="cyan")
    table.add_column("基金")
    table.add_column("操作")
    table.add_column("金额")
    table.add_column("净值")
    table.add_column("状态")

    for t in trades:
        action_color = "green" if t["action"] == "buy" else "red"
        table.add_row(
            t["trade_date"],
            t["fund_code"],
            f"[{action_color}]{t['action']}[/]",
            f"{t['amount']:,.2f}",
            f"{t['nav']:.4f}",
            t["status"],
        )

    console.print(table)


def cmd_watchlist(args: list[str]):
    """管理观察池"""
    from src.memory.database import execute_query, execute_write

    if args and args[0] == "add" and len(args) >= 2:
        fund_code = args[1]
        reason = " ".join(args[2:]) if len(args) > 2 else ""
        execute_write(
            """INSERT OR REPLACE INTO watchlist (fund_code, added_date, reason, target_action)
               VALUES (?, ?, ?, 'watch')""",
            (fund_code, datetime.now().strftime("%Y-%m-%d"), reason),
        )
        console.print(f"[green]已添加 {fund_code} 到观察池[/]")
        return

    if args and args[0] == "remove" and len(args) >= 2:
        execute_write("DELETE FROM watchlist WHERE fund_code = ?", (args[1],))
        console.print(f"[yellow]已从观察池移除 {args[1]}[/]")
        return

    # 显示观察池
    watchlist = execute_query("SELECT * FROM watchlist ORDER BY added_date DESC")
    if not watchlist:
        console.print("\n[yellow]观察池为空[/]")
        console.print("添加基金: uv run src/main.py watchlist add <基金代码> [原因]")
        return

    # 分类统计
    category_counts: dict[str, int] = {}
    for w in watchlist:
        cat = w.get("category") or "equity"
        category_counts[cat] = category_counts.get(cat, 0) + 1

    CATEGORY_NAMES = {"equity": "偏股", "bond": "债券", "index": "指数", "gold": "黄金", "qdii": "QDII"}
    stats = " | ".join(f"{CATEGORY_NAMES.get(k, k)} {v}" for k, v in sorted(category_counts.items()))
    console.print(f"\n[dim]分类统计: {stats} | 合计 {len(watchlist)}[/]\n")

    table = Table(title="观察池")
    table.add_column("基金代码", style="cyan")
    table.add_column("类别", style="magenta")
    table.add_column("添加日期")
    table.add_column("目标操作")
    table.add_column("备注")

    for w in watchlist:
        cat = w.get("category") or "equity"
        cat_label = CATEGORY_NAMES.get(cat, cat)
        table.add_row(
            w["fund_code"], cat_label, w["added_date"], w["target_action"] or "", w["reason"] or ""
        )
    console.print(table)


def cmd_analyze(args: list[str]):
    """执行市场分析（阶段2实现）"""
    from src.analysis.market_regime import detect_market_regime
    from src.analysis.fund_scorer import screen_and_score_funds
    from src.data.market_data import get_latest_index_snapshot

    console.print("\n[bold]执行市场分析...[/]")

    # 指数快照
    snapshots = get_latest_index_snapshot()
    if snapshots:
        table = Table(title="市场指数概况")
        table.add_column("指数", style="cyan")
        table.add_column("收盘价")
        table.add_column("涨跌幅")
        table.add_column("日期")

        for s in snapshots:
            change = s.get("change_pct")
            if change is not None:
                color = "green" if change >= 0 else "red"
                change_str = f"[{color}]{change:+.2f}%[/]"
            else:
                change_str = "-"
            table.add_row(s["name"], f"{s['close']:,.2f}", change_str, s["trade_date"])
        console.print(table)

    # 市场状态检测
    regime = detect_market_regime()
    if regime:
        regime_colors = {
            "bull_strong": "bold green",
            "bull_weak": "green",
            "bear_strong": "bold red",
            "bear_weak": "red",
            "ranging": "yellow",
        }
        color = regime_colors.get(regime["regime"], "white")
        console.print(f"\n[bold]市场状态:[/] [{color}]{regime['regime']}[/] — {regime['description']}")
        console.print(f"  趋势得分: {regime['trend_score']:.1f}  波动率: {regime['volatility']:.2%}")

    # 基金筛选评分
    scored_funds = screen_and_score_funds()
    if scored_funds:
        table = Table(title="基金评分排名 (Top 10)")
        table.add_column("排名", style="dim")
        table.add_column("代码", style="cyan")
        table.add_column("名称")
        table.add_column("综合评分")
        table.add_column("近1月")
        table.add_column("近3月")
        table.add_column("最大回撤")

        for i, f in enumerate(scored_funds[:10], 1):
            table.add_row(
                str(i),
                f["fund_code"],
                f.get("fund_name", "")[:12],
                f"[bold]{f['total_score']:.1f}[/]",
                f"{f.get('return_1m', 0):+.2f}%",
                f"{f.get('return_3m', 0):+.2f}%",
                f"{f.get('max_drawdown', 0):.2f}%",
            )
        console.print(table)


def cmd_recommend(args: list[str]):
    """生成交易建议（阶段4实现）"""
    from src.report.recommendation import generate_recommendation
    report_path = generate_recommendation()
    if report_path:
        console.print(f"\n[bold green]推荐报告已生成: {report_path}[/]")


def cmd_record_trade(args: list[str]):
    """记录已执行的交易"""
    from src.memory.database import execute_write

    console.print("\n[bold]记录交易[/]")
    fund_code = input("基金代码: ").strip()
    action = input("操作 (buy/sell): ").strip()
    amount = float(input("金额 (RMB): ").strip())
    nav = float(input("成交净值: ").strip())
    trade_date = input("交易日期 (YYYY-MM-DD, 回车=今天): ").strip()
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    reason = input("备注: ").strip()

    shares = amount / nav if nav > 0 else 0
    execute_write(
        """INSERT INTO trades (trade_date, fund_code, action, amount, nav, shares, reason, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'executed')""",
        (trade_date, fund_code, action, amount, nav, shares, reason),
    )

    # 更新持仓
    if action == "buy":
        execute_write(
            """INSERT INTO portfolio (fund_code, shares, cost_price, current_nav, buy_date, status)
               VALUES (?, ?, ?, ?, ?, 'holding')""",
            (fund_code, shares, nav, nav, trade_date),
        )
    console.print(f"[green]交易已记录: {action} {fund_code} {amount:.2f} RMB @ {nav:.4f}[/]")


def cmd_backtest(args: list[str]):
    """回测策略（阶段3实现）"""
    from src.strategy.portfolio import run_backtest
    run_backtest(args)


def cmd_context(args: list[str]):
    """查看系统上下文"""
    from src.memory.context import build_context, format_context_summary
    ctx = build_context()
    console.print(format_context_summary(ctx))


def cmd_stats(args: list[str]):
    """查看交易统计"""
    from src.memory.trade_journal import print_trade_journal
    print_trade_journal()


def cmd_schedule(args: list[str]):
    """启动定时调度器"""
    from src.scheduler.jobs import run_scheduler
    run_scheduler()


def cmd_hotspot(args: list[str]):
    """扫描市场热点"""
    from src.analysis.sector_rotation import print_hotspot_report
    print_hotspot_report()


def cmd_learn(args: list[str]):
    """查看学习进化报告"""
    from src.analysis.learner import print_learning_report
    print_learning_report()


def cmd_fund_flow(args: list[str]):
    """查看资金流向分析"""
    from src.analysis.fund_flow import print_fund_flow_report
    print_fund_flow_report()


def cmd_valuation(args: list[str]):
    """查看估值数据"""
    from src.data.valuation import get_valuation_snapshot, save_valuation_to_db
    from rich.table import Table

    console.print("\n[bold]═══ 指数估值分位 ═══[/]\n")
    snapshot = get_valuation_snapshot()

    if not snapshot:
        console.print("[yellow]估值数据获取失败[/]")
        return

    save_valuation_to_db(snapshot)

    table = Table(title="主要指数估值")
    table.add_column("指数", style="cyan")
    table.add_column("PE")
    table.add_column("PE分位")
    table.add_column("PB")
    table.add_column("PB分位")
    table.add_column("信号")

    for code, data in snapshot.items():
        pe_pct = data.get("pe_percentile", 0)
        signal = data.get("signal", "")

        signal_color = "green" if "低估" in signal else "red" if "高估" in signal else "yellow"

        table.add_row(
            data.get("name", code),
            f"{data.get('pe', 0):.1f}",
            f"{pe_pct:.0f}%",
            f"{data.get('pb', 0):.2f}",
            f"{data.get('pb_percentile', 0):.0f}%",
            f"[{signal_color}]{signal}[/]",
        )

    console.print(table)


def cmd_macro(args: list[str]):
    """查看宏观经济数据"""
    from src.data.macro import update_macro_data, get_macro_snapshot

    console.print("\n[bold]═══ 宏观经济指标 ═══[/]\n")

    if "--update" in args:
        update_macro_data()

    snapshot = get_macro_snapshot()

    console.print(f"  PMI: {snapshot.get('pmi', '?')}")
    console.print(f"  M2 同比: {snapshot.get('m2_yoy', '?')}%")
    console.print(f"  CPI 同比: {snapshot.get('cpi_yoy', '?')}%")
    console.print(f"  信贷周期: [bold]{snapshot.get('credit_cycle', '?')}[/]")
    console.print(f"  配置建议: {snapshot.get('cycle_signal', '?')}")
    console.print(f"\n  {snapshot.get('narrative', '')}")


def cmd_sentiment(args: list[str]):
    """查看市场情绪"""
    from src.data.sentiment import get_sentiment_snapshot

    console.print("\n[bold]═══ 市场情绪 ═══[/]\n")
    snapshot = get_sentiment_snapshot()

    level = snapshot.get("level", "neutral")
    level_color = "red" if "贪婪" in level else "green" if "恐惧" in level else "yellow"

    console.print(f"  情绪水平: [{level_color}]{level}[/]")
    console.print(f"  情绪得分: {snapshot.get('score', 50):.0f}/100")
    console.print(f"  融资分位: {snapshot.get('percentile', 50):.0f}%")
    console.print(f"  趋势: {snapshot.get('trend', '?')}")
    console.print(f"\n  {snapshot.get('narrative', '')}")


def cmd_managers(args: list[str]):
    """评估基金经理"""
    from src.data.fund_manager import screen_managers

    console.print("\n[bold]═══ 基金经理评估 ═══[/]\n")
    results = screen_managers(min_score=50)

    if not results:
        console.print("[yellow]无足够数据评估经理[/]")
        return

    table = Table(title=f"基金经理评估 ({len(results)} 只)")
    table.add_column("基金代码", style="cyan")
    table.add_column("经理")
    table.add_column("评分")
    table.add_column("等级")
    table.add_column("年化收益")
    table.add_column("最大回撤")

    for r in results[:15]:
        grade_color = {"A": "green", "B": "yellow", "C": "white", "D": "red"}.get(r["grade"], "white")
        table.add_row(
            r.get("fund_code", ""),
            r.get("manager_name", "")[:8],
            f"{r['score']}",
            f"[{grade_color}]{r['grade']}[/]",
            f"{r.get('annualized_return', 0):+.1f}%",
            f"{r.get('max_drawdown', 0):.1f}%",
        )
    console.print(table)


def cmd_allocation(args: list[str]):
    """查看资产配置"""
    from src.risk.asset_allocation import check_allocation_compliance

    console.print("\n[bold]═══ 资产配置检查 ═══[/]\n")

    # 获取估值分位
    pe_pct = 50
    try:
        from src.data.valuation import get_valuation_signal
        v = get_valuation_signal()
        pe_pct = v.get("pe_percentile", 50)
    except Exception:
        pass

    # 获取市场状态
    regime = "ranging"
    try:
        from src.analysis.market_regime import detect_market_regime
        rd = detect_market_regime()
        regime = rd["regime"] if rd else "ranging"
    except Exception:
        pass

    result = check_allocation_compliance(regime, pe_pct)

    console.print(f"  市场状态: {regime} | PE分位: {pe_pct:.0f}%")
    console.print(f"  合规: {'[green]是[/]' if result['compliant'] else '[red]否[/]'}")

    table = Table(title="配置对比")
    table.add_column("资产类别")
    table.add_column("目标")
    table.add_column("当前")
    table.add_column("偏差")

    for asset in ["equity", "bond", "cash"]:
        name = {"equity": "股票基金", "bond": "债券基金", "cash": "现金"}.get(asset, asset)
        target = result["target"][asset]
        current = result["current"][asset]
        dev = result["deviations"][asset]
        dev_color = "red" if abs(dev) > 0.10 else "yellow" if abs(dev) > 0.05 else "green"
        table.add_row(name, f"{target:.0%}", f"{current:.0%}", f"[{dev_color}]{dev:+.0%}[/]")

    console.print(table)

    for v in result.get("violations", []):
        console.print(f"  [red]违规: {v}[/]")
    for s in result.get("suggestions", []):
        console.print(f"  [yellow]建议: {s}[/]")


def cmd_scenario(args: list[str]):
    """LLM 场景推演"""
    from src.agent.scenario import run_scenario_analysis, format_scenario_for_report

    console.print("\n[bold]═══ 场景推演 ═══[/]\n")

    # 构建市场上下文
    context_parts = []
    try:
        from src.data.valuation import get_valuation_signal
        v = get_valuation_signal()
        context_parts.append(f"估值: {v.get('narrative', '')}")
    except Exception:
        pass

    try:
        from src.data.macro import get_macro_snapshot
        m = get_macro_snapshot()
        context_parts.append(f"宏观: {m.get('narrative', '')}")
    except Exception:
        pass

    try:
        from src.data.sentiment import get_sentiment_snapshot
        s = get_sentiment_snapshot()
        context_parts.append(f"情绪: {s.get('narrative', '')}")
    except Exception:
        pass

    try:
        from src.analysis.market_regime import detect_market_regime
        r = detect_market_regime()
        if r:
            context_parts.append(f"市场状态: {r['regime']} — {r.get('description', '')}")
    except Exception:
        pass

    context = "\n".join(context_parts) if context_parts else "市场数据收集中..."

    result = run_scenario_analysis(context)
    if result:
        report = format_scenario_for_report(result)
        console.print(report)


def cmd_intel(args: list[str]):
    """Market Intelligence 市场情报"""
    from src.agent.market_intel import run_market_intel, format_intel_for_report

    console.print("\n[bold]═══ Market Intelligence 市场情报 ═══[/]\n")
    result = run_market_intel()
    if result:
        report = format_intel_for_report(result)
        console.print(report)
    else:
        console.print("[yellow]MI 分析未能完成，请检查 LLM 配置和数据源[/]")


def cmd_debate(args: list[str]):
    """LLM 多角色辩论"""
    from src.agent.debate import run_debate, format_debate_for_report

    console.print("\n[bold]═══ 多角色辩论 ═══[/]\n")

    # 构建市场上下文 (同 cmd_scenario)
    context_parts = []
    try:
        from src.data.valuation import get_valuation_signal
        v = get_valuation_signal()
        context_parts.append(f"估值: {v.get('narrative', '')}")
    except Exception:
        pass
    try:
        from src.data.macro import get_macro_snapshot
        m = get_macro_snapshot()
        context_parts.append(f"宏观: {m.get('narrative', '')}")
    except Exception:
        pass
    try:
        from src.data.sentiment import get_sentiment_snapshot
        s = get_sentiment_snapshot()
        context_parts.append(f"情绪: {s.get('narrative', '')}")
    except Exception:
        pass
    try:
        from src.analysis.market_regime import detect_market_regime
        r = detect_market_regime()
        if r:
            context_parts.append(f"市场状态: {r['regime']} — {r.get('description', '')}")
    except Exception:
        pass

    context = "\n".join(context_parts) if context_parts else "市场数据收集中..."
    result = run_debate(context)
    if result:
        report = format_debate_for_report(result)
        console.print(report)


def cmd_walk_forward(args: list[str]):
    """走前验证回测"""
    from src.strategy.portfolio import build_fund_data
    from src.strategy.walk_forward import run_walk_forward, print_walk_forward_report

    console.print("\n[bold]运行走前验证...[/]")
    fund_data = build_fund_data()
    if not fund_data:
        console.print("[yellow]无基金数据[/]")
        return

    result = run_walk_forward(fund_data)
    print_walk_forward_report(result)


def cmd_monte_carlo(args: list[str]):
    """蒙特卡洛模拟"""
    from src.strategy.portfolio import build_fund_data
    from src.strategy.monte_carlo import run_monte_carlo_from_backtest, print_monte_carlo_report

    console.print("\n[bold]运行蒙特卡洛模拟...[/]")
    fund_data = build_fund_data()
    if not fund_data:
        console.print("[yellow]无基金数据[/]")
        return

    result = run_monte_carlo_from_backtest(fund_data)
    if result:
        print_monte_carlo_report(result)


def cmd_reflect(args: list[str]):
    """手动触发反思复盘"""
    console.print("\n[bold]═══ 反思复盘 ═══[/]\n")
    try:
        from src.agent.reflection import run_reflection_cycle, print_reflection_report
        run_reflection_cycle()
        print_reflection_report()
    except Exception as e:
        console.print(f"[red]反思失败: {e}[/]")


def cmd_knowledge(args: list[str]):
    """查看知识库"""
    from src.agent.reflection import print_knowledge_report
    print_knowledge_report()


def cmd_discover(args: list[str]):
    """基金发现 — 从全市场 + 热点板块筛选最优基金, 或按主题关键词搜索"""

    # 检查 --theme 参数
    if "--theme" in args:
        theme_idx = args.index("--theme")
        keywords = args[theme_idx + 1:]
        if not keywords:
            console.print("[red]请指定搜索关键词, 如: uv run pixiu discover --theme 养老[/]")
            return

        from src.data.fund_discovery import discover_by_theme

        console.print(f"\n[bold]═══ 主题搜索: {' '.join(keywords)} ═══[/]\n")
        results = discover_by_theme(keywords)
        if not results:
            console.print("[yellow]未找到匹配的基金[/]")
            return

        table = Table(title=f"搜索结果: {' '.join(keywords)}")
        table.add_column("代码", style="cyan")
        table.add_column("名称")
        table.add_column("近3月")
        table.add_column("近1年")
        table.add_column("评分")

        for r in results:
            ret_3m = r.get("return_3m")
            ret_1y = r.get("return_1y")
            score = r.get("composite_score", 0)
            table.add_row(
                r["fund_code"],
                r["fund_name"][:20],
                f"{ret_3m:+.1f}%" if ret_3m is not None else "-",
                f"{ret_1y:+.1f}%" if ret_1y is not None else "-",
                f"{score:.1f}",
            )
        console.print(table)
        return

    from src.data.fund_discovery import update_dynamic_pool, print_discovery_report

    console.print("\n[bold]═══ 基金发现 ═══[/]\n")
    candidates = update_dynamic_pool()
    print_discovery_report(candidates)


def cmd_daily(args: list[str]):
    """日常例行流程: 学习 → 反思 → 更新增强数据 → 分析 → 热点 → 发现 → LLM决策 → 快照"""
    from src.report.portfolio_report import generate_portfolio_report

    console.print("\n[bold]═══ 貔貅日常分析流程 (全量智能体) ═══[/]\n")

    # 步骤 1: 学习进化
    console.print("[bold]步骤 1/11: 学习进化[/]")
    try:
        from src.analysis.learner import run_learning_cycle
        run_learning_cycle()
    except Exception as e:
        console.print(f"  [dim]学习: {e}[/]")

    # 步骤 2: LLM 反思复盘
    console.print("\n[bold]步骤 2/11: LLM 反思复盘[/]")
    try:
        from src.agent.reflection import run_reflection_cycle
        run_reflection_cycle()
    except Exception as e:
        console.print(f"  [dim]反思: {e}[/]")

    # 步骤 2b: 种子基金池导入
    try:
        from src.data.fund_discovery import seed_fund_universe
        seed_fund_universe()
    except Exception as e:
        console.print(f"  [dim]种子池: {e}[/]")

    # 步骤 3: 更新市场数据
    console.print("\n[bold]步骤 3/11: 更新市场数据[/]")
    cmd_update(args)

    # 步骤 4: 更新增强数据 (估值/宏观/情绪)
    console.print("\n[bold]步骤 4/11: 增强数据采集[/]")
    try:
        from src.data.valuation import get_valuation_snapshot, save_valuation_to_db
        v_snapshot = get_valuation_snapshot()
        if v_snapshot:
            save_valuation_to_db(v_snapshot)
            csi300 = v_snapshot.get("000300", {})
            console.print(f"  [dim]估值: 沪深300 PE分位 {csi300.get('pe_percentile', '?')}%[/]")
    except Exception as e:
        console.print(f"  [dim]估值数据: {e}[/]")

    try:
        from src.data.macro import update_macro_data, get_macro_snapshot
        update_macro_data()
        macro = get_macro_snapshot()
        console.print(f"  [dim]宏观: {macro.get('credit_cycle', '?')} — {macro.get('cycle_signal', '?')}[/]")
    except Exception as e:
        console.print(f"  [dim]宏观数据: {e}[/]")

    try:
        from src.data.sentiment import get_sentiment_snapshot
        sentiment = get_sentiment_snapshot()
        console.print(f"  [dim]情绪: {sentiment.get('level', '?')} (分位 {sentiment.get('percentile', '?')}%)[/]")
    except Exception as e:
        console.print(f"  [dim]情绪数据: {e}[/]")

    # 步骤 5: 市场分析
    console.print("\n[bold]步骤 5/11: 市场分析[/]")
    cmd_analyze([])

    # 步骤 6: 热点扫描
    console.print("\n[bold]步骤 6/11: 热点扫描[/]")
    hotspots = []
    try:
        from src.analysis.sector_rotation import print_hotspot_report
        hotspots = print_hotspot_report() or []
    except Exception as e:
        console.print(f"  [yellow]热点扫描: {e}[/]")

    # 步骤 7: 基金发现
    console.print("\n[bold]步骤 7/11: 基金发现[/]")
    try:
        from src.data.fund_discovery import update_dynamic_pool, print_discovery_report
        candidates = update_dynamic_pool(hotspots=hotspots)
        if candidates:
            print_discovery_report(candidates)
            from src.data.fund_data import batch_update_funds
            new_codes = [c["fund_code"] for c in candidates[:10]]
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            console.print(f"  [dim]下载新发现基金的净值数据 ({len(new_codes)} 只)...[/]")
            batch_update_funds(new_codes, start_date=start_date)
    except Exception as e:
        console.print(f"  [yellow]基金发现: {e}[/]")

    # 步骤 8: 资产配置检查
    console.print("\n[bold]步骤 8/11: 资产配置检查[/]")
    try:
        from src.risk.asset_allocation import check_allocation_compliance
        pe_pct = 50
        try:
            from src.data.valuation import get_valuation_signal
            pe_pct = get_valuation_signal().get("pe_percentile", 50)
        except Exception:
            pass
        compliance = check_allocation_compliance("ranging", pe_pct)
        if not compliance["compliant"]:
            for v in compliance["violations"]:
                console.print(f"  [red]配置违规: {v}[/]")
        else:
            console.print("  [dim]资产配置合规 ✓[/]")
    except Exception as e:
        console.print(f"  [dim]配置检查: {e}[/]")

    # 步骤 9: Market Intelligence
    console.print("\n[bold]步骤 9/11: Market Intelligence[/]")
    try:
        from src.agent.market_intel import run_market_intel
        mi_result = run_market_intel()
        if mi_result:
            console.print(f"  [dim]MI 判断: {mi_result.get('market_regime_view', '?')}[/]")
        else:
            console.print("  [dim]MI 未能生成结果[/]")
    except Exception as e:
        console.print(f"  [dim]MI: {e}[/]")

    # 步骤 10: 生成建议 (含 LLM 智能分析)
    console.print("\n[bold]步骤 10/11: 生成建议 (全量智能体)[/]")
    cmd_recommend([])

    # 记录信号供学习系统验证
    try:
        from src.analysis.learner import record_signals_from_composite
        from src.strategy.portfolio import generate_composite_signals
        from src.analysis.market_regime import detect_market_regime
        regime_data = detect_market_regime()
        regime = regime_data["regime"] if regime_data else "ranging"
        signals = generate_composite_signals()
        if signals:
            record_signals_from_composite(signals, regime)
            console.print(f"  [dim]记录了 {len(signals)} 个信号待验证[/]")
    except Exception as e:
        console.print(f"  [dim]信号记录: {e}[/]")

    # 步骤 11: 组合快照
    console.print("\n[bold]步骤 11/11: 组合快照[/]")
    generate_portfolio_report()
    console.print("\n[bold green]═══ 日常分析完成 ═══[/]")


def cmd_llm(args: list[str]):
    """切换或查看 LLM 后端"""
    from src.agent.llm import load_env, get_provider, get_analysis_model, get_decision_model, get_critical_model
    import os
    from pathlib import Path
    from src.config import CONFIG

    load_env()

    if args and args[0] in ("gemini", "anthropic"):
        new_provider = args[0]
        env_path = Path(CONFIG["project_root"]) / ".env"
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
            new_lines = []
            found = False
            for line in lines:
                if line.strip().startswith("LLM_PROVIDER="):
                    new_lines.append(f"LLM_PROVIDER={new_provider}")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"LLM_PROVIDER={new_provider}")
            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            os.environ["LLM_PROVIDER"] = new_provider
            console.print(f"  [green]已切换到 {new_provider}[/]")
        else:
            console.print("[red].env 文件不存在[/]")
            return

    provider = get_provider()
    console.print(f"\n[bold]═══ LLM 配置 ═══[/]\n")
    console.print(f"  当前后端: [cyan]{provider}[/]")
    console.print(f"  分析模型: {get_analysis_model()}  [dim](市场摘要)[/]")
    console.print(f"  决策模型: {get_decision_model()}  [dim](反思/情景)[/]")
    console.print(f"  关键模型: [bold]{get_critical_model()}[/]  [dim](核心决策/辩论裁判)[/]")
    console.print(f"\n  切换: [dim]uv run pixiu llm gemini[/] 或 [dim]uv run pixiu llm anthropic[/]")

    # 基金池分类统计
    from src.memory.database import execute_query as _eq
    watchlist = _eq("SELECT category FROM watchlist")
    if watchlist:
        CATEGORY_NAMES = {"equity": "偏股", "bond": "债券", "index": "指数", "gold": "黄金", "qdii": "QDII"}
        cat_counts: dict[str, int] = {}
        for w in watchlist:
            cat = w.get("category") or "equity"
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        stats = " | ".join(f"{CATEGORY_NAMES.get(k, k)} {v}" for k, v in sorted(cat_counts.items()))
        console.print(f"\n  [bold]基金池:[/] {stats} | 合计 {len(watchlist)}")


COMMANDS = {
    "update": ("更新市场数据", cmd_update),
    "fund": ("查看单只基金详情", cmd_fund),
    "portfolio": ("查看当前组合状态", cmd_portfolio),
    "history": ("查看交易历史", cmd_history),
    "watchlist": ("管理观察池", cmd_watchlist),
    "analyze": ("执行市场分析", cmd_analyze),
    "recommend": ("生成交易建议", cmd_recommend),
    "record-trade": ("记录已执行的交易", cmd_record_trade),
    "backtest": ("回测策略", cmd_backtest),
    "daily": ("日常例行流程", cmd_daily),
    "discover": ("基金发现 (热点+全市场+主题搜索)", cmd_discover),
    "fund-flow": ("资金流向分析", cmd_fund_flow),
    "hotspot": ("扫描市场热点", cmd_hotspot),
    "learn": ("查看学习进化报告", cmd_learn),
    "context": ("查看系统上下文", cmd_context),
    "stats": ("查看交易统计", cmd_stats),
    "schedule": ("启动定时调度器", cmd_schedule),
    "reflect": ("反思复盘 (LLM)", cmd_reflect),
    "knowledge": ("查看知识库", cmd_knowledge),
    "valuation": ("查看估值分位", cmd_valuation),
    "macro": ("宏观经济指标", cmd_macro),
    "sentiment": ("市场情绪", cmd_sentiment),
    "managers": ("基金经理评估", cmd_managers),
    "allocation": ("资产配置检查", cmd_allocation),
    "scenario": ("LLM 场景推演", cmd_scenario),
    "intel": ("Market Intelligence 市场情报", cmd_intel),
    "debate": ("LLM 多角色辩论", cmd_debate),
    "walk-forward": ("走前验证回测", cmd_walk_forward),
    "monte-carlo": ("蒙特卡洛模拟", cmd_monte_carlo),
    "llm": ("查看/切换 LLM 后端", cmd_llm),
}


def main():
    init_db()

    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        console.print("\n[bold]貔貅 (Pixiu) — 智能基金交易分析系统[/]\n")
        table = Table()
        table.add_column("命令", style="cyan")
        table.add_column("说明")
        for cmd, (desc, _) in COMMANDS.items():
            table.add_row(cmd, desc)
        console.print(table)
        console.print("\n用法: uv run pixiu <命令> [参数]")
        return

    cmd_name = args[0]
    cmd_args = args[1:]

    if cmd_name not in COMMANDS:
        console.print(f"[red]未知命令: {cmd_name}[/]")
        console.print("运行 'uv run src/main.py help' 查看可用命令")
        return

    _, cmd_func = COMMANDS[cmd_name]
    cmd_func(cmd_args)


if __name__ == "__main__":
    main()
