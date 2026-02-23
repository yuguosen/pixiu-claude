"""Market Intelligence Agent — 独立市场研判，为决策引擎提供信息增量

收集 7 个数据源 (新闻/估值/宏观/情绪/热点/市场状态/资金流向)，
调用轻量模型生成结构化市场情报，存入 analysis_log 表。

遵循 scenario.py 模式: 独立函数 + 持久化 + 格式化输出。
"""

import json
from datetime import datetime

from rich.console import Console

from src.agent.llm import call_llm, get_analysis_model, parse_json_response
from src.memory.database import execute_query, execute_write

console = Console()

INTEL_SYSTEM = """你是一位资深 A 股市场情报分析师。你的任务是综合多维数据源，生成独立的市场研判报告。

你的分析框架：
- 从政策、宏观、估值、情绪、行业五个维度提炼信号方向
- 识别各维度之间的矛盾和共振
- 关注风险预警和潜在机会
- 给出资产配置方向性建议

输出 JSON（不要输出其他内容）：
{
    "market_regime_view": "你对当前市场状态的独立判断",
    "confidence": 0.7,
    "key_narrative": "一段话核心叙事",
    "signal_dimensions": {
        "policy_signal": {"direction": "+/-/=", "summary": "政策面判断", "strength": "strong/moderate/weak"},
        "macro_signal": {"direction": "+/-/=", "summary": "宏观面判断", "strength": "strong/moderate/weak"},
        "valuation_signal": {"direction": "+/-/=", "summary": "估值面判断", "strength": "strong/moderate/weak"},
        "sentiment_signal": {"direction": "+/-/=", "summary": "情绪面判断", "strength": "strong/moderate/weak"},
        "sector_signal": {"direction": "+/-/=", "summary": "行业面判断", "strength": "strong/moderate/weak"}
    },
    "contradictions": ["矛盾点1", "矛盾点2"],
    "risk_alerts": ["风险预警1"],
    "opportunity_alerts": ["机会提示1"],
    "actionable_suggestion": "一句话操作建议",
    "asset_allocation_hint": {
        "equity_bias": "increase/decrease/maintain",
        "bond_bias": "increase/decrease/maintain",
        "cash_bias": "increase/decrease/maintain"
    }
}"""


def build_intel_context() -> str:
    """收集 7 个数据源，拼接为完整上下文

    Returns:
        格式化的市场数据上下文文本
    """
    parts = []

    # 1. 财经新闻
    try:
        from src.agent.news import summarize_news_for_llm
        news = summarize_news_for_llm(max_items=8)
        if news and news != "暂无最新新闻数据":
            parts.append(f"## 新闻资讯\n{news}")
    except Exception:
        pass

    # 2. 估值快照
    try:
        from src.data.valuation import get_valuation_snapshot
        snapshot = get_valuation_snapshot()
        if snapshot:
            lines = ["## 估值数据"]
            for code, data in snapshot.items():
                name = data.get("name", code)
                pe_pct = data.get("pe_percentile", "?")
                pb_pct = data.get("pb_percentile", "?")
                signal = data.get("signal", "")
                lines.append(f"- {name}: PE分位 {pe_pct}%, PB分位 {pb_pct}% — {signal}")
            parts.append("\n".join(lines))
    except Exception:
        pass

    # 3. 宏观经济
    try:
        from src.data.macro import get_macro_snapshot
        m = get_macro_snapshot()
        if m:
            macro_lines = [
                "## 宏观经济",
                f"- PMI: {m.get('pmi', '?')}",
                f"- M2同比: {m.get('m2_yoy', '?')}%",
                f"- CPI同比: {m.get('cpi_yoy', '?')}%",
                f"- 信贷周期: {m.get('credit_cycle', '?')}",
                f"- 判断: {m.get('narrative', '')}",
            ]
            parts.append("\n".join(macro_lines))
    except Exception:
        pass

    # 4. 市场情绪
    try:
        from src.data.sentiment import get_sentiment_snapshot
        s = get_sentiment_snapshot()
        if s:
            sent_lines = [
                "## 市场情绪",
                f"- 情绪水平: {s.get('level', '?')}",
                f"- 情绪得分: {s.get('score', 50):.0f}/100",
                f"- 融资分位: {s.get('percentile', 50):.0f}%",
                f"- 判断: {s.get('narrative', '')}",
            ]
            parts.append("\n".join(sent_lines))
    except Exception:
        pass

    # 5. 行业热点
    try:
        hotspots = execute_query(
            "SELECT sector_name, hotspot_type, score FROM hotspots "
            "WHERE status = 'active' ORDER BY score DESC LIMIT 8"
        )
        if hotspots:
            lines = ["## 行业热点"]
            for h in hotspots:
                lines.append(f"- {h['sector_name']}: {h['hotspot_type']} (热度 {h['score']:.0f})")
            parts.append("\n".join(lines))
    except Exception:
        pass

    # 6. 市场状态
    try:
        from src.analysis.market_regime import detect_market_regime
        regime = detect_market_regime()
        if regime:
            parts.append(
                f"## 市场状态\n"
                f"- 状态: {regime['regime']} — {regime.get('description', '')}\n"
                f"- 趋势得分: {regime.get('trend_score', 0):.1f}\n"
                f"- 波动率: {regime.get('volatility', 0):.2%}"
            )
    except Exception:
        pass

    # 7. 资金流向
    try:
        from src.analysis.fund_flow import get_fund_flow_composite
        flow = get_fund_flow_composite()
        signals = flow.get("signals", [])
        if signals:
            lines = ["## 资金流向"]
            for sig in signals[:5]:
                lines.append(f"- {sig}")
            parts.append("\n".join(lines))
    except Exception:
        pass

    return "\n\n".join(parts) if parts else "市场数据收集中，暂无足够数据"


def run_market_intel(market_context: str | None = None) -> dict | None:
    """运行 Market Intelligence 分析

    Args:
        market_context: 可选的预构建上下文，为 None 时自动收集

    Returns:
        结构化情报结果 dict 或 None
    """
    model = get_analysis_model()

    if market_context is None:
        market_context = build_intel_context()

    prompt = f"""以下是当前市场的多维数据，请进行综合研判：

{market_context}

请从政策、宏观、估值、情绪、行业五个维度分析，识别矛盾和共振，给出资产配置方向建议。"""

    try:
        text, tokens = call_llm(
            system=INTEL_SYSTEM,
            user_message=prompt,
            model=model,
            max_tokens=2048,
        )
        result = parse_json_response(text)
        result["tokens_used"] = tokens
        result["analysis_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        console.print(
            f"  [dim]MI 完成 ({tokens} tokens), "
            f"判断: {result.get('market_regime_view', '?')}, "
            f"置信度: {result.get('confidence', 0):.0%}[/]"
        )

        # 持久化到 analysis_log
        _save_intel(result, model)

        return result

    except Exception as e:
        console.print(f"  [dim]Market Intelligence 失败: {e}[/]")
        return None


def _save_intel(result: dict, model_used: str):
    """保存 MI 结果到 analysis_log 表"""
    try:
        execute_write(
            """INSERT INTO analysis_log
               (analysis_date, analysis_type, summary, details_json)
               VALUES (?, 'market_intel', ?, ?)""",
            (
                datetime.now().strftime("%Y-%m-%d"),
                result.get("key_narrative", "")[:500],
                json.dumps(result, ensure_ascii=False),
            ),
        )
    except Exception:
        pass


def get_latest_intel(today_only: bool = True) -> dict | None:
    """获取最近一条 MI 结果

    Args:
        today_only: 为 True 时只返回当日结果，避免注入过时情报

    Returns:
        解析后的 dict 或 None
    """
    if today_only:
        rows = execute_query(
            """SELECT details_json, analysis_date FROM analysis_log
               WHERE analysis_type = 'market_intel' AND analysis_date = ?
               ORDER BY created_at DESC LIMIT 1""",
            (datetime.now().strftime("%Y-%m-%d"),),
        )
    else:
        rows = execute_query(
            """SELECT details_json, analysis_date FROM analysis_log
               WHERE analysis_type = 'market_intel'
               ORDER BY created_at DESC LIMIT 1"""
        )
    if not rows or not rows[0].get("details_json"):
        return None
    try:
        return json.loads(rows[0]["details_json"])
    except (json.JSONDecodeError, TypeError):
        return None


def format_intel_for_report(result: dict) -> str:
    """将 MI 结果格式化为完整 Markdown 报告"""
    if not result:
        return ""

    sections = [
        f"## Market Intelligence 市场情报\n",
        f"**市场判断**: {result.get('market_regime_view', '?')}",
        f"**置信度**: {result.get('confidence', 0):.0%}",
        f"**核心叙事**: {result.get('key_narrative', '')}\n",
    ]

    # 五维信号
    dims = result.get("signal_dimensions", {})
    if dims:
        sections.append("### 五维信号")
        DIM_NAMES = {
            "policy_signal": "政策面",
            "macro_signal": "宏观面",
            "valuation_signal": "估值面",
            "sentiment_signal": "情绪面",
            "sector_signal": "行业面",
        }
        for key, label in DIM_NAMES.items():
            d = dims.get(key, {})
            direction = d.get("direction", "=")
            direction_icon = {"+" : "↑", "-": "↓", "=": "→"}.get(direction, "→")
            sections.append(
                f"- {label} {direction_icon} ({d.get('strength', '?')}): {d.get('summary', '')}"
            )
        sections.append("")

    # 矛盾点
    contradictions = result.get("contradictions", [])
    if contradictions:
        sections.append("### 矛盾与冲突")
        for c in contradictions:
            sections.append(f"- {c}")
        sections.append("")

    # 风险与机会
    risks = result.get("risk_alerts", [])
    if risks:
        sections.append("### 风险预警")
        for r in risks:
            sections.append(f"- {r}")
        sections.append("")

    opps = result.get("opportunity_alerts", [])
    if opps:
        sections.append("### 机会提示")
        for o in opps:
            sections.append(f"- {o}")
        sections.append("")

    # 操作建议
    suggestion = result.get("actionable_suggestion", "")
    if suggestion:
        sections.append(f"**操作建议**: {suggestion}\n")

    # 配置方向
    hint = result.get("asset_allocation_hint", {})
    if hint:
        BIAS_MAP = {"increase": "加配", "decrease": "减配", "maintain": "维持"}
        sections.append("### 配置方向")
        sections.append(
            f"- 权益: {BIAS_MAP.get(hint.get('equity_bias', 'maintain'), '维持')} | "
            f"债券: {BIAS_MAP.get(hint.get('bond_bias', 'maintain'), '维持')} | "
            f"现金: {BIAS_MAP.get(hint.get('cash_bias', 'maintain'), '维持')}"
        )

    tokens = result.get("tokens_used", 0)
    if tokens:
        sections.append(f"\n[dim]({tokens} tokens)[/]")

    return "\n".join(sections)


def format_intel_for_decision(result: dict) -> str:
    """将 MI 结果精简为决策引擎消费的文本 (控制 token)"""
    if not result:
        return ""

    parts = [
        f"市场判断: {result.get('market_regime_view', '?')} (置信度 {result.get('confidence', 0):.0%})",
        f"核心叙事: {result.get('key_narrative', '')}",
    ]

    # 五维信号精简
    dims = result.get("signal_dimensions", {})
    if dims:
        dim_parts = []
        DIM_SHORT = {
            "policy_signal": "政策",
            "macro_signal": "宏观",
            "valuation_signal": "估值",
            "sentiment_signal": "情绪",
            "sector_signal": "行业",
        }
        for key, label in DIM_SHORT.items():
            d = dims.get(key, {})
            dim_parts.append(f"{label}{d.get('direction', '=')}")
        parts.append(f"信号: {' | '.join(dim_parts)}")

    # 矛盾点
    contradictions = result.get("contradictions", [])
    if contradictions:
        parts.append(f"矛盾: {'; '.join(contradictions[:2])}")

    # 风险
    risks = result.get("risk_alerts", [])
    if risks:
        parts.append(f"风险: {'; '.join(risks[:2])}")

    # 配置方向
    hint = result.get("asset_allocation_hint", {})
    if hint:
        parts.append(
            f"配置方向: 权益{hint.get('equity_bias', 'maintain')} "
            f"债券{hint.get('bond_bias', 'maintain')} "
            f"现金{hint.get('cash_bias', 'maintain')}"
        )

    suggestion = result.get("actionable_suggestion", "")
    if suggestion:
        parts.append(f"建议: {suggestion}")

    return "\n".join(parts)
