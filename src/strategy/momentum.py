"""动量策略 — 辅助策略 (升级版)

核心逻辑 (v2):
- 使用风险调整后的动量 (夏普动量), 而非原始涨幅
- 剔除最近 5 天的短期反转噪音
- 评估路径质量: 平稳上涨优于暴涨暴跌
- 多周期动量交叉确认 (20日 vs 60日)
"""

import numpy as np
import pandas as pd

from src.memory.database import get_fund_nav_history
from src.strategy.base import Signal, SignalType, Strategy
from src.strategy.registry import register_strategy


@register_strategy(weight=0.20)
class MomentumStrategy(Strategy):
    name = "momentum"

    def __init__(self, lookback_days: int = 60, top_n: int = 3):
        self.lookback_days = lookback_days
        self.top_n = top_n

    def generate_signals(
        self, market_data: dict, fund_data: dict
    ) -> list[Signal]:
        signals = []
        regime = market_data.get("regime", "ranging")

        # 动量策略在强趋势市效果最好
        if regime in ("bear_strong",):
            return signals

        # 计算所有基金的多维动量
        momentum_list = []
        for fund_code, data in fund_data.items():
            nav_history = data.get("nav_history", [])
            if len(nav_history) < self.lookback_days:
                continue

            navs = pd.Series([r["nav"] for r in nav_history], dtype=float)
            score = self._compute_momentum_score(navs)
            if score is not None:
                momentum_list.append({
                    "fund_code": fund_code,
                    **score,
                })

        if len(momentum_list) < 2:
            return signals

        # 按综合动量评分排序
        momentum_list.sort(key=lambda x: x["composite_score"], reverse=True)

        # 买入信号：综合评分最强的 top_n 只
        for item in momentum_list[: self.top_n]:
            if item["composite_score"] > 5:  # 要求综合评分 > 5
                confidence = min(0.7, item["composite_score"] / 50)
                reasons = []
                reasons.append(f"夏普动量 {item['sharpe_momentum']:.2f}")
                reasons.append(f"路径质量 {item['path_quality']:.0%}")
                if item["trend_accel"]:
                    reasons.append("动量加速")

                signals.append(Signal(
                    fund_code=item["fund_code"],
                    signal_type=SignalType.BUY,
                    confidence=round(confidence, 2),
                    reason=", ".join(reasons),
                    strategy_name=self.name,
                    metadata={
                        "composite_score": item["composite_score"],
                        "sharpe_momentum": item["sharpe_momentum"],
                    },
                ))

        # 卖出信号：综合评分最弱的
        for item in momentum_list[-self.top_n:]:
            if item["composite_score"] < -10:
                confidence = min(0.7, abs(item["composite_score"]) / 50)
                signals.append(Signal(
                    fund_code=item["fund_code"],
                    signal_type=SignalType.SELL,
                    confidence=round(confidence, 2),
                    reason=f"动量排名靠后, 综合评分 {item['composite_score']:.1f}",
                    strategy_name=self.name,
                    metadata={
                        "composite_score": item["composite_score"],
                        "sharpe_momentum": item["sharpe_momentum"],
                    },
                ))

        return signals

    def _compute_momentum_score(self, navs: pd.Series) -> dict | None:
        """计算多维动量评分

        Returns:
            {
                "raw_momentum": 原始动量 (%),
                "sharpe_momentum": 风险调整动量,
                "path_quality": 路径质量 (0~1),
                "trend_accel": 趋势加速标志,
                "composite_score": 综合评分,
            }
        """
        if len(navs) < self.lookback_days:
            return None

        # ── 1. 原始动量 (剔除最近5天反转噪音) ──
        # 用 T-5 到 T-60 的区间, 避免短期反转影响
        t5 = navs.iloc[-6] if len(navs) >= 6 else navs.iloc[-1]
        t60 = navs.iloc[-self.lookback_days]
        if t60 <= 0:
            return None
        raw_momentum = (t5 - t60) / t60 * 100

        # ── 2. 夏普动量 (风险调整) ──
        period_navs = navs.iloc[-self.lookback_days:-5] if len(navs) > 5 else navs.iloc[-self.lookback_days:]
        daily_returns = period_navs.pct_change().dropna()
        if len(daily_returns) < 10 or daily_returns.std() == 0:
            sharpe_momentum = raw_momentum / 10  # 降级
        else:
            sharpe_momentum = float(
                daily_returns.mean() / daily_returns.std() * np.sqrt(250)
            )

        # ── 3. 路径质量 (上涨的一致性) ──
        # 统计日收益为正的比例, 以及连续上涨天数
        if len(daily_returns) > 0:
            positive_ratio = (daily_returns > 0).sum() / len(daily_returns)
            # 如果连续下跌超过5天, 路径质量惩罚
            neg_streak = 0
            max_neg_streak = 0
            for r in daily_returns:
                if r < 0:
                    neg_streak += 1
                    max_neg_streak = max(max_neg_streak, neg_streak)
                else:
                    neg_streak = 0
            streak_penalty = max(0, 1 - max_neg_streak / 10)
            path_quality = positive_ratio * 0.7 + streak_penalty * 0.3
        else:
            path_quality = 0.5

        # ── 4. 动量加速 (短期 vs 长期) ──
        if len(navs) >= 25:
            t20 = navs.iloc[-21] if len(navs) >= 21 else navs.iloc[0]
            short_mom = (t5 - t20) / t20 * 100 if t20 > 0 else 0
            long_mom = raw_momentum
            trend_accel = short_mom > long_mom * 0.5 and short_mom > 2
        else:
            trend_accel = False

        # ── 5. 综合评分 ──
        composite = (
            sharpe_momentum * 10       # 夏普动量 (核心因子)
            + raw_momentum * 0.3       # 原始动量 (辅助)
            + path_quality * 10        # 路径质量
            + (5 if trend_accel else 0) # 加速奖励
        )

        return {
            "raw_momentum": round(raw_momentum, 2),
            "sharpe_momentum": round(sharpe_momentum, 2),
            "path_quality": round(path_quality, 2),
            "trend_accel": trend_accel,
            "composite_score": round(composite, 2),
        }
