"""东方财富/新浪直接 HTTP 数据获取 — 替代 AKShare 中不稳定的接口

在阿里云服务器上，AKShare 的 push2*.eastmoney.com 系列 API 全部被拦截。
本模块直接调用可用的 HTTP 端点，作为稳定的数据源。

数据源:
- 指数日线: 新浪财经 money.finance.sina.com.cn
- 板块实时: AKShare 同花顺接口 (已验证可用)
"""

import logging
import time

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# 新浪指数代码映射 (指数代码 → 新浪格式)
SINA_INDEX_MAP = {
    "000001": "sh000001",  # 上证指数
    "399001": "sz399001",  # 深证成指
    "399006": "sz399006",  # 创业板指
    "000300": "sh000300",  # 沪深300
    "000905": "sh000905",  # 中证500
    "000852": "sh000852",  # 中证1000
}

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
})


def sina_index_hist(
    symbol: str,
    datalen: int = 1000,
) -> pd.DataFrame:
    """从新浪财经获取指数日 K 线数据

    Args:
        symbol: 指数代码, 如 '000300'
        datalen: 获取天数, 最大约 1000

    Returns:
        DataFrame: trade_date, open, high, low, close, volume, amount
    """
    sina_symbol = SINA_INDEX_MAP.get(symbol)
    if not sina_symbol:
        # 尝试自动推断: 0/3 开头为深市, 其他为沪市
        prefix = "sz" if symbol.startswith(("0", "3")) and not symbol.startswith("000") else "sh"
        # 特殊处理: 000 开头但不是上证指数的情况
        if symbol.startswith("399"):
            prefix = "sz"
        else:
            prefix = "sh"
        sina_symbol = f"{prefix}{symbol}"

    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": sina_symbol,
        "scale": "240",  # 日线 (240分钟)
        "ma": "no",
        "datalen": str(datalen),
    }

    try:
        time.sleep(0.5)  # 限速
        resp = _session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if not data:
            logger.warning("新浪指数 %s 返回空数据", symbol)
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df = df.rename(columns={
            "day": "trade_date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        })

        # 新浪没有成交额, 留空
        if "amount" not in df.columns:
            df["amount"] = 0

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # trade_date 格式: "2026-04-17" (新浪原生就是这个格式)
        df = df.sort_values("trade_date").reset_index(drop=True)
        return df[["trade_date", "open", "high", "low", "close", "volume", "amount"]]

    except Exception as e:
        logger.warning("新浪指数 %s 获取失败: %s", symbol, e)
        return pd.DataFrame()


def ths_board_industry_list() -> pd.DataFrame:
    """获取同花顺行业板块实时行情 (通过 AKShare)

    列名已对齐东方财富格式，方便替换使用。

    Returns:
        DataFrame: 板块名称, 涨跌幅, 总成交量, 总成交额, 净流入, ...
    """
    try:
        import akshare as ak
        time.sleep(0.8)
        df = ak.stock_board_industry_summary_ths()
        if df is None or df.empty:
            return pd.DataFrame()
        # 列名映射: 对齐东方财富格式 (调用方 sector_rotation.py 使用 EM 列名)
        rename_map = {
            "板块": "板块名称",
            "总成交量": "成交量",
            "总成交额": "成交额",
        }
        df = df.rename(columns=rename_map)
        # THS 没有 "板块代码" 和 "最新价"/"换手率", 添加占位
        if "板块代码" not in df.columns:
            df["板块代码"] = ""
        if "最新价" not in df.columns:
            df["最新价"] = None
        if "换手率" not in df.columns:
            df["换手率"] = None
        return df
    except Exception as e:
        logger.warning("同花顺板块列表获取失败: %s", e)
        return pd.DataFrame()


def ths_board_concept_list() -> pd.DataFrame:
    """获取同花顺概念板块列表 (通过 AKShare)

    Returns:
        DataFrame: name, code
    """
    try:
        import akshare as ak
        time.sleep(0.8)
        df = ak.stock_board_concept_name_ths()
        return df
    except Exception as e:
        logger.warning("同花顺概念板块获取失败: %s", e)
        return pd.DataFrame()
