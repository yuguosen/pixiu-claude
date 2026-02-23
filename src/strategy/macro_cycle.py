"""宏观周期策略 — 信贷周期决定大类资产配置

核心逻辑：
- 信贷扩张 (PMI↑ + M2↑) → 偏股
- 经济见顶 (PMI↑ + M2↓) → 均衡
- 信贷紧缩 (PMI↓ + M2↓) → 偏债
- 政策底部 (PMI↓ + M2↑) → 左侧布局

信号频率低（月度），作为大方向参考。
"""

from src.strategy.base import Signal, SignalType, Strategy
from src.strategy.registry import register_strategy


@register_strategy(weight=0.10)
class MacroCycleStrategy(Strategy):
    name = "macro_cycle"

    def generate_signals(
        self, market_data: dict, fund_data: dict
    ) -> list[Signal]:
        """基于宏观周期生成信号

        market_data 需包含 macro_snapshot: {credit_cycle, cycle_signal, narrative}
        """
        macro = market_data.get("macro_snapshot", {})
        cycle = macro.get("credit_cycle", "unknown")
        narrative = macro.get("narrative", "")

        if cycle == "unknown":
            return []

        signals = []

        # 根据信贷周期阶段给出信号
        cycle_config = {
            "expansion": {
                "signal_type": SignalType.BUY,
                "confidence": 0.65,
                "reason": f"信贷扩张期，利好权益资产。{narrative}",
            },
            "recovery": {
                "signal_type": SignalType.BUY,
                "confidence": 0.55,
                "reason": f"政策底/经济底，可左侧布局。{narrative}",
            },
            "peak": {
                "signal_type": SignalType.HOLD,
                "confidence": 0.40,
                "reason": f"经济见顶期，维持现有配置。{narrative}",
            },
            "contraction": {
                "signal_type": SignalType.SELL,
                "confidence": 0.60,
                "reason": f"信贷紧缩期，减少权益敞口。{narrative}",
            },
        }

        config = cycle_config.get(cycle)
        if not config or config["signal_type"] == SignalType.HOLD:
            return []

        from src.memory.database import classify_fund
        for fund_code in fund_data:
            category = classify_fund(fund_code)
            if category not in ("equity", "index"):
                continue

            signals.append(Signal(
                fund_code=fund_code,
                signal_type=config["signal_type"],
                confidence=config["confidence"],
                reason=config["reason"],
                strategy_name=self.name,
                priority=50,
                metadata={"credit_cycle": cycle},
            ))

        return signals
