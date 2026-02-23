"""蒙特卡洛模拟 — 衡量策略对运气的依赖程度

核心逻辑：
1. 获取历史交易列表 (含盈亏)
2. 随机打乱交易顺序 N 次
3. 对每次打乱模拟资金曲线
4. 统计最差/最好/中位情况
5. 如果最差情况下依然盈利 → 策略稳健
"""

import random
from dataclasses import dataclass, field

import numpy as np
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class MonteCarloResult:
    """蒙特卡洛模拟结果"""
    n_simulations: int
    n_trades: int
    median_return: float          # 中位收益
    mean_return: float            # 平均收益
    percentile_5: float           # 5% 分位 (最差情况)
    percentile_95: float          # 95% 分位 (最好情况)
    worst_return: float           # 最差收益
    best_return: float            # 最好收益
    median_max_drawdown: float    # 中位最大回撤
    worst_max_drawdown: float     # 最差最大回撤
    probability_of_profit: float  # 盈利概率
    robustness_score: float       # 稳健性评分 (0-100)
    distribution: list[float] = field(default_factory=list)


def simulate_portfolio(
    trade_pnls: list[float],
    initial_capital: float = 10000,
) -> dict:
    """模拟一次资金曲线

    Args:
        trade_pnls: 交易盈亏百分比列表
        initial_capital: 初始资金

    Returns:
        {total_return, max_drawdown, final_capital}
    """
    capital = initial_capital
    peak = capital
    max_dd = 0

    for pnl in trade_pnls:
        # 每次交易投入 80% 资金
        position = capital * 0.8
        profit = position * (pnl / 100)
        capital += profit

        peak = max(peak, capital)
        dd = (capital - peak) / peak
        max_dd = min(max_dd, dd)

        if capital <= 0:
            break

    total_return = (capital - initial_capital) / initial_capital * 100

    return {
        "total_return": total_return,
        "max_drawdown": max_dd * 100,
        "final_capital": capital,
    }


def run_monte_carlo(
    trade_pnls: list[float],
    n_simulations: int = 1000,
    initial_capital: float = 10000,
) -> MonteCarloResult:
    """运行蒙特卡洛模拟

    Args:
        trade_pnls: 历史交易盈亏百分比列表
        n_simulations: 模拟次数
        initial_capital: 初始资金

    Returns:
        MonteCarloResult
    """
    if len(trade_pnls) < 3:
        return MonteCarloResult(
            n_simulations=0, n_trades=len(trade_pnls),
            median_return=0, mean_return=0,
            percentile_5=0, percentile_95=0,
            worst_return=0, best_return=0,
            median_max_drawdown=0, worst_max_drawdown=0,
            probability_of_profit=0, robustness_score=0,
        )

    returns = []
    drawdowns = []

    for _ in range(n_simulations):
        # 随机打乱交易顺序
        shuffled = trade_pnls.copy()
        random.shuffle(shuffled)

        result = simulate_portfolio(shuffled, initial_capital)
        returns.append(result["total_return"])
        drawdowns.append(result["max_drawdown"])

    returns_arr = np.array(returns)
    drawdowns_arr = np.array(drawdowns)

    # 盈利概率
    prob_profit = float(np.sum(returns_arr > 0) / len(returns_arr) * 100)

    # 稳健性评分
    robustness = 0
    if prob_profit > 80:
        robustness += 30
    elif prob_profit > 60:
        robustness += 15

    p5 = float(np.percentile(returns_arr, 5))
    if p5 > 0:
        robustness += 30  # 5% 最差情况仍盈利
    elif p5 > -5:
        robustness += 15

    median_dd = float(np.median(drawdowns_arr))
    if abs(median_dd) < 10:
        robustness += 20
    elif abs(median_dd) < 15:
        robustness += 10

    # 收益分布集中度
    std = float(np.std(returns_arr))
    if std < 5:
        robustness += 20
    elif std < 10:
        robustness += 10

    return MonteCarloResult(
        n_simulations=n_simulations,
        n_trades=len(trade_pnls),
        median_return=round(float(np.median(returns_arr)), 2),
        mean_return=round(float(np.mean(returns_arr)), 2),
        percentile_5=round(p5, 2),
        percentile_95=round(float(np.percentile(returns_arr, 95)), 2),
        worst_return=round(float(np.min(returns_arr)), 2),
        best_return=round(float(np.max(returns_arr)), 2),
        median_max_drawdown=round(median_dd, 2),
        worst_max_drawdown=round(float(np.min(drawdowns_arr)), 2),
        probability_of_profit=round(prob_profit, 1),
        robustness_score=round(min(100, robustness), 1),
        distribution=sorted(returns),
    )


def run_monte_carlo_from_backtest(fund_data: dict) -> MonteCarloResult | None:
    """从回测交易中提取盈亏数据, 运行蒙特卡洛"""
    from src.strategy.trend_following import TrendFollowingStrategy

    strategy = TrendFollowingStrategy()
    result = strategy.backtest(fund_data)

    trade_pnls = [
        t["pnl"] for t in result.details
        if t["action"] == "sell" and "pnl" in t
    ]

    if len(trade_pnls) < 3:
        console.print("[yellow]交易数据不足 (< 3 笔), 无法进行蒙特卡洛模拟[/]")
        return None

    console.print(f"  [dim]提取 {len(trade_pnls)} 笔交易, 运行 1000 次模拟...[/]")
    return run_monte_carlo(trade_pnls)


def print_monte_carlo_report(result: MonteCarloResult):
    """打印蒙特卡洛报告"""
    console.print(f"\n[bold]═══ 蒙特卡洛模拟 ({result.n_simulations} 次) ═══[/]\n")

    table = Table(title="模拟结果分布")
    table.add_column("指标", style="cyan")
    table.add_column("数值")

    color = "green" if result.median_return > 0 else "red"
    table.add_row("中位收益", f"[{color}]{result.median_return:+.2f}%[/]")
    table.add_row("平均收益", f"{result.mean_return:+.2f}%")
    table.add_row("5% 分位 (最差)", f"[red]{result.percentile_5:+.2f}%[/]")
    table.add_row("95% 分位 (最好)", f"[green]{result.percentile_95:+.2f}%[/]")
    table.add_row("最差情况", f"[red]{result.worst_return:+.2f}%[/]")
    table.add_row("最好情况", f"[green]{result.best_return:+.2f}%[/]")
    table.add_row("", "")
    table.add_row("中位最大回撤", f"{result.median_max_drawdown:.2f}%")
    table.add_row("最差最大回撤", f"{result.worst_max_drawdown:.2f}%")
    table.add_row("", "")
    table.add_row("盈利概率", f"{result.probability_of_profit:.1f}%")
    table.add_row("稳健性评分", f"{result.robustness_score:.0f}/100")

    console.print(table)

    if result.probability_of_profit >= 70:
        console.print("  [green]策略稳健: 即使交易顺序随机化，仍有较高盈利概率[/]")
    elif result.probability_of_profit >= 50:
        console.print("  [yellow]策略一般: 对运气有一定依赖[/]")
    else:
        console.print("  [red]策略存疑: 盈利高度依赖交易顺序 (运气)[/]")
