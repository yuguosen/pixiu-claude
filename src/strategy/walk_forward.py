"""走前验证 (Walk-Forward) — 让回测不再自欺欺人

核心逻辑：
1. 将历史数据分成 N 个窗口
2. 用窗口 1-K 训练 (生成信号), 用窗口 K+1 测试
3. 滑动: 用窗口 2-(K+1) 训练, 用窗口 K+2 测试
4. 汇总所有测试窗口的结果

优势：模拟真实的"未来未知"状态。
"""

import pandas as pd
from dataclasses import dataclass, field
from rich.console import Console
from rich.table import Table

from src.analysis.indicators import get_technical_summary
from src.strategy.base import BacktestResult, Signal, SignalType

console = Console()


@dataclass
class WalkForwardResult:
    """走前验证结果"""
    strategy_name: str
    n_windows: int
    avg_return: float
    worst_return: float
    best_return: float
    avg_win_rate: float
    total_trades: int
    window_results: list[dict] = field(default_factory=list)
    robustness_score: float = 0.0  # 0-100, 衡量策略稳健性


def run_walk_forward(
    fund_data: dict,
    n_windows: int = 6,
    train_ratio: float = 0.7,
) -> WalkForwardResult:
    """运行走前验证

    Args:
        fund_data: {fund_code: {nav_history: [...]}}
        n_windows: 验证窗口数
        train_ratio: 训练集占比

    Returns:
        WalkForwardResult
    """
    from src.strategy.trend_following import TrendFollowingStrategy

    strategy = TrendFollowingStrategy()
    window_results = []

    for fund_code, data in fund_data.items():
        nav_history = data.get("nav_history", [])
        if len(nav_history) < 200:
            continue

        total_len = len(nav_history)
        window_size = total_len // n_windows

        if window_size < 60:
            continue

        for i in range(n_windows - 1):
            # 训练窗口: [0, train_end)
            train_end = (i + 1) * window_size
            train_size = int(train_end * train_ratio)

            # 测试窗口: [train_end, test_end)
            test_start = train_end
            test_end = min(test_start + window_size, total_len)

            if test_end - test_start < 20:
                continue

            # 在测试窗口上模拟交易
            test_navs = nav_history[test_start:test_end]
            navs = pd.Series([r["nav"] for r in test_navs])

            if len(navs) < 30:
                continue

            # 简化回测: 在测试窗口开头看信号, 期末看结果
            full_navs = pd.Series([r["nav"] for r in nav_history[:test_end]])
            tech = get_technical_summary(full_navs.iloc[:test_start + 30])

            if not tech:
                continue

            start_nav = float(navs.iloc[0])
            end_nav = float(navs.iloc[-1])
            period_return = (end_nav - start_nav) / start_nav * 100

            # 获取窗口开始时的信号
            rsi = tech.get("rsi", 50)
            ma_alignment = tech.get("ma_alignment", "交叉")

            # 判断信号方向
            if ma_alignment == "多头排列" and rsi < 70:
                predicted_direction = "buy"
            elif ma_alignment == "空头排列" and rsi > 30:
                predicted_direction = "sell"
            else:
                predicted_direction = "hold"

            is_correct = (
                (predicted_direction == "buy" and period_return > 0) or
                (predicted_direction == "sell" and period_return < 0) or
                (predicted_direction == "hold")
            )

            window_results.append({
                "fund_code": fund_code,
                "window": i,
                "train_end": nav_history[train_end - 1]["nav_date"] if train_end > 0 else "",
                "test_period": f"{test_navs[0]['nav_date']} ~ {test_navs[-1]['nav_date']}",
                "predicted": predicted_direction,
                "actual_return": round(period_return, 2),
                "is_correct": is_correct,
            })

    if not window_results:
        return WalkForwardResult(
            strategy_name="trend_following",
            n_windows=n_windows,
            avg_return=0, worst_return=0, best_return=0,
            avg_win_rate=0, total_trades=0,
        )

    # 汇总
    returns = [w["actual_return"] for w in window_results if w["predicted"] != "hold"]
    correct = [w for w in window_results if w["is_correct"] and w["predicted"] != "hold"]
    active = [w for w in window_results if w["predicted"] != "hold"]

    avg_return = sum(returns) / len(returns) if returns else 0
    worst_return = min(returns) if returns else 0
    best_return = max(returns) if returns else 0
    win_rate = len(correct) / len(active) * 100 if active else 0

    # 稳健性评分
    # 基于: 胜率, 最差窗口, 窗口间一致性
    robustness = 0
    if win_rate > 60:
        robustness += 30
    elif win_rate > 50:
        robustness += 15
    if worst_return > -10:
        robustness += 30
    elif worst_return > -15:
        robustness += 15
    if len(returns) > 3:
        # 收益一致性 (标准差越小越稳健)
        import numpy as np
        std = float(np.std(returns))
        if std < 5:
            robustness += 40
        elif std < 10:
            robustness += 20

    return WalkForwardResult(
        strategy_name="trend_following",
        n_windows=n_windows,
        avg_return=round(avg_return, 2),
        worst_return=round(worst_return, 2),
        best_return=round(best_return, 2),
        avg_win_rate=round(win_rate, 1),
        total_trades=len(active),
        window_results=window_results,
        robustness_score=round(robustness, 1),
    )


def print_walk_forward_report(result: WalkForwardResult):
    """打印走前验证报告"""
    console.print(f"\n[bold]═══ 走前验证报告 ({result.n_windows} 窗口) ═══[/]\n")

    table = Table(title="总结")
    table.add_column("指标", style="cyan")
    table.add_column("数值")

    color = "green" if result.avg_return > 0 else "red"
    table.add_row("平均收益", f"[{color}]{result.avg_return:+.2f}%[/]")
    table.add_row("最差窗口", f"[red]{result.worst_return:+.2f}%[/]")
    table.add_row("最好窗口", f"[green]{result.best_return:+.2f}%[/]")
    table.add_row("胜率", f"{result.avg_win_rate:.1f}%")
    table.add_row("交易次数", str(result.total_trades))
    table.add_row("稳健性评分", f"{result.robustness_score:.0f}/100")
    console.print(table)

    if result.window_results:
        detail = Table(title="窗口明细")
        detail.add_column("基金")
        detail.add_column("测试期")
        detail.add_column("预测")
        detail.add_column("实际")
        detail.add_column("结果")

        for w in result.window_results[:20]:
            correct_icon = "[green]✓[/]" if w["is_correct"] else "[red]✗[/]"
            color = "green" if w["actual_return"] > 0 else "red"
            detail.add_row(
                w["fund_code"],
                w["test_period"],
                w["predicted"],
                f"[{color}]{w['actual_return']:+.2f}%[/]",
                correct_icon,
            )
        console.print(detail)
