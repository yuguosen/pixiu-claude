"""AKShare 数据获取封装，统一错误处理和缓存"""

import hashlib
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd

from src.config import CONFIG


def _cache_path(key: str) -> Path:
    """生成缓存文件路径"""
    cache_dir = Path(CONFIG["cache_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    hashed = hashlib.md5(key.encode()).hexdigest()
    return cache_dir / f"{hashed}.json"


def _is_cache_valid(path: Path) -> bool:
    """检查缓存是否有效"""
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    ttl = timedelta(hours=CONFIG["cache_ttl_hours"])
    return datetime.now() - mtime < ttl


def _read_cache(path: Path) -> pd.DataFrame | None:
    """读取缓存"""
    if not _is_cache_valid(path):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return pd.DataFrame(data)
    except (json.JSONDecodeError, ValueError):
        return None


def _write_cache(path: Path, df: pd.DataFrame):
    """写入缓存"""
    try:
        data = df.to_dict(orient="records")
        # 处理 Timestamp 类型序列化
        for record in data:
            for k, v in record.items():
                if isinstance(v, pd.Timestamp):
                    record[k] = v.isoformat()
        path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        pass


def fetch_with_retry(func, *args, max_retries: int = 3, **kwargs) -> pd.DataFrame | None:
    """带重试的数据获取 (含限速, 防止被数据源断连)"""
    for attempt in range(max_retries):
        try:
            time.sleep(0.8)  # 限速: 防止云服务器 IP 被东方财富限流
            result = func(*args, **kwargs)
            if result is not None and not result.empty:
                return result
        except Exception as e:
            wait = 3 + 2 ** attempt  # 退避: 4s, 5s, 7s
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"获取数据失败 ({func.__name__}): {e}"
                ) from e
    return None


def fetch_with_cache(cache_key: str, params: dict, fetch_fn) -> pd.DataFrame:
    """通用缓存获取 — 先查缓存, 未命中则调用 fetch_fn

    Args:
        cache_key: 缓存标识
        params: 额外参数 (用于生成唯一 hash)
        fetch_fn: 无参数的获取函数, 返回 DataFrame
    """
    full_key = f"{cache_key}_{hash(frozenset(params.items())) if params else ''}"
    cache = _cache_path(full_key)
    cached = _read_cache(cache)
    if cached is not None and not cached.empty:
        return cached

    try:
        time.sleep(0.5)  # 限速
        df = fetch_fn()
        if df is not None and not df.empty:
            _write_cache(cache, df)
            return df
    except Exception:
        pass
    return pd.DataFrame()


def fetch_fund_nav(
    fund_code: str, start_date: str = None, end_date: str = None
) -> pd.DataFrame:
    """获取基金净值历史

    Args:
        fund_code: 基金代码，如 '110011'
        start_date: 开始日期 'YYYY-MM-DD'（不传则不限）
        end_date: 结束日期 'YYYY-MM-DD'（不传则不限）

    Returns:
        DataFrame with columns: nav_date, nav, acc_nav, daily_return
    """
    cache_key = f"fund_nav_{fund_code}_{start_date}_{end_date}"
    cache = _cache_path(cache_key)
    cached = _read_cache(cache)
    if cached is not None and not cached.empty:
        return cached

    df = fetch_with_retry(ak.fund_open_fund_info_em, symbol=fund_code, indicator="单位净值走势")
    if df is None or df.empty:
        return pd.DataFrame()

    # 标准化列名
    df = df.rename(columns={
        "净值日期": "nav_date",
        "单位净值": "nav",
        "日增长率": "daily_return",
    })

    # 确保数据类型正确
    df["nav_date"] = pd.to_datetime(df["nav_date"]).dt.strftime("%Y-%m-%d")
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")

    # 获取累计净值
    try:
        acc_df = fetch_with_retry(ak.fund_open_fund_info_em, symbol=fund_code, indicator="累计净值走势")
        if acc_df is not None and not acc_df.empty:
            acc_df = acc_df.rename(columns={"净值日期": "nav_date", "累计净值": "acc_nav"})
            acc_df["nav_date"] = pd.to_datetime(acc_df["nav_date"]).dt.strftime("%Y-%m-%d")
            acc_df["acc_nav"] = pd.to_numeric(acc_df["acc_nav"], errors="coerce")
            df = df.merge(acc_df[["nav_date", "acc_nav"]], on="nav_date", how="left")
    except Exception:
        df["acc_nav"] = None

    if "acc_nav" not in df.columns:
        df["acc_nav"] = None

    # 日期过滤
    if start_date:
        df = df[df["nav_date"] >= start_date]
    if end_date:
        df = df[df["nav_date"] <= end_date]

    df = df.sort_values("nav_date").reset_index(drop=True)
    result = df[["nav_date", "nav", "acc_nav", "daily_return"]]

    _write_cache(cache, result)
    return result


def fetch_fund_info(fund_code: str) -> dict | None:
    """获取基金基本信息

    Returns:
        dict with fund_code, fund_name, fund_type, management_company, etc.
    """
    cache_key = f"fund_info_{fund_code}"
    cache = _cache_path(cache_key)
    cached = _read_cache(cache)
    if cached is not None and not cached.empty:
        return cached.to_dict(orient="records")[0]

    try:
        # 尝试获取基金基本信息
        info = {}
        info["fund_code"] = fund_code

        # 获取基金名称和类型
        try:
            name_df = ak.fund_individual_basic_info_xq(symbol=fund_code)
            if name_df is not None and not name_df.empty:
                info_dict = dict(zip(name_df.iloc[:, 0], name_df.iloc[:, 1]))
                info["fund_name"] = info_dict.get("基金简称", info_dict.get("基金全称", f"基金{fund_code}"))
                info["fund_type"] = info_dict.get("基金类型", "")
                info["management_company"] = info_dict.get("基金管理人", "")
                info["establishment_date"] = info_dict.get("成立日期", "")
                info["benchmark"] = info_dict.get("业绩比较基准", "")
        except Exception:
            info["fund_name"] = f"基金{fund_code}"

        _write_cache(cache, pd.DataFrame([info]))
        return info

    except Exception as e:
        raise RuntimeError(f"获取基金信息失败 ({fund_code}): {e}") from e


def fetch_index_daily(
    index_code: str, start_date: str = None, end_date: str = None
) -> pd.DataFrame:
    """获取指数日线数据

    Args:
        index_code: 指数代码，如 '000300'
        start_date: 'YYYYMMDD' 格式
        end_date: 'YYYYMMDD' 格式

    Returns:
        DataFrame with columns: trade_date, open, high, low, close, volume, amount
    """
    cache_key = f"index_daily_{index_code}_{start_date}_{end_date}"
    cache = _cache_path(cache_key)
    cached = _read_cache(cache)
    if cached is not None and not cached.empty:
        return cached

    # akshare 指数日线需要 start_date 和 end_date 为 YYYYMMDD 格式
    kwargs = {"symbol": index_code, "period": "daily"}
    if start_date:
        kwargs["start_date"] = start_date.replace("-", "")
    if end_date:
        kwargs["end_date"] = end_date.replace("-", "")

    df = fetch_with_retry(ak.index_zh_a_hist, **kwargs)
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns={
        "日期": "trade_date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    })

    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("trade_date").reset_index(drop=True)
    result = df[["trade_date", "open", "high", "low", "close", "volume", "amount"]]

    _write_cache(cache, result)
    return result


def fetch_fund_ranking(fund_type: str = "全部") -> pd.DataFrame:
    """获取基金排名

    Args:
        fund_type: 基金类型筛选

    Returns:
        DataFrame with fund rankings
    """
    cache_key = f"fund_ranking_{fund_type}"
    cache = _cache_path(cache_key)
    cached = _read_cache(cache)
    if cached is not None and not cached.empty:
        return cached

    df = fetch_with_retry(ak.fund_open_fund_rank_em, symbol="全部")
    if df is None or df.empty:
        return pd.DataFrame()

    _write_cache(cache, df)
    return df
