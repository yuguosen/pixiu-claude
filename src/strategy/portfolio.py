"""组合构建与管理"""

import pandas as pd
from rich.console import Console
from rich.table import Table

from src.analysis.market_regime import detect_market_regime, get_regime_allocation
from src.config import CONFIG
from src.memory.database import classify_fund, execute_query, get_fund_nav_history
from src.strategy.base import Signal, SignalType
from src.strategy.registry import discover_strategies, get_registered_strategies

console = Console()


def build_fund_data(include_discovered: bool = True) -> dict:
    """从数据库构建基金数据字典

    Args:
        include_discovered: 是否包含动态发现的基金 (观察池)
    """
    # 基础: 已有足够数据的基金
    funds = execute_query(
        """SELECT DISTINCT fund_code FROM fund_nav
           GROUP BY fund_code HAVING COUNT(*) >= 60"""
    )
    fund_data = {}
    for f in funds:
        code = f["fund_code"]
        nav_history = get_fund_nav_history(code)
        if nav_history:
            fund_data[code] = {"nav_history": nav_history}

    # 补充: 观察池中有数据但尚未达到 60 条的基金 (至少 30 条)
    if include_discovered:
        watchlist = execute_query("SELECT fund_code FROM watchlist")
        for w in watchlist:
            code = w["fund_code"]
            if code not in fund_data:
                nav_history = get_fund_nav_history(code)
                if nav_history and len(nav_history) >= 30:
                    fund_data[code] = {"nav_history": nav_history}

    return fund_data


def generate_composite_signals() -> list[Signal]:
    """生成综合加权信号

    根据市场状态动态分配各策略权重，汇总信号。
    如果有学习数据，使用学习后的权重替代默认值。
    """
    # 检测市场状态 (分别检测各个资产类别)
    category_regimes = {}
    for cat in ["equity", "bond", "gold", "qdii", "index"]:
        r_data = detect_market_regime(category=cat)
        category_regimes[cat] = r_data["regime"] if r_data else "ranging"

    global_regime = category_regimes.get("equity", "ranging")
    allocation = get_regime_allocation(global_regime)
    strategy_weights = allocation["strategy_weights"]

    # 尝试使用学习后的权重
    try:
        from src.analysis.learner import get_learned_weights
        learned = get_learned_weights(global_regime)
        if learned:
            console.print(f"  [dim]使用学习权重: {learned}[/]")
            strategy_weights = learned
    except Exception:
        pass  # 学习系统未初始化时降级为默认权重

    # 构建数据
    fund_data = build_fund_data()
    if not fund_data:
        console.print("[yellow]无基金数据可分析[/]")
        return []

    market_data = {
        "regime": global_regime,
        "category_regimes": category_regimes
    }

    # 获取增强数据源 (渐进降级, 并行)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    data_quality = {}

    def _fetch_valuation():
        from src.data.valuation import get_valuation_signal_safe
        return get_valuation_signal_safe()

    def _fetch_macro():
        from src.data.macro import get_macro_snapshot_safe
        return get_macro_snapshot_safe()

    def _fetch_managers():
        from src.data.fund_manager import evaluate_fund_manager
        scores = {}
        for code in list(fund_data.keys())[:10]:
            try:
                score = evaluate_fund_manager(code)
                scores[code] = score
            except Exception:
                pass
        return scores

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="enrich") as pool:
        futures = {
            pool.submit(_fetch_valuation): "valuation",
            pool.submit(_fetch_macro): "macro",
            pool.submit(_fetch_managers): "managers",
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                result = future.result(timeout=60)
                if key == "valuation":
                    market_data["valuation_signal"] = result.data
                    data_quality["valuation"] = result.quality.name
                    console.print(
                        f"  [dim]估值: PE分位 {result.data.get('pe_percentile', '?')}% "
                        f"({result.source})[/]"
                    )
                elif key == "macro":
                    market_data["macro_snapshot"] = result.data
                    data_quality["macro"] = result.quality.name
                    console.print(
                        f"  [dim]宏观: {result.data.get('credit_cycle', '?')} "
                        f"({result.source})[/]"
                    )
                elif key == "managers":
                    if result:
                        market_data["manager_scores"] = result
                        console.print(f"  [dim]经理评估: {len(result)} 只基金[/]")
            except Exception as e:
                console.print(f"  [dim]{key}: {e}[/]")

    market_data["data_quality"] = data_quality

    # 各策略生成信号 (注册表驱动, 并行执行)
    discover_strategies()
    registered = get_registered_strategies()
    strategies = []
    for name, (cls, default_weight) in registered.items():
        weight = strategy_weights.get(name, default_weight)
        strategies.append((cls(), weight))

    def _run_strategy(strategy, weight):
        try:
            return strategy.generate_signals(market_data, fund_data), weight
        except Exception as e:
            console.print(f"  [yellow]策略 {strategy.name} 出错: {e}[/]")
            return [], weight

    # 汇总信号 (按基金代码分组)
    fund_signals: dict[str, list[tuple[Signal, float]]] = {}
    with ThreadPoolExecutor(max_workers=len(strategies), thread_name_prefix="strat") as pool:
        strat_futures = {
            pool.submit(_run_strategy, s, w): s.name for s, w in strategies
        }
        for future in as_completed(strat_futures):
            signals, weight = future.result(timeout=30)
            for sig in signals:
                fund_signals.setdefault(sig.fund_code, []).append((sig, weight))

    # 合并信号 (含冲突检测)
    composite = []
    for fund_code, weighted_signals in fund_signals.items():
        buy_score = 0
        sell_score = 0
        buy_strategies = []
        sell_strategies = []
        reasons = []

        for sig, weight in weighted_signals:
            if sig.is_buy:
                buy_score += sig.confidence * weight
                buy_strategies.append(sig.strategy_name)
                reasons.append(f"[{sig.strategy_name}] {sig.reason}")
            elif sig.is_sell:
                sell_score += sig.confidence * weight
                sell_strategies.append(sig.strategy_name)
                reasons.append(f"[{sig.strategy_name}] {sig.reason}")

        net = buy_score - sell_score
        total = buy_score + sell_score
        if total < 0.1:
            continue

        confidence = abs(net) / max(total, 0.01)

        # ── 冲突检测: 当策略方向矛盾时降低置信度 ──
        has_conflict = bool(buy_strategies) and bool(sell_strategies)
        if has_conflict:
            # 冲突惩罚: 按矛盾策略的数量和强度
            conflict_ratio = min(buy_score, sell_score) / max(total, 0.01)
            confidence *= (1 - conflict_ratio * 0.5)  # 最多降低50%
            reasons.append(f"[conflict] 策略冲突 (买:{','.join(buy_strategies)} vs 卖:{','.join(sell_strategies)})")

        if net > 0.2:
            signal_type = SignalType.STRONG_BUY if net > 0.5 else SignalType.BUY
        elif net < -0.2:
            signal_type = SignalType.STRONG_SELL if net < -0.5 else SignalType.SELL
        else:
            signal_type = SignalType.HOLD

        if signal_type != SignalType.HOLD:
            composite.append(Signal(
                fund_code=fund_code,
                signal_type=signal_type,
                confidence=round(min(confidence, 0.95), 2),
                reason="\n".join(reasons),
                strategy_name="composite",
                priority=abs(int(net * 100)),
                metadata={
                    "buy_score": round(buy_score, 3),
                    "sell_score": round(sell_score, 3),
                    "regime": category_regimes.get(classify_fund(fund_code), global_regime),
                    "has_conflict": has_conflict,
                    "category": classify_fund(fund_code),
                },
            ))

    composite.sort(key=lambda s: s.priority, reverse=True)

    # 信号守卫: 检测并降级反复出错的信号
    try:
        from src.analysis.signal_guard import apply_signal_guard
        composite = apply_signal_guard(composite)
    except Exception as e:
        console.print(f"  [dim]信号守卫: {e}[/]")

    return composite


def run_backtest(args: list[str]):
    """运行回测"""
    console.print("\n[bold]运行趋势跟踪策略回测...[/]")

    fund_data = build_fund_data()
    if not fund_data:
        console.print("[yellow]无基金数据可回测[/]")
        return

    discover_strategies()
    registered = get_registered_strategies()
    trend_cls = registered.get("trend_following", (None, 0))[0]
    if trend_cls is None:
        from src.strategy.trend_following import TrendFollowingStrategy
        trend_cls = TrendFollowingStrategy
    strategy = trend_cls()
    result = strategy.backtest(fund_data)

    table = Table(title=f"回测结果 — {result.strategy_name}")
    table.add_column("指标", style="cyan")
    table.add_column("数值", style="green")

    color = "green" if result.total_return > 0 else "red"
    table.add_row("总收益率", f"[{color}]{result.total_return:+.2f}%[/]")
    table.add_row("最大回撤", f"[red]{result.max_drawdown:.2f}%[/]")
    table.add_row("交易次数", str(result.total_trades))
    table.add_row("盈利次数", str(result.profit_trades))
    table.add_row("胜率", f"{result.win_rate:.1f}%")

    console.print(table)

    if result.details:
        console.print("\n[bold]交易明细:[/]")
        detail_table = Table()
        detail_table.add_column("日期")
        detail_table.add_column("操作")
        detail_table.add_column("净值")
        detail_table.add_column("盈亏")

        for d in result.details[-20:]:
            action_color = "green" if d["action"] == "buy" else "red"
            pnl = d.get("pnl")
            pnl_str = f"{pnl:+.2f}%" if pnl is not None else "-"
            detail_table.add_row(
                d["date"],
                f"[{action_color}]{d['action']}[/]",
                f"{d['nav']:.4f}",
                pnl_str,
            )
        console.print(detail_table)
