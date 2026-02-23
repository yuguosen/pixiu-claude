"""趋势跟踪策略 — 主策略

核心逻辑：
- 当基金净值站上关键均线且均线多头排列时买入
- 当基金净值跌破关键均线且均线转空时卖出
- 用 MACD 辅助确认趋势方向
"""

import pandas as pd

from src.analysis.indicators import (
    calculate_ma,
    calculate_macd,
    calculate_rsi,
    get_technical_summary,
)
from src.memory.database import classify_fund, get_fund_nav_history
from src.strategy.base import BacktestResult, Signal, SignalType, Strategy
from src.strategy.registry import register_strategy


@register_strategy(weight=0.30)
class TrendFollowingStrategy(Strategy):
    name = "trend_following"

    def generate_signals(
        self, market_data: dict, fund_data: dict
    ) -> list[Signal]:
        signals = []
        global_regime = market_data.get("regime", "ranging")
        category_regimes = market_data.get("category_regimes", {})

        for fund_code, data in fund_data.items():
            nav_history = data.get("nav_history", [])
            if len(nav_history) < 60:
                continue

            navs = pd.Series([r["nav"] for r in nav_history])
            tech = get_technical_summary(navs)
            if not tech:
                continue

            category = classify_fund(fund_code)
            regime = category_regimes.get(category, global_regime)
            signal_type, confidence, reasons = self._evaluate(tech, regime)

            # 多时间框架确认: 用周线趋势验证日线信号
            weekly_factor = self._weekly_confirmation(navs)
            if signal_type in (SignalType.BUY, SignalType.STRONG_BUY):
                if weekly_factor > 0:
                    confidence = min(confidence * 1.2, 0.95)
                    reasons.append("周线趋势确认")
                elif weekly_factor < 0:
                    confidence *= 0.6
                    reasons.append("周线趋势不一致")
            elif signal_type in (SignalType.SELL, SignalType.STRONG_SELL):
                if weekly_factor < 0:
                    confidence = min(confidence * 1.2, 0.95)
                    reasons.append("周线趋势确认")
                elif weekly_factor > 0:
                    confidence *= 0.6
                    reasons.append("周线趋势不一致")

            if signal_type != SignalType.HOLD:
                signals.append(Signal(
                    fund_code=fund_code,
                    signal_type=signal_type,
                    confidence=round(confidence, 2),
                    reason="; ".join(reasons),
                    strategy_name=self.name,
                    metadata={"tech_summary": tech, "weekly_factor": weekly_factor},
                ))

        return signals

    @staticmethod
    def _weekly_confirmation(navs: pd.Series) -> float:
        """周线级别趋势确认

        将日线数据聚合为周线, 判断周线趋势方向。

        Returns:
            +1 = 周线多头, -1 = 周线空头, 0 = 中性
        """
        if len(navs) < 40:
            return 0

        # 每5个交易日取一个周线收盘价
        weekly = navs.iloc[::5]
        if len(weekly) < 8:
            return 0

        mas = calculate_ma(weekly, [4, 8])  # ~20日和~40日均线
        ma4 = float(mas["MA4"].iloc[-1]) if not mas["MA4"].isna().iloc[-1] else 0
        ma8 = float(mas["MA8"].iloc[-1]) if not mas["MA8"].isna().iloc[-1] else 0

        if ma4 == 0 or ma8 == 0:
            return 0

        current = float(weekly.iloc[-1])

        score = 0
        if current > ma4 > ma8:
            score = 1  # 周线多头
        elif current < ma4 < ma8:
            score = -1  # 周线空头

        return score

    def _evaluate(
        self, tech: dict, regime: str
    ) -> tuple[SignalType, float, list[str]]:
        """根据技术指标评估信号"""
        buy_score = 0
        sell_score = 0
        reasons = []

        # 1. 均线排列
        alignment = tech.get("ma_alignment", "交叉")
        if alignment == "多头排列":
            buy_score += 3
            reasons.append("均线多头排列")
        elif alignment == "空头排列":
            sell_score += 3
            reasons.append("均线空头排列")

        # 2. MACD
        macd_signal = tech.get("macd_signal", "")
        if macd_signal == "金叉":
            buy_score += 2
            reasons.append("MACD金叉")
        elif macd_signal == "死叉":
            sell_score += 2
            reasons.append("MACD死叉")
        elif macd_signal == "多头":
            buy_score += 1
        elif macd_signal == "空头":
            sell_score += 1

        # 3. RSI
        rsi = tech.get("rsi", 50)
        if rsi < 30:
            buy_score += 1
            reasons.append(f"RSI超卖({rsi:.0f})")
        elif rsi > 70:
            sell_score += 1
            reasons.append(f"RSI超买({rsi:.0f})")

        # 4. 价格相对均线位置
        current = tech.get("current_price", 0)
        ma20 = tech.get("ma", {}).get("MA20")
        ma60 = tech.get("ma", {}).get("MA60")
        if ma20 and current > ma20:
            buy_score += 1
        elif ma20 and current < ma20:
            sell_score += 1
        if ma60 and current > ma60:
            buy_score += 1
        elif ma60 and current < ma60:
            sell_score += 1

        # 5. 市场状态修正
        if regime in ("bear_strong", "bear_weak"):
            sell_score += 1
            buy_score = max(0, buy_score - 1)
        elif regime in ("bull_strong", "bull_weak"):
            buy_score += 1
            sell_score = max(0, sell_score - 1)

        # 判断信号 — 提高阈值, 减少噪音交易
        net_score = buy_score - sell_score
        max_possible = max(buy_score + sell_score, 1)
        confidence = abs(net_score) / max_possible * 0.8

        # 必须同时满足: 均线排列 + 至少一个辅助确认
        has_ma_confirm = alignment in ("多头排列", "空头排列")
        has_secondary = (macd_signal in ("金叉", "死叉")) or (rsi < 30 or rsi > 70)

        if net_score >= 6 and has_ma_confirm:
            return SignalType.STRONG_BUY, min(confidence, 0.9), reasons
        elif net_score >= 4 and has_ma_confirm and has_secondary:
            return SignalType.BUY, min(confidence, 0.7), reasons
        elif net_score <= -6 and has_ma_confirm:
            return SignalType.STRONG_SELL, min(confidence, 0.9), reasons
        elif net_score <= -4 and has_ma_confirm and has_secondary:
            return SignalType.SELL, min(confidence, 0.7), reasons
        else:
            return SignalType.HOLD, 0, reasons

    def backtest(
        self, historical_data: dict, initial_capital: float = 10000
    ) -> BacktestResult:
        """回测 (含止损与移动止盈, 每只基金独立回测后汇总)"""
        # 风控参数: 在循环内动态计算
        # stop_loss_pct, trailing_stop_pct

        all_trades = []
        fund_returns = []

        for fund_code, data in historical_data.items():
            nav_history = data.get("nav_history", [])
            if len(nav_history) < 120:
                continue

            navs = pd.Series([r["nav"] for r in nav_history])

            # 每只基金独立回测
            capital = initial_capital
            position = 0
            cost_basis = 0
            nav_peak = 0
            peak = initial_capital
            fund_max_dd = 0
            buy_index = 0  # 追踪持有天数

            window = 60
            for i in range(window, len(navs)):
                window_navs = navs.iloc[:i + 1]
                tech = get_technical_summary(window_navs)
                if not tech:
                    continue

                signal_type, confidence, _ = self._evaluate(tech, "ranging")
                current_nav = float(navs.iloc[i])
                vol = tech.get("volatility", 0.01)

                # 获取动态止损比例
                stop_loss_pct = max(0.03, min(vol * 15, 0.15))
                trailing_stop_pct = stop_loss_pct * 1.5

                # ── 持仓中: 检查止损/止盈 ──
                if position > 0:
                    nav_peak = max(nav_peak, current_nav)
                    loss_from_cost = (current_nav - cost_basis) / cost_basis
                    loss_from_peak = (current_nav - nav_peak) / nav_peak

                    stop_triggered = False
                    stop_reason = ""

                    if loss_from_cost <= -stop_loss_pct:
                        stop_triggered = True
                        stop_reason = f"止损({loss_from_cost:.1%})"
                    elif nav_peak > cost_basis and loss_from_peak <= -trailing_stop_pct:
                        stop_triggered = True
                        stop_reason = f"移动止盈({loss_from_peak:.1%})"

                    if stop_triggered:
                        holding_days = i - buy_index
                        fee_rate = 0.015 if holding_days < 5 else 0
                        proceeds = position * current_nav * (1 - fee_rate)
                        capital += proceeds
                        pnl = (current_nav - cost_basis) / cost_basis * 100
                        all_trades.append({
                            "action": "sell", "nav": current_nav,
                            "date": nav_history[i]["nav_date"],
                            "pnl": pnl, "reason": stop_reason,
                            "fund": fund_code,
                        })
                        position = 0
                        cost_basis = 0
                        nav_peak = 0
                        total_value = capital
                        peak = max(peak, total_value)
                        dd = (total_value - peak) / peak
                        fund_max_dd = min(fund_max_dd, dd)
                        continue

                # ── 买入 ──
                if signal_type in (SignalType.BUY, SignalType.STRONG_BUY) and position == 0 and capital > 0:
                    shares = capital * 0.8 / current_nav
                    cost = capital * 0.8
                    capital -= cost
                    position = shares
                    cost_basis = current_nav
                    nav_peak = current_nav
                    buy_index = i
                    all_trades.append({
                        "action": "buy", "nav": current_nav,
                        "date": nav_history[i]["nav_date"],
                        "fund": fund_code,
                    })

                # ── 策略卖出 ──
                elif signal_type in (SignalType.SELL, SignalType.STRONG_SELL) and position > 0:
                    holding_days = i - buy_index
                    fee_rate = 0.015 if holding_days < 5 else 0
                    proceeds = position * current_nav * (1 - fee_rate)
                    capital += proceeds
                    all_trades.append({
                        "action": "sell", "nav": current_nav,
                        "date": nav_history[i]["nav_date"],
                        "pnl": (current_nav - cost_basis) / cost_basis * 100,
                        "fund": fund_code,
                    })
                    position = 0
                    cost_basis = 0
                    nav_peak = 0

                # 跟踪回撤
                total_value = capital + position * current_nav
                peak = max(peak, total_value)
                dd = (total_value - peak) / peak
                fund_max_dd = min(fund_max_dd, dd)

            # 基金回测结束: 平仓
            if position > 0:
                final_nav = float(navs.iloc[-1])
                capital += position * final_nav
                position = 0

            ret = (capital - initial_capital) / initial_capital
            fund_returns.append({"fund": fund_code, "return": ret, "max_dd": fund_max_dd})

        # 汇总所有基金的平均表现
        if fund_returns:
            avg_return = sum(r["return"] for r in fund_returns) / len(fund_returns)
            worst_dd = min(r["max_dd"] for r in fund_returns)
        else:
            avg_return = 0
            worst_dd = 0

        # 获取回测起止日期以计算年化
        all_dates = []
        for data in historical_data.values():
            nav_history = data.get("nav_history", [])
            if nav_history:
                all_dates.append(nav_history[0]["nav_date"])
                all_dates.append(nav_history[-1]["nav_date"])
        
        annualized_return = avg_return
        if all_dates and avg_return > -1:
            import datetime
            start_dt = datetime.datetime.strptime(min(all_dates), "%Y-%m-%d")
            end_dt = datetime.datetime.strptime(max(all_dates), "%Y-%m-%d")
            days = (end_dt - start_dt).days
            if days > 0:
                annualized_return = (1 + avg_return) ** (365 / days) - 1

        sell_trades = [t for t in all_trades if t["action"] == "sell"]
        profit_trades = [t for t in sell_trades if t.get("pnl", 0) > 0]

        return BacktestResult(
            strategy_name=self.name,
            total_return=round(avg_return * 100, 2),
            annualized_return=round(annualized_return * 100, 2),
            max_drawdown=round(worst_dd * 100, 2),
            sharpe_ratio=0,  # 现有系统无法生成全组合的资金曲线，暂不计算夏普比率
            win_rate=round(len(profit_trades) / max(len(sell_trades), 1) * 100, 1),
            total_trades=len(all_trades),
            profit_trades=len(profit_trades),
            details=all_trades,
        )
