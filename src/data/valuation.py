"""估值数据获取 — PE/PB 历史分位数，A 股最有效的择时指标

数据源: AKShare stock_index_pe_lg / stock_index_pb_lg (乐咕数据)
列名: 日期, 滚动市盈率(TTM PE), 市净率
"""

import pandas as pd
from rich.console import Console

from src.data.fetcher import fetch_with_cache, fetch_with_retry
from src.memory.database import get_connection

console = Console()

# 主要宽基指数 — 使用中文名 (乐咕数据源要求)
VALUATION_INDICES = {
    "000300": "沪深300",
    "000905": "中证500",
    "000852": "中证1000",
    "000016": "上证50",
}


def fetch_index_valuation(index_name: str = "沪深300") -> pd.DataFrame:
    """获取指数历史估值数据 (PE/PB)

    使用 stock_index_pe_lg / stock_index_pb_lg (乐咕数据)。
    PE 取"滚动市盈率"(TTM)，PB 取"市净率"。

    Returns:
        DataFrame: date, pe, pb
    """
    import akshare as ak

    def _fetch_pe():
        return fetch_with_retry(
            ak.stock_index_pe_lg,
            symbol=index_name,
        )

    pe_df = fetch_with_cache(
        f"valuation_pe_{index_name}", {}, _fetch_pe
    )

    def _fetch_pb():
        return fetch_with_retry(
            ak.stock_index_pb_lg,
            symbol=index_name,
        )

    pb_df = fetch_with_cache(
        f"valuation_pb_{index_name}", {}, _fetch_pb
    )

    result = pd.DataFrame()

    if pe_df is not None and not pe_df.empty:
        pe_df = pe_df.rename(columns={"日期": "date", "滚动市盈率": "pe"})
        pe_df["date"] = pd.to_datetime(pe_df["date"]).dt.strftime("%Y-%m-%d")
        pe_df["pe"] = pd.to_numeric(pe_df["pe"], errors="coerce")
        result = pe_df[["date", "pe"]].dropna()

    if pb_df is not None and not pb_df.empty:
        pb_df = pb_df.rename(columns={"日期": "date", "市净率": "pb"})
        pb_df["date"] = pd.to_datetime(pb_df["date"]).dt.strftime("%Y-%m-%d")
        pb_df["pb"] = pd.to_numeric(pb_df["pb"], errors="coerce")
        if result.empty:
            result = pb_df[["date", "pb"]].dropna()
        else:
            result = result.merge(pb_df[["date", "pb"]], on="date", how="outer")

    return result.sort_values("date").reset_index(drop=True)


def calculate_percentile(series: pd.Series) -> float:
    """计算当前值在历史中的分位数 (0-100)"""
    if series.empty or series.isna().all():
        return 50.0
    current = series.iloc[-1]
    if pd.isna(current):
        return 50.0
    return float((series.dropna() < current).sum() / series.dropna().count() * 100)


def get_valuation_snapshot() -> dict:
    """获取所有主要指数的当前估值分位

    Returns:
        {index_code: {name, pe, pb, pe_percentile, pb_percentile, signal}}
    """
    result = {}

    for index_code, index_name in VALUATION_INDICES.items():
        try:
            df = fetch_index_valuation(index_name)
            if df.empty:
                continue

            entry = {"name": index_name, "index_code": index_code}

            if "pe" in df.columns:
                pe_series = df["pe"].dropna()
                if not pe_series.empty:
                    entry["pe"] = round(float(pe_series.iloc[-1]), 2)
                    entry["pe_percentile"] = round(calculate_percentile(pe_series), 1)

            if "pb" in df.columns:
                pb_series = df["pb"].dropna()
                if not pb_series.empty:
                    entry["pb"] = round(float(pb_series.iloc[-1]), 2)
                    entry["pb_percentile"] = round(calculate_percentile(pb_series), 1)

            # 综合信号
            pe_pct = entry.get("pe_percentile", 50)
            pb_pct = entry.get("pb_percentile", 50)
            avg_pct = (pe_pct + pb_pct) / 2

            if avg_pct < 20:
                entry["signal"] = "极度低估"
                entry["action"] = "积极买入"
            elif avg_pct < 30:
                entry["signal"] = "低估"
                entry["action"] = "加大定投"
            elif avg_pct < 50:
                entry["signal"] = "适中偏低"
                entry["action"] = "正常定投"
            elif avg_pct < 70:
                entry["signal"] = "适中偏高"
                entry["action"] = "减少定投"
            elif avg_pct < 80:
                entry["signal"] = "高估"
                entry["action"] = "停止买入"
            else:
                entry["signal"] = "极度高估"
                entry["action"] = "逐步减仓"

            result[index_code] = entry

        except Exception as e:
            console.print(f"  [dim]估值获取失败 {index_name}: {e}[/]")

    return result


def save_valuation_to_db(snapshot: dict):
    """保存估值数据到数据库"""
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        for index_code, data in snapshot.items():
            conn.execute(
                """INSERT OR REPLACE INTO index_valuation
                   (index_code, trade_date, pe, pb, pe_percentile, pb_percentile)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    index_code,
                    today,
                    data.get("pe"),
                    data.get("pb"),
                    data.get("pe_percentile"),
                    data.get("pb_percentile"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_valuation_signal() -> dict:
    """获取估值驱动的整体信号

    Returns:
        {regime_modifier, position_multiplier, narrative}
    """
    snapshot = get_valuation_snapshot()
    if not snapshot:
        return {"regime_modifier": 0, "position_multiplier": 1.0, "narrative": "估值数据不可用"}

    # 以沪深300 为主要参考
    csi300 = snapshot.get("000300", {})
    pe_pct = csi300.get("pe_percentile", 50)

    if pe_pct < 20:
        return {
            "regime_modifier": 2,
            "position_multiplier": 1.5,
            "pe_percentile": pe_pct,
            "narrative": f"沪深300 PE 分位 {pe_pct:.0f}%，处于历史极低区域，是最佳建仓时机",
        }
    elif pe_pct < 30:
        return {
            "regime_modifier": 1,
            "position_multiplier": 1.3,
            "pe_percentile": pe_pct,
            "narrative": f"沪深300 PE 分位 {pe_pct:.0f}%，低估区域，适合加大投入",
        }
    elif pe_pct < 70:
        return {
            "regime_modifier": 0,
            "position_multiplier": 1.0,
            "pe_percentile": pe_pct,
            "narrative": f"沪深300 PE 分位 {pe_pct:.0f}%，估值中性",
        }
    elif pe_pct < 80:
        return {
            "regime_modifier": -1,
            "position_multiplier": 0.6,
            "pe_percentile": pe_pct,
            "narrative": f"沪深300 PE 分位 {pe_pct:.0f}%，高估区域，应减少投入",
        }
    else:
        return {
            "regime_modifier": -2,
            "position_multiplier": 0.3,
            "pe_percentile": pe_pct,
            "narrative": f"沪深300 PE 分位 {pe_pct:.0f}%，极度高估，应逐步撤退",
        }


# ── 渐进降级 ──────────────────────────────────────────────


def _valuation_from_db():
    """从数据库缓存获取估值"""
    from src.memory.database import execute_query

    rows = execute_query(
        """SELECT pe_percentile, trade_date FROM index_valuation
           WHERE index_code='000300' ORDER BY trade_date DESC LIMIT 1"""
    )
    if not rows:
        return None
    r = rows[0]
    pe_pct = r["pe_percentile"] or 50
    signal = {
        "pe_percentile": pe_pct,
        "regime_modifier": 0,
        "position_multiplier": 1.0,
        "narrative": f"(缓存) PE分位 {pe_pct:.0f}%",
    }
    return signal, r["trade_date"]


def _valuation_default():
    """估值中性默认"""
    return {
        "pe_percentile": 50,
        "regime_modifier": 0,
        "position_multiplier": 1.0,
        "narrative": "估值数据不可用",
    }


def get_valuation_signal_safe():
    """渐进降级获取估值信号: API → DB → 默认"""
    from src.data.fallback import fetch_with_fallback

    return fetch_with_fallback(
        "估值", get_valuation_signal, _valuation_from_db, _valuation_default, ttl_hours=24
    )
