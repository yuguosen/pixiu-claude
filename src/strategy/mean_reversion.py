"""均值回归策略 — 辅助策略

核心逻辑：
- 当基金净值偏离均值过多时反向操作
- RSI 超卖时买入，超买时卖出
- 布林带突破后回归时操作
- 适用于震荡市
"""

import pandas as pd

from src.analysis.indicators import (
    calculate_bollinger,
    calculate_rsi,
    get_technical_summary,
)
from src.strategy.base import Signal, SignalType, Strategy
from src.strategy.registry import register_strategy


@register_strategy(weight=0.30)
class MeanReversionStrategy(Strategy):
    name = "mean_reversion"

    def generate_signals(
        self, market_data: dict, fund_data: dict
    ) -> list[Signal]:
        signals = []
        global_regime = market_data.get("regime", "ranging")
        category_regimes = market_data.get("category_regimes", {})

        from src.memory.database import classify_fund
        for fund_code, data in fund_data.items():
            category = classify_fund(fund_code)
            regime = category_regimes.get(category, global_regime)

            # 均值回归在震荡市权重最高
            if regime in ("bull_strong", "bear_strong"):
                continue  # 强趋势市不使用均值回归

            nav_history = data.get("nav_history", [])
            if len(nav_history) < 30:
                continue

            navs = pd.Series([r["nav"] for r in nav_history])
            tech = get_technical_summary(navs)
            if not tech:
                continue

            signal_type, confidence, reasons = self._evaluate(tech)

            if signal_type != SignalType.HOLD:
                signals.append(Signal(
                    fund_code=fund_code,
                    signal_type=signal_type,
                    confidence=confidence,
                    reason="; ".join(reasons),
                    strategy_name=self.name,
                    metadata={"tech_summary": tech},
                ))

        return signals

    def _evaluate(
        self, tech: dict
    ) -> tuple[SignalType, float, list[str]]:
        """根据均值偏离度评估信号"""
        buy_score = 0
        sell_score = 0
        reasons = []

        # 1. RSI 超买超卖
        rsi = tech.get("rsi", 50)
        if rsi < 25:
            buy_score += 3
            reasons.append(f"RSI 深度超卖({rsi:.0f})")
        elif rsi < 35:
            buy_score += 1
            reasons.append(f"RSI 超卖({rsi:.0f})")
        elif rsi > 75:
            sell_score += 3
            reasons.append(f"RSI 深度超买({rsi:.0f})")
        elif rsi > 65:
            sell_score += 1
            reasons.append(f"RSI 超买({rsi:.0f})")

        # 2. 布林带位置
        bb_signal = tech.get("bb_signal", "")
        bb_position = tech.get("bb_position", 0.5)

        if bb_signal == "突破下轨":
            buy_score += 2
            reasons.append("跌破布林下轨")
        elif bb_position < 0.2:
            buy_score += 1
            reasons.append(f"接近布林下轨(位置{bb_position:.0%})")
        elif bb_signal == "突破上轨":
            sell_score += 2
            reasons.append("突破布林上轨")
        elif bb_position > 0.8:
            sell_score += 1
            reasons.append(f"接近布林上轨(位置{bb_position:.0%})")

        # 3. 价格偏离 MA20
        current = tech.get("current_price", 0)
        ma20 = tech.get("ma", {}).get("MA20")
        if ma20 and ma20 > 0:
            deviation = (current - ma20) / ma20
            if deviation < -0.05:
                buy_score += 2
                reasons.append(f"偏离MA20 {deviation:.1%}")
            elif deviation > 0.05:
                sell_score += 2
                reasons.append(f"偏离MA20 {deviation:+.1%}")

        # 判断信号
        net_score = buy_score - sell_score
        max_possible = max(buy_score + sell_score, 1)
        confidence = abs(net_score) / max_possible * 0.7

        if net_score >= 4:
            return SignalType.STRONG_BUY, min(confidence, 0.8), reasons
        elif net_score >= 2:
            return SignalType.BUY, min(confidence, 0.6), reasons
        elif net_score <= -4:
            return SignalType.STRONG_SELL, min(confidence, 0.8), reasons
        elif net_score <= -2:
            return SignalType.SELL, min(confidence, 0.6), reasons
        else:
            return SignalType.HOLD, 0, reasons
