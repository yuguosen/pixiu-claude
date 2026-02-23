"""市场情绪指标 — 融资余额/换手率等，极端值是最好的反向指标"""

import pandas as pd
from rich.console import Console

from src.data.fetcher import fetch_with_cache, fetch_with_retry
from src.memory.database import get_connection

console = Console()


def fetch_margin_data() -> pd.DataFrame:
    """获取两市融资融券余额数据"""
    import akshare as ak

    def _fetch():
        return fetch_with_retry(ak.stock_margin_sse, start_date="20200101")

    df = fetch_with_cache("margin_sse", {}, _fetch)
    if df.empty:
        return df

    # 找到日期和融资余额列
    date_col = None
    balance_col = None
    for col in df.columns:
        if "日期" in col or "信用交易日期" in col:
            date_col = col
        if "融资余额" in col and "融券" not in col:
            balance_col = col

    if date_col and balance_col:
        result = df[[date_col, balance_col]].copy()
        result.columns = ["date", "value"]
        result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        result["value"] = pd.to_numeric(result["value"], errors="coerce")
        result = result.dropna()
        return result.sort_values("date").reset_index(drop=True)

    return pd.DataFrame()


def calculate_sentiment_score(margin_df: pd.DataFrame) -> dict:
    """基于融资数据计算情绪得分

    Returns:
        {score: 0-100, level, percentile, trend, narrative}
    """
    if margin_df.empty or len(margin_df) < 60:
        return {
            "score": 50,
            "level": "neutral",
            "narrative": "情绪数据不足",
        }

    current = float(margin_df["value"].iloc[-1])
    values = margin_df["value"]

    # 当前在历史中的分位
    percentile = float((values < current).sum() / len(values) * 100)

    # 近 20 日趋势
    recent = values.tail(20)
    ma5 = recent.tail(5).mean()
    ma20 = recent.mean()
    trend = "上升" if ma5 > ma20 else "下降"

    # 得分
    score = percentile

    # 判断极端情绪
    if percentile > 90:
        level = "极度贪婪"
        signal = "强烈看空"
    elif percentile > 75:
        level = "贪婪"
        signal = "谨慎"
    elif percentile < 10:
        level = "极度恐惧"
        signal = "强烈看多"
    elif percentile < 25:
        level = "恐惧"
        signal = "积极"
    else:
        level = "中性"
        signal = "正常"

    return {
        "score": round(score, 1),
        "level": level,
        "signal": signal,
        "percentile": round(percentile, 1),
        "trend": trend,
        "margin_balance": current,
        "narrative": f"融资余额分位 {percentile:.0f}% ({level})，趋势{trend}。{signal}信号。",
    }


def save_sentiment_to_db(data: dict):
    """保存情绪数据到数据库"""
    from datetime import datetime

    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO sentiment_indicators
               (indicator_name, trade_date, value, percentile)
               VALUES (?, ?, ?, ?)""",
            (
                "margin_balance",
                datetime.now().strftime("%Y-%m-%d"),
                data.get("margin_balance"),
                data.get("percentile"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_sentiment_snapshot() -> dict:
    """获取完整情绪快照"""
    try:
        margin_df = fetch_margin_data()
        sentiment = calculate_sentiment_score(margin_df)
        save_sentiment_to_db(sentiment)
        return sentiment
    except Exception as e:
        console.print(f"  [dim]情绪数据获取失败: {e}[/]")
        return {"score": 50, "level": "neutral", "narrative": "情绪数据不可用"}


# ── 渐进降级 ──────────────────────────────────────────────


def _sentiment_from_db():
    """从数据库缓存获取情绪"""
    from src.memory.database import execute_query

    rows = execute_query(
        """SELECT value, percentile, trade_date FROM sentiment_indicators
           WHERE indicator_name='margin_balance'
           ORDER BY trade_date DESC LIMIT 1"""
    )
    if not rows:
        return None
    r = rows[0]
    pct = r["percentile"] or 50
    snapshot = {
        "score": pct,
        "level": "neutral",
        "percentile": pct,
        "margin_balance": r["value"],
        "narrative": f"(缓存) 融资余额分位 {pct:.0f}%",
    }
    return snapshot, r["trade_date"]


def _sentiment_default():
    """情绪中性默认"""
    return {"score": 50, "level": "neutral", "narrative": "情绪数据不可用"}


def get_sentiment_snapshot_safe():
    """渐进降级获取情绪快照: API → DB → 默认"""
    from src.data.fallback import fetch_with_fallback

    return fetch_with_fallback(
        "情绪", get_sentiment_snapshot, _sentiment_from_db, _sentiment_default, ttl_hours=24
    )
