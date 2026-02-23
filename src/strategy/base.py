"""策略基类"""

from dataclasses import dataclass, field
from enum import Enum


class SignalType(Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class Signal:
    fund_code: str
    signal_type: SignalType
    confidence: float  # 0-1
    reason: str
    strategy_name: str
    target_amount: float = 0  # 建议交易金额
    priority: int = 0  # 优先级，越高越优先
    metadata: dict = field(default_factory=dict)

    @property
    def is_buy(self) -> bool:
        return self.signal_type in (SignalType.STRONG_BUY, SignalType.BUY)

    @property
    def is_sell(self) -> bool:
        return self.signal_type in (SignalType.STRONG_SELL, SignalType.SELL)


@dataclass
class BacktestResult:
    strategy_name: str
    total_return: float  # 总收益率
    annualized_return: float  # 年化收益率
    max_drawdown: float  # 最大回撤
    sharpe_ratio: float  # 夏普比率
    win_rate: float  # 胜率
    total_trades: int  # 交易次数
    profit_trades: int  # 盈利次数
    details: list[dict] = field(default_factory=list)


class Strategy:
    """策略基类"""

    name: str = "base"

    def generate_signals(
        self, market_data: dict, fund_data: dict
    ) -> list[Signal]:
        """生成交易信号

        Args:
            market_data: 市场状态数据
            fund_data: 基金数据

        Returns:
            信号列表
        """
        raise NotImplementedError

    def backtest(
        self, historical_data: dict, initial_capital: float = 10000
    ) -> BacktestResult:
        """回测策略

        Args:
            historical_data: 历史数据
            initial_capital: 初始资金

        Returns:
            回测结果
        """
        raise NotImplementedError
