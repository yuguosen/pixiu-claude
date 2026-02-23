"""估值驱动策略 — 最有效的单一择时指标

核心逻辑：
- PE 分位 < 20% → 积极买入
- PE 分位 20-30% → 加大定投
- PE 分位 70-80% → 停止买入
- PE 分位 > 80% → 逐步减仓

这不是高频策略，信号变化周期以月计。
"""

from src.memory.database import classify_fund
from src.strategy.base import Signal, SignalType, Strategy
from src.strategy.registry import register_strategy


@register_strategy(weight=0.25)
class ValuationStrategy(Strategy):
    name = "valuation"

    def generate_signals(
        self, market_data: dict, fund_data: dict
    ) -> list[Signal]:
        """基于估值分位生成信号

        market_data 需包含 valuation_signal: {pe_percentile, position_multiplier, narrative}

        仅对 equity/index 类基金生效 — PE 分位对债券/黄金/QDII 无意义。
        """
        valuation = market_data.get("valuation_signal", {})
        pe_pct = valuation.get("pe_percentile", 50)
        narrative = valuation.get("narrative", "")

        signals = []

        for fund_code in fund_data:
            category = classify_fund(fund_code)
            if category not in ("equity", "index"):
                continue

            if pe_pct < 20:
                signals.append(Signal(
                    fund_code=fund_code,
                    signal_type=SignalType.STRONG_BUY,
                    confidence=0.85,
                    reason=f"估值极低 (PE分位 {pe_pct:.0f}%)，历史底部区域。{narrative}",
                    strategy_name=self.name,
                    priority=90,
                    metadata={"pe_percentile": pe_pct, "category": category},
                ))
            elif pe_pct < 30:
                signals.append(Signal(
                    fund_code=fund_code,
                    signal_type=SignalType.BUY,
                    confidence=0.70,
                    reason=f"估值低估 (PE分位 {pe_pct:.0f}%)。{narrative}",
                    strategy_name=self.name,
                    priority=70,
                    metadata={"pe_percentile": pe_pct, "category": category},
                ))
            elif pe_pct > 85:
                signals.append(Signal(
                    fund_code=fund_code,
                    signal_type=SignalType.STRONG_SELL,
                    confidence=0.80,
                    reason=f"估值极高 (PE分位 {pe_pct:.0f}%)，应逐步减仓。{narrative}",
                    strategy_name=self.name,
                    priority=85,
                    metadata={"pe_percentile": pe_pct, "category": category},
                ))
            elif pe_pct > 75:
                signals.append(Signal(
                    fund_code=fund_code,
                    signal_type=SignalType.SELL,
                    confidence=0.60,
                    reason=f"估值偏高 (PE分位 {pe_pct:.0f}%)。{narrative}",
                    strategy_name=self.name,
                    priority=60,
                    metadata={"pe_percentile": pe_pct, "category": category},
                ))
            # 30-75%: 不产生信号，由其他策略驱动

        return signals
