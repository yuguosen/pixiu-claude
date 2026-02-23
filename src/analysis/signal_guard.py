"""信号循环检测 — 识别并降级反复出错的信号模式

检测三种反模式:
1. 连续同方向错误 >= 3 次
2. 乒乓模式 (BUY-SELL-BUY-SELL 交替且多数错误)
3. 置信度虚高 (高置信度信号胜率低于 40%)
"""

from dataclasses import dataclass

from rich.console import Console

from src.memory.database import execute_query

console = Console()


@dataclass
class SignalHealth:
    fund_code: str
    penalty_factor: float = 1.0  # 乘以置信度 (0.3 ~ 1.0)
    suppressed: bool = False  # 是否完全压制
    reason: str = ""


def check_signal_health(fund_code: str, lookback_days: int = 90) -> SignalHealth:
    """查询 signal_validation 表，检测反模式"""
    from datetime import datetime, timedelta

    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    records = execute_query(
        """SELECT signal_type, is_correct_30d, confidence
           FROM signal_validation
           WHERE fund_code = ? AND strategy_name = 'composite'
             AND signal_date >= ?
           ORDER BY signal_date DESC LIMIT 10""",
        (fund_code, cutoff),
    )

    if len(records) < 3:
        return SignalHealth(fund_code=fund_code)

    # 反模式 1: 连续同方向错误 >= 3 次
    consecutive_wrong = 0
    last_direction = None
    for r in records:
        is_buy = r["signal_type"] in ("strong_buy", "buy")
        direction = "buy" if is_buy else "sell"
        correct = r["is_correct_30d"]

        if correct == 0 and (last_direction is None or direction == last_direction):
            consecutive_wrong += 1
            last_direction = direction
        else:
            break

    if consecutive_wrong >= 3:
        return SignalHealth(
            fund_code=fund_code,
            penalty_factor=0.3,
            suppressed=consecutive_wrong >= 5,
            reason=f"连续 {consecutive_wrong} 次同方向错误",
        )

    # 反模式 2: 乒乓模式
    validated = [r for r in records if r["is_correct_30d"] is not None]
    if len(validated) >= 4:
        directions = [
            "buy" if r["signal_type"] in ("strong_buy", "buy") else "sell"
            for r in validated
        ]
        alternating = sum(
            1 for i in range(1, len(directions)) if directions[i] != directions[i - 1]
        )
        wrong_count = sum(1 for r in validated if r["is_correct_30d"] == 0)

        if alternating >= len(directions) * 0.7 and wrong_count >= len(validated) * 0.6:
            return SignalHealth(
                fund_code=fund_code,
                penalty_factor=0.5,
                reason=f"乒乓模式 ({alternating}/{len(directions)} 交替, {wrong_count}/{len(validated)} 错误)",
            )

    # 反模式 3: 置信度虚高
    high_conf = [r for r in validated if (r["confidence"] or 0) >= 0.6]
    if len(high_conf) >= 3:
        high_correct = sum(1 for r in high_conf if r["is_correct_30d"] == 1)
        high_win_rate = high_correct / len(high_conf)
        if high_win_rate < 0.4:
            return SignalHealth(
                fund_code=fund_code,
                penalty_factor=0.6,
                reason=f"高置信度胜率仅 {high_win_rate:.0%} ({high_correct}/{len(high_conf)})",
            )

    return SignalHealth(fund_code=fund_code)


def apply_signal_guard(signals: list) -> list:
    """对 composite signals 应用健康检查，降级或移除问题信号"""
    if not signals:
        return signals

    guarded = []
    for sig in signals:
        health = check_signal_health(sig.fund_code)

        if health.suppressed:
            console.print(
                f"  [yellow]信号守卫: {sig.fund_code} 已压制 — {health.reason}[/]"
            )
            continue

        if health.penalty_factor < 1.0:
            original_conf = sig.confidence
            sig.confidence = round(sig.confidence * health.penalty_factor, 2)
            sig.reason += f"\n[signal_guard] 置信度降级 {original_conf} → {sig.confidence} ({health.reason})"
            console.print(
                f"  [dim]信号守卫: {sig.fund_code} 降级 ×{health.penalty_factor:.1f} — {health.reason}[/]"
            )

        guarded.append(sig)

    return guarded
