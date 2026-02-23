"""宏观经济数据获取 — PMI/M2/社融/CPI，判断信贷周期"""

import pandas as pd
from rich.console import Console

from src.data.fetcher import fetch_with_cache, fetch_with_retry
from src.memory.database import get_connection

console = Console()


def fetch_pmi() -> pd.DataFrame:
    """获取中国制造业 PMI"""
    import akshare as ak

    def _fetch():
        return fetch_with_retry(ak.macro_china_pmi_yearly)

    df = fetch_with_cache("macro_pmi", {}, _fetch)
    if df.empty:
        return df

    # 标准化: columns = ['商品', '日期', '今值', '预测值', '前值']
    df = df.rename(columns={"日期": "date", "今值": "value"})
    if "date" not in df.columns:
        for col in df.columns:
            if "日期" in col or "date" in col.lower():
                df = df.rename(columns={col: "date"})
                break
    if "value" not in df.columns:
        for col in df.columns:
            if "今值" in col or "制造业" in col or "PMI" in col:
                df = df.rename(columns={col: "value"})
                break

    if "date" in df.columns and "value" in df.columns:
        df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce").dt.strftime("%Y-%m-%d")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["indicator"] = "pmi"
        return df[["date", "indicator", "value"]].dropna()
    return pd.DataFrame()


def fetch_money_supply() -> pd.DataFrame:
    """获取货币供应量 M2 同比增速"""
    import akshare as ak

    def _fetch():
        return fetch_with_retry(ak.macro_china_money_supply)

    df = fetch_with_cache("macro_m2", {}, _fetch)
    if df.empty:
        return df

    # M2 同比列
    m2_col = None
    for col in df.columns:
        if "M2" in col and "同比" in col:
            m2_col = col
            break
    if m2_col is None:
        for col in df.columns:
            if "M2" in col:
                m2_col = col
                break

    date_col = None
    for col in df.columns:
        if "月份" in col or "日期" in col or "date" in col.lower():
            date_col = col
            break

    if date_col and m2_col:
        result = df[[date_col, m2_col]].copy()
        result.columns = ["date", "value"]
        # 日期格式: "2026年01月份" → "2026-01-01"
        result["date"] = (
            result["date"]
            .str.replace("年", "-")
            .str.replace("月份", "-01")
            .str.replace("月", "-01")
        )
        result["date"] = pd.to_datetime(result["date"], format="%Y-%m-%d", errors="coerce").dt.strftime("%Y-%m-%d")
        result["value"] = pd.to_numeric(result["value"], errors="coerce")
        result["indicator"] = "m2_yoy"
        return result[["date", "indicator", "value"]].dropna()
    return pd.DataFrame()


def fetch_cpi() -> pd.DataFrame:
    """获取 CPI 同比数据"""
    import akshare as ak

    def _fetch():
        return fetch_with_retry(ak.macro_china_cpi_yearly)

    df = fetch_with_cache("macro_cpi", {}, _fetch)
    if df.empty:
        return df

    date_col = None
    value_col = None
    for col in df.columns:
        if "日期" in col or "date" in col.lower():
            date_col = col
        if "今值" in col or "CPI" in col or "同比" in col:
            value_col = col

    if date_col and value_col:
        result = df[[date_col, value_col]].copy()
        result.columns = ["date", "value"]
        result["date"] = pd.to_datetime(result["date"], format="%Y-%m-%d", errors="coerce").dt.strftime("%Y-%m-%d")
        result["value"] = pd.to_numeric(result["value"], errors="coerce")
        result["indicator"] = "cpi_yoy"
        return result[["date", "indicator", "value"]].dropna()
    return pd.DataFrame()


def save_macro_to_db(df: pd.DataFrame):
    """保存宏观数据到数据库"""
    if df.empty:
        return
    conn = get_connection()
    try:
        for _, row in df.iterrows():
            conn.execute(
                """INSERT OR REPLACE INTO macro_indicators
                   (indicator_name, report_date, value)
                   VALUES (?, ?, ?)""",
                (row["indicator"], row["date"], row["value"]),
            )
        conn.commit()
    finally:
        conn.close()


def update_macro_data():
    """更新所有宏观数据"""
    fetchers = [
        ("PMI", fetch_pmi),
        ("M2", fetch_money_supply),
        ("CPI", fetch_cpi),
    ]
    for name, fetcher in fetchers:
        try:
            df = fetcher()
            if not df.empty:
                save_macro_to_db(df)
                console.print(f"  [dim]宏观数据 {name}: {len(df)} 条[/]")
        except Exception as e:
            console.print(f"  [dim]宏观数据 {name} 获取失败: {e}[/]")


def get_macro_snapshot() -> dict:
    """获取最新宏观数据快照

    Returns:
        {pmi, m2_yoy, cpi_yoy, credit_cycle, narrative}
    """
    from src.memory.database import execute_query

    result = {}

    for indicator in ["pmi", "m2_yoy", "cpi_yoy"]:
        rows = execute_query(
            """SELECT value, report_date FROM macro_indicators
               WHERE indicator_name = ?
               ORDER BY report_date DESC LIMIT 3""",
            (indicator,),
        )
        if rows:
            result[indicator] = rows[0]["value"]
            if len(rows) >= 2:
                result[f"{indicator}_trend"] = "上升" if rows[0]["value"] > rows[1]["value"] else "下降"

    # 判断信贷周期
    pmi = result.get("pmi", 50)
    m2 = result.get("m2_yoy", 8)
    m2_trend = result.get("m2_yoy_trend", "持平")

    if pmi > 50 and m2_trend == "上升":
        result["credit_cycle"] = "expansion"
        result["cycle_signal"] = "偏股"
        result["narrative"] = f"PMI {pmi:.1f} (扩张) + M2 增速 {m2:.1f}% (上行)，信贷宽松期，利好权益资产"
    elif pmi > 50 and m2_trend == "下降":
        result["credit_cycle"] = "peak"
        result["cycle_signal"] = "均衡"
        result["narrative"] = f"PMI {pmi:.1f} (扩张) + M2 增速 {m2:.1f}% (回落)，经济见顶期，注意风险"
    elif pmi <= 50 and m2_trend == "下降":
        result["credit_cycle"] = "contraction"
        result["cycle_signal"] = "偏债"
        result["narrative"] = f"PMI {pmi:.1f} (收缩) + M2 增速 {m2:.1f}% (下行)，信贷紧缩期，减少权益"
    else:
        result["credit_cycle"] = "recovery"
        result["cycle_signal"] = "偏股"
        result["narrative"] = f"PMI {pmi:.1f} (收缩) + M2 增速 {m2:.1f}% (回升)，政策底信号，可左侧布局"

    return result


# ── 渐进降级 ──────────────────────────────────────────────


def _macro_from_db():
    """从数据库缓存获取宏观快照"""
    from src.memory.database import execute_query

    rows = execute_query(
        """SELECT indicator_name, value, report_date FROM macro_indicators
           ORDER BY report_date DESC LIMIT 10"""
    )
    if not rows:
        return None
    snapshot = {"credit_cycle": "unknown", "narrative": "(缓存) 宏观数据来自DB"}
    latest_date = rows[0]["report_date"]
    for r in rows:
        snapshot[r["indicator_name"]] = r["value"]
    return snapshot, latest_date


def _macro_default():
    """宏观中性默认"""
    return {
        "pmi": 50,
        "m2_yoy": 8,
        "credit_cycle": "unknown",
        "cycle_signal": "均衡",
        "narrative": "宏观数据不可用",
    }


def get_macro_snapshot_safe():
    """渐进降级获取宏观快照: API → DB → 默认"""
    from src.data.fallback import fetch_with_fallback

    return fetch_with_fallback(
        "宏观", get_macro_snapshot, _macro_from_db, _macro_default, ttl_hours=72
    )
