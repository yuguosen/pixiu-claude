"""技术指标计算 (基于 pandas/numpy)"""

import numpy as np
import pandas as pd


def calculate_ma(series: pd.Series, windows: list[int] = None) -> dict[str, pd.Series]:
    """计算移动平均线

    Args:
        series: 价格序列
        windows: 窗口列表，默认 [5, 10, 20, 60, 120, 250]

    Returns:
        dict: {"MA5": series, "MA10": series, ...}
    """
    if windows is None:
        windows = [5, 10, 20, 60, 120, 250]
    return {f"MA{w}": series.rolling(window=w).mean() for w in windows}


def calculate_ema(series: pd.Series, windows: list[int] = None) -> dict[str, pd.Series]:
    """计算指数移动平均线"""
    if windows is None:
        windows = [12, 26]
    return {f"EMA{w}": series.ewm(span=w, adjust=False).mean() for w in windows}


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """计算 RSI (相对强弱指数)

    Args:
        series: 价格序列
        period: 计算周期，默认14

    Returns:
        RSI 序列 (0-100)
    """
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> dict[str, pd.Series]:
    """计算 MACD

    Returns:
        dict: {"dif": DIF线, "dea": DEA线(信号线), "histogram": MACD柱}
    """
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    histogram = 2 * (dif - dea)

    return {"dif": dif, "dea": dea, "histogram": histogram}


def calculate_bollinger(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> dict[str, pd.Series]:
    """计算布林带

    Returns:
        dict: {"middle": 中轨, "upper": 上轨, "lower": 下轨, "width": 带宽}
    """
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    width = (upper - lower) / middle

    return {"middle": middle, "upper": upper, "lower": lower, "width": width}


def calculate_volatility(series: pd.Series, window: int = 20) -> pd.Series:
    """计算滚动波动率 (年化)"""
    log_returns = np.log(series / series.shift(1))
    return log_returns.rolling(window=window).std() * np.sqrt(250)


def calculate_sharpe_ratio(
    returns: pd.Series, risk_free_rate: float = 0.02
) -> float:
    """计算夏普比率

    Args:
        returns: 日收益率序列
        risk_free_rate: 年化无风险利率，默认 2%

    Returns:
        年化夏普比率
    """
    returns = returns.dropna()
    if returns.empty or returns.std() == 0:
        return 0.0
    excess_returns = returns - risk_free_rate / 250
    return float(excess_returns.mean() / returns.std() * np.sqrt(250))


def calculate_max_drawdown(series: pd.Series) -> tuple[float, str, str]:
    """计算最大回撤

    Args:
        series: 净值序列

    Returns:
        (最大回撤比例, 起始日期索引, 结束日期索引)
    """
    if series.empty:
        return 0.0, "", ""

    cummax = series.cummax()
    drawdown = (series - cummax) / cummax
    max_dd = drawdown.min()
    end_idx = drawdown.idxmin()

    # 找到峰值位置
    start_idx = series[:end_idx].idxmax() if end_idx is not None else None

    return float(max_dd), str(start_idx), str(end_idx)


def calculate_sortino_ratio(
    returns: pd.Series, risk_free_rate: float = 0.02
) -> float:
    """计算索提诺比率 (只考虑下行波动)"""
    returns = returns.dropna()
    if returns.empty:
        return 0.0
    excess_returns = returns - risk_free_rate / 250
    downside = returns[returns < 0]
    if downside.empty or downside.std() == 0:
        return float("inf") if excess_returns.mean() > 0 else 0.0
    return float(excess_returns.mean() / downside.std() * np.sqrt(250))


def get_technical_summary(prices: pd.Series) -> dict:
    """获取技术指标汇总

    Args:
        prices: 价格序列（净值）

    Returns:
        dict: 各技术指标的当前值和信号判断
    """
    if prices.empty or len(prices) < 30:
        return {}

    current = float(prices.iloc[-1])
    summary = {"current_price": current}

    # RSI
    rsi = calculate_rsi(prices)
    current_rsi = float(rsi.iloc[-1]) if not rsi.empty else None
    if current_rsi is not None:
        summary["rsi"] = round(current_rsi, 1)
        if current_rsi > 70:
            summary["rsi_signal"] = "超买"
        elif current_rsi < 30:
            summary["rsi_signal"] = "超卖"
        else:
            summary["rsi_signal"] = "中性"

    # MACD
    macd = calculate_macd(prices)
    if not macd["dif"].empty:
        dif = float(macd["dif"].iloc[-1])
        dea = float(macd["dea"].iloc[-1])
        hist = float(macd["histogram"].iloc[-1])
        summary["macd_dif"] = round(dif, 4)
        summary["macd_dea"] = round(dea, 4)
        summary["macd_histogram"] = round(hist, 4)

        if dif > dea:
            prev_dif = float(macd["dif"].iloc[-2]) if len(macd["dif"]) > 1 else dif
            prev_dea = float(macd["dea"].iloc[-2]) if len(macd["dea"]) > 1 else dea
            if prev_dif <= prev_dea:
                summary["macd_signal"] = "金叉"
            else:
                summary["macd_signal"] = "多头"
        else:
            prev_dif = float(macd["dif"].iloc[-2]) if len(macd["dif"]) > 1 else dif
            prev_dea = float(macd["dea"].iloc[-2]) if len(macd["dea"]) > 1 else dea
            if prev_dif >= prev_dea:
                summary["macd_signal"] = "死叉"
            else:
                summary["macd_signal"] = "空头"

    # 均线
    mas = calculate_ma(prices, [5, 10, 20, 60])
    ma_values = {}
    for key, ma in mas.items():
        if not ma.empty and not np.isnan(ma.iloc[-1]):
            ma_values[key] = round(float(ma.iloc[-1]), 4)

    summary["ma"] = ma_values

    # 均线排列
    if all(k in ma_values for k in ["MA5", "MA10", "MA20", "MA60"]):
        if ma_values["MA5"] > ma_values["MA10"] > ma_values["MA20"] > ma_values["MA60"]:
            summary["ma_alignment"] = "多头排列"
        elif ma_values["MA5"] < ma_values["MA10"] < ma_values["MA20"] < ma_values["MA60"]:
            summary["ma_alignment"] = "空头排列"
        else:
            summary["ma_alignment"] = "交叉"

    # 布林带
    bb = calculate_bollinger(prices)
    if not bb["upper"].empty:
        upper = float(bb["upper"].iloc[-1])
        lower = float(bb["lower"].iloc[-1])
        middle = float(bb["middle"].iloc[-1])
        summary["bb_upper"] = round(upper, 4)
        summary["bb_middle"] = round(middle, 4)
        summary["bb_lower"] = round(lower, 4)

        if current > upper:
            summary["bb_signal"] = "突破上轨"
        elif current < lower:
            summary["bb_signal"] = "突破下轨"
        else:
            pct = (current - lower) / (upper - lower) if upper != lower else 0.5
            summary["bb_position"] = round(pct, 2)
            summary["bb_signal"] = "通道内"

    # 波动率
    vol = calculate_volatility(prices)
    if not vol.empty and not np.isnan(vol.iloc[-1]):
        summary["volatility"] = round(float(vol.iloc[-1]), 4)

    return summary
