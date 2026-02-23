"""自动学习引擎 — 从历史信号验证中进化

核心能力:
1. 记录每个信号的预测
2. 定期回头验证信号的准确性
3. 按 策略×市场状态 统计真实胜率
4. 根据历史表现动态调整策略权重
5. 校准置信度 (高置信度是否真的更准?)
"""

import json
from datetime import datetime, timedelta

import pandas as pd
from rich.console import Console
from rich.table import Table

from src.memory.database import execute_query, execute_write, execute_many, get_fund_nav_history

console = Console()


# ── 信号记录 ──────────────────────────────────────────────


def record_signal(
    signal_date: str,
    fund_code: str,
    strategy_name: str,
    signal_type: str,
    confidence: float,
    regime: str,
    nav_at_signal: float,
):
    """记录一个待验证的信号"""
    execute_write(
        """INSERT INTO signal_validation
           (signal_date, fund_code, strategy_name, signal_type,
            confidence, regime, nav_at_signal)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (signal_date, fund_code, strategy_name, signal_type,
         confidence, regime, nav_at_signal),
    )


def record_signals_from_composite(signals: list, regime: str):
    """从综合信号列表中批量记录待验证信号"""
    today = datetime.now().strftime("%Y-%m-%d")

    for sig in signals:
        # 获取当前净值
        nav_history = get_fund_nav_history(sig.fund_code)
        nav = nav_history[-1]["nav"] if nav_history else 0

        # 记录综合信号
        record_signal(
            today, sig.fund_code, "composite",
            sig.signal_type.value, sig.confidence, regime, nav,
        )

        # 也记录各子策略的信号 (从 metadata 中提取)
        if hasattr(sig, "reason") and sig.reason:
            for line in sig.reason.split("\n"):
                if line.startswith("[") and "]" in line:
                    strat_name = line[1:line.index("]")]
                    record_signal(
                        today, sig.fund_code, strat_name,
                        sig.signal_type.value, sig.confidence, regime, nav,
                    )


# ── 信号验证 ──────────────────────────────────────────────


def validate_pending_signals():
    """验证所有到期未验证的信号

    对 7 天前和 30 天前的信号，回查实际净值，判断方向是否正确。
    """
    today = datetime.now()
    cutoff_7d = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    cutoff_30d = (today - timedelta(days=30)).strftime("%Y-%m-%d")

    # 找到需要验证 7d 的信号
    pending_7d = execute_query(
        """SELECT id, fund_code, signal_type, nav_at_signal, signal_date
           FROM signal_validation
           WHERE nav_after_7d IS NULL AND signal_date <= ?""",
        (cutoff_7d,),
    )

    # 找到需要验证 30d 的信号
    pending_30d = execute_query(
        """SELECT id, fund_code, signal_type, nav_at_signal, signal_date
           FROM signal_validation
           WHERE nav_after_30d IS NULL AND signal_date <= ?""",
        (cutoff_30d,),
    )

    validated_count = 0

    for sig in pending_7d:
        nav_now = _get_nav_after(sig["fund_code"], sig["signal_date"], 7)
        if nav_now is None:
            continue

        nav_at = sig["nav_at_signal"]
        if not nav_at or nav_at <= 0:
            continue

        return_7d = (nav_now - nav_at) / nav_at * 100
        is_correct = _check_direction(sig["signal_type"], return_7d, days=7)

        execute_write(
            """UPDATE signal_validation
               SET nav_after_7d = ?, return_7d = ?, is_correct_7d = ?, validated_at = ?
               WHERE id = ?""",
            (nav_now, round(return_7d, 4), is_correct, today.isoformat(), sig["id"]),
        )
        validated_count += 1

    for sig in pending_30d:
        nav_now = _get_nav_after(sig["fund_code"], sig["signal_date"], 30)
        if nav_now is None:
            continue

        nav_at = sig["nav_at_signal"]
        if not nav_at or nav_at <= 0:
            continue

        return_30d = (nav_now - nav_at) / nav_at * 100
        is_correct = _check_direction(sig["signal_type"], return_30d, days=30)

        execute_write(
            """UPDATE signal_validation
               SET nav_after_30d = ?, return_30d = ?, is_correct_30d = ?, validated_at = ?
               WHERE id = ?""",
            (nav_now, round(return_30d, 4), is_correct, today.isoformat(), sig["id"]),
        )
        validated_count += 1

    if validated_count > 0:
        console.print(f"  [green]验证了 {validated_count} 个历史信号[/]")

    return validated_count


def _get_nav_after(fund_code: str, signal_date: str, days: int) -> float | None:
    """获取信号后 N 天的净值"""
    target_date = (
        datetime.strptime(signal_date, "%Y-%m-%d") + timedelta(days=days)
    ).strftime("%Y-%m-%d")

    # 找最接近目标日期的净值
    rows = execute_query(
        """SELECT nav FROM fund_nav
           WHERE fund_code = ? AND nav_date >= ? AND nav_date <= ?
           ORDER BY nav_date DESC LIMIT 1""",
        (fund_code, signal_date, target_date),
    )
    # 如果没找到，取最新的
    if not rows:
        rows = execute_query(
            """SELECT nav FROM fund_nav
               WHERE fund_code = ? AND nav_date > ?
               ORDER BY nav_date DESC LIMIT 1""",
            (fund_code, signal_date),
        )
    return rows[0]["nav"] if rows else None


def _check_direction(signal_type: str, actual_return: float, days: int = 30) -> int:
    """检查信号方向是否正确

    买入信号 + 实际上涨 = 正确
    卖出信号 + 实际下跌 = 正确
    """
    is_buy = signal_type in ("strong_buy", "buy")
    is_sell = signal_type in ("strong_sell", "sell")

    hurdle = 1.65 if days == 7 else 0.0

    if is_buy and actual_return > hurdle:
        return 1
    elif is_sell and actual_return < 0:
        return 1
    elif is_buy and actual_return < hurdle:
        return 0
    elif is_sell and actual_return > 0:
        return 0
    return 0  # 持平算错


# ── 策略表现统计 ──────────────────────────────────────────


def update_strategy_performance():
    """根据已验证的信号更新各策略表现统计

    按 策略 × 市场状态 聚合最近 90 天的信号验证结果。
    """
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    # 聚合查询
    stats = execute_query(
        """SELECT strategy_name, regime,
                  COUNT(*) as total,
                  SUM(CASE WHEN is_correct_30d = 1 THEN 1 ELSE 0 END) as correct,
                  AVG(return_30d) as avg_return,
                  AVG(confidence) as avg_confidence
           FROM signal_validation
           WHERE signal_date >= ? AND is_correct_30d IS NOT NULL
           GROUP BY strategy_name, regime""",
        (cutoff,),
    )

    if not stats:
        return

    for s in stats:
        total = s["total"]
        correct = s["correct"] or 0
        win_rate = correct / total if total > 0 else 0

        # 计算置信度校准 (高置信度信号的胜率 vs 低置信度)
        high_conf = execute_query(
            """SELECT AVG(CASE WHEN is_correct_30d = 1 THEN 1.0 ELSE 0.0 END) as rate
               FROM signal_validation
               WHERE strategy_name = ? AND regime = ?
                 AND confidence >= 0.6 AND signal_date >= ?
                 AND is_correct_30d IS NOT NULL""",
            (s["strategy_name"], s["regime"], cutoff),
        )
        low_conf = execute_query(
            """SELECT AVG(CASE WHEN is_correct_30d = 1 THEN 1.0 ELSE 0.0 END) as rate
               FROM signal_validation
               WHERE strategy_name = ? AND regime = ?
                 AND confidence < 0.6 AND signal_date >= ?
                 AND is_correct_30d IS NOT NULL""",
            (s["strategy_name"], s["regime"], cutoff),
        )

        high_rate = high_conf[0]["rate"] if high_conf and high_conf[0]["rate"] else 0
        low_rate = low_conf[0]["rate"] if low_conf and low_conf[0]["rate"] else 0
        confidence_accuracy = high_rate - low_rate  # 正值 = 置信度有区分力

        # 计算建议权重: 胜率越高权重越大, 但至少保留 0.1
        recommended_weight = max(0.1, min(1.0, win_rate * 1.5))
        # 收益为负的策略降权
        avg_return = s["avg_return"] or 0
        if avg_return < -2:
            recommended_weight *= 0.5

        execute_write(
            """INSERT OR REPLACE INTO strategy_performance
               (period_start, period_end, strategy_name, regime,
                total_signals, correct_signals, win_rate, avg_return,
                avg_confidence, confidence_accuracy, recommended_weight, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (
                cutoff, today, s["strategy_name"], s["regime"],
                total, correct, round(win_rate, 4), round(avg_return, 4),
                round(s["avg_confidence"] or 0, 4),
                round(confidence_accuracy, 4),
                round(recommended_weight, 4),
            ),
        )

    console.print(f"  [green]更新了 {len(stats)} 条策略表现记录[/]")


# ── 动态权重获取 ──────────────────────────────────────────


def get_learned_weights(regime: str) -> dict[str, float] | None:
    """获取基于学习的策略权重

    如果有足够的历史数据，返回根据表现调整后的权重。
    否则返回 None (使用默认权重)。

    Args:
        regime: 当前市场状态

    Returns:
        {"trend_following": 0.4, "mean_reversion": 0.3, "momentum": 0.3} 或 None
    """
    rows = execute_query(
        """SELECT strategy_name, recommended_weight, total_signals, win_rate
           FROM strategy_performance
           WHERE regime = ? AND total_signals >= 5
           ORDER BY updated_at DESC""",
        (regime,),
    )

    if not rows:
        return None

    # 从注册表获取策略名称
    from src.strategy.registry import discover_strategies, get_strategy_names
    discover_strategies()
    strategy_names = set(get_strategy_names())
    weights = {}
    for r in rows:
        name = r["strategy_name"]
        if name in strategy_names and name not in weights:
            weights[name] = r["recommended_weight"]

    if len(weights) < 2:
        return None  # 数据不够

    # 归一化
    total = sum(weights.values())
    if total <= 0:
        return None

    normalized = {k: round(v / total, 3) for k, v in weights.items()}

    # 补齐缺失策略 (给予小幅默认权重)
    for name in strategy_names:
        if name not in normalized:
            if name in ("macro_cycle", "manager_alpha"):
                normalized[name] = 0.05
            else:
                normalized[name] = 0.20

    # 再次归一化
    total = sum(normalized.values())
    normalized = {k: round(v / total, 3) for k, v in normalized.items()}

    return normalized


# ── 学习报告 ──────────────────────────────────────────────


def print_learning_report():
    """输出学习进化报告"""
    console.print("\n[bold]═══ 学习进化报告 ═══[/]\n")

    # 信号验证统计
    total_signals = execute_query(
        "SELECT COUNT(*) as cnt FROM signal_validation"
    )[0]["cnt"]
    validated = execute_query(
        "SELECT COUNT(*) as cnt FROM signal_validation WHERE is_correct_30d IS NOT NULL"
    )[0]["cnt"]
    pending = total_signals - validated

    console.print(f"信号总数: {total_signals}  已验证: {validated}  待验证: {pending}\n")

    # 按策略统计
    perf = execute_query(
        """SELECT strategy_name, regime, total_signals, win_rate,
                  avg_return, recommended_weight, confidence_accuracy
           FROM strategy_performance
           ORDER BY strategy_name, regime"""
    )

    if perf:
        table = Table(title="策略表现 (按市场状态)")
        table.add_column("策略", style="cyan")
        table.add_column("市场状态")
        table.add_column("信号数")
        table.add_column("胜率")
        table.add_column("平均收益")
        table.add_column("建议权重")
        table.add_column("置信度准确")

        for p in perf:
            wr = p["win_rate"] or 0
            wr_color = "green" if wr > 0.5 else "red" if wr < 0.4 else "yellow"
            table.add_row(
                p["strategy_name"],
                p["regime"],
                str(p["total_signals"]),
                f"[{wr_color}]{wr:.0%}[/]",
                f"{(p['avg_return'] or 0):+.2f}%",
                f"{(p['recommended_weight'] or 0):.2f}",
                f"{(p['confidence_accuracy'] or 0):+.2f}",
            )

        console.print(table)
    else:
        console.print("[yellow]尚无足够的策略表现数据（需要积累至少 5 个已验证信号）[/]")

    # 当前权重 vs 默认权重
    for regime in ["bull_strong", "bull_weak", "ranging", "bear_weak", "bear_strong"]:
        learned = get_learned_weights(regime)
        if learned:
            console.print(f"\n  [{regime}] 学习后权重: {learned}")


def run_learning_cycle():
    """执行一次完整的学习循环

    在 daily 流程中调用:
    1. 验证历史信号
    2. 更新策略表现
    """
    console.print("\n[bold]执行学习进化...[/]")
    validate_pending_signals()
    update_strategy_performance()
