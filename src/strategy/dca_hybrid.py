"""定投+择时混合策略 — 底仓定投 + 机动择时

核心逻辑：
- 70% 资金做智能定投 (低估多投，高估少投)
- 30% 资金做择时操作 (极端信号才动，一年 3-5 次)
- 定投金额根据估值分位动态调整

定投比例调整规则：
  PE分位 < 20% → 定投金额 ×2.0
  PE分位 20-30% → ×1.5
  PE分位 30-50% → ×1.0
  PE分位 50-70% → ×0.7
  PE分位 70-80% → ×0.3
  PE分位 > 80% → 暂停定投
"""

from src.strategy.base import Signal, SignalType, Strategy


# 定投金额乘数映射
DCA_MULTIPLIERS = [
    (20, 2.0),
    (30, 1.5),
    (50, 1.0),
    (70, 0.7),
    (80, 0.3),
    (100, 0.0),
]


def get_dca_multiplier(pe_percentile: float) -> float:
    """根据 PE 分位获取定投乘数"""
    for threshold, multiplier in DCA_MULTIPLIERS:
        if pe_percentile < threshold:
            return multiplier
    return 0.0


class DCAHybridStrategy(Strategy):
    """定投+择时混合策略

    生成定投建议信号，金额随估值分位调整。
    """
    name = "dca_hybrid"

    def __init__(self, weekly_amount: float = 500):
        """
        Args:
            weekly_amount: 每周基础定投金额 (RMB)
        """
        self.weekly_amount = weekly_amount

    def generate_signals(
        self, market_data: dict, fund_data: dict
    ) -> list[Signal]:
        """生成定投信号

        market_data 需包含 valuation_signal: {pe_percentile}
        """
        valuation = market_data.get("valuation_signal", {})
        pe_pct = valuation.get("pe_percentile", 50)

        multiplier = get_dca_multiplier(pe_pct)
        adjusted_amount = self.weekly_amount * multiplier

        if adjusted_amount <= 0:
            # 高估暂停定投
            return [Signal(
                fund_code=list(fund_data.keys())[0] if fund_data else "000300",
                signal_type=SignalType.HOLD,
                confidence=0.70,
                reason=f"PE分位 {pe_pct:.0f}% 偏高，暂停定投",
                strategy_name=self.name,
                priority=20,
                metadata={"pe_percentile": pe_pct, "dca_multiplier": 0},
            )]

        signals = []
        # 只对观察池中评分最高的基金定投
        # 这里给所有基金发信号，由上层筛选
        for fund_code in fund_data:
            confidence = 0.50 * multiplier  # 估值越低，置信度越高
            confidence = min(0.80, max(0.20, confidence))

            signals.append(Signal(
                fund_code=fund_code,
                signal_type=SignalType.BUY,
                confidence=round(confidence, 2),
                reason=(
                    f"智能定投: 基础 {self.weekly_amount} × {multiplier:.1f} = "
                    f"{adjusted_amount:.0f} RMB/周 (PE分位 {pe_pct:.0f}%)"
                ),
                strategy_name=self.name,
                target_amount=adjusted_amount,
                priority=15,
                metadata={
                    "pe_percentile": pe_pct,
                    "dca_multiplier": multiplier,
                    "adjusted_amount": adjusted_amount,
                },
            ))

        return signals
