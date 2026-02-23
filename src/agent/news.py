"""新闻/政策信息获取 — 让 LLM 有真实信息增量"""

import pandas as pd
from rich.console import Console

from src.data.fetcher import fetch_with_cache, fetch_with_retry

console = Console()


def fetch_financial_news(limit: int = 20) -> list[dict]:
    """获取财经新闻

    Returns:
        [{title, content, datetime, source}, ...]
    """
    import akshare as ak

    try:
        def _fetch():
            return fetch_with_retry(ak.stock_news_em, symbol="财经")

        df = fetch_with_cache("fin_news", {}, _fetch)
        if df.empty:
            return []

        news = []
        for _, row in df.head(limit).iterrows():
            entry = {}
            for col in df.columns:
                if "标题" in col or "新闻标题" in col:
                    entry["title"] = str(row[col])
                elif "内容" in col or "新闻内容" in col:
                    entry["content"] = str(row[col])[:500]
                elif "时间" in col or "发布时间" in col:
                    entry["datetime"] = str(row[col])

            if entry.get("title"):
                news.append(entry)

        return news

    except Exception as e:
        console.print(f"  [dim]新闻获取失败: {e}[/]")
        return []


def fetch_market_headlines() -> list[dict]:
    """获取市场要闻 (更精简的版本)"""
    import akshare as ak

    try:
        def _fetch():
            return fetch_with_retry(ak.stock_info_global_em)

        df = fetch_with_cache("global_headlines", {}, _fetch)
        if df.empty:
            return []

        headlines = []
        for _, row in df.head(15).iterrows():
            entry = {}
            for col in df.columns:
                if "标题" in col or "名称" in col:
                    entry["title"] = str(row[col])
                elif "内容" in col:
                    entry["summary"] = str(row[col])[:300]

            if entry.get("title"):
                headlines.append(entry)

        return headlines

    except Exception:
        return []


def summarize_news_for_llm(max_items: int = 10) -> str:
    """将新闻整理成适合 LLM 消费的文本

    Returns:
        格式化的新闻摘要文本
    """
    news = fetch_financial_news(limit=max_items)
    headlines = fetch_market_headlines()

    sections = []

    if headlines:
        sections.append("### 全球市场要闻")
        for h in headlines[:5]:
            sections.append(f"- {h.get('title', '')}")

    if news:
        sections.append("\n### 国内财经新闻")
        for n in news[:max_items]:
            title = n.get("title", "")
            time = n.get("datetime", "")
            sections.append(f"- [{time}] {title}")

    if not sections:
        return "暂无最新新闻数据"

    return "\n".join(sections)
