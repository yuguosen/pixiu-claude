"""基金经理 Alpha 筛选策略 — 选对人比选对时机重要

核心逻辑：
- 评估基金经理能力 (年化收益/回撤/夏普/风格稳定性)
- 高分经理的基金信号加强，低分经理的信号削弱
- 不直接生成买卖信号，而是作为置信度修正器
"""

from src.strategy.base import Signal, SignalType, Strategy
from src.strategy.registry import register_strategy


@register_strategy(weight=0.10)
class ManagerAlphaStrategy(Strategy):
    """基金经理质量作为信号修正器

    不独立生成买卖信号，而是基于经理评分给出加分/减分。
    只对已有数据且评分较高的基金产生正向信号。
    """
    name = "manager_alpha"

    def generate_signals(
        self, market_data: dict, fund_data: dict
    ) -> list[Signal]:
        """基于基金经理评分生成辅助信号

        market_data 需包含 manager_scores: {fund_code: {score, grade, reasons}}
        """
        manager_scores = market_data.get("manager_scores", {})
        if not manager_scores:
            return []

        signals = []

        for fund_code in fund_data:
            eval_data = manager_scores.get(fund_code)
            if not eval_data:
                continue

            score = eval_data.get("score", 50)
            grade = eval_data.get("grade", "C")
            reasons = eval_data.get("reasons", [])
            reason_text = "; ".join(reasons[:3]) if reasons else f"经理评分 {score}"

            # A 级经理: 生成弱买入信号 (加持其他策略)
            if grade == "A":
                signals.append(Signal(
                    fund_code=fund_code,
                    signal_type=SignalType.BUY,
                    confidence=0.40,
                    reason=f"基金经理评级 A ({score}分): {reason_text}",
                    strategy_name=self.name,
                    priority=30,
                    metadata={"manager_score": score, "grade": grade},
                ))
            # B 级: 中性偏正
            elif grade == "B":
                signals.append(Signal(
                    fund_code=fund_code,
                    signal_type=SignalType.BUY,
                    confidence=0.25,
                    reason=f"基金经理评级 B ({score}分): {reason_text}",
                    strategy_name=self.name,
                    priority=20,
                    metadata={"manager_score": score, "grade": grade},
                ))
            # D 级: 生成弱卖出信号 (警告)
            elif grade == "D":
                signals.append(Signal(
                    fund_code=fund_code,
                    signal_type=SignalType.SELL,
                    confidence=0.30,
                    reason=f"基金经理评级 D ({score}分)，能力存疑: {reason_text}",
                    strategy_name=self.name,
                    priority=25,
                    metadata={"manager_score": score, "grade": grade},
                ))

        return signals
