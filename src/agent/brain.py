"""LLM 智能体核心 — 市场分析、决策推理、反思复盘

双后端: Google Gemini / Anthropic Claude，通过 .env 中 LLM_PROVIDER 切换。
LLM 基础设施 (调用/重试/回退) 在 llm.py，本模块只负责业务逻辑。
"""

import json
from datetime import datetime

from rich.console import Console

from src.agent.errors import LLMError
from src.agent.llm import (
    call_llm,
    get_analysis_model,
    get_critical_model,
    parse_json_response,
)
from src.agent.prompts import (
    get_decision_engine_system,
    get_decision_engine_template,
    get_market_analyst_system,
    get_market_analyst_template,
    get_reflection_system,
    get_reflection_template,
)
from src.agent.schemas import (
    AgentDecision,
    FundRecommendation,
    MarketAssessment,
    ReflectionResult,
)
from src.config import CONFIG

console = Console()


# ═══════════════════ 向后兼容别名 (下个版本移除) ═══════════════════

from src.agent.llm import (  # noqa: E402
    call_llm as _call_llm,
    get_analysis_model as _get_analysis_model,
    get_critical_model as _get_critical_model,
    get_decision_model as _get_decision_model,
    get_provider as _get_provider,
    get_provider_config as _get_provider_config,
    load_env as _load_env,
    parse_json_response as _parse_json_response,
)


# ═══════════════════ 业务逻辑 ═══════════════════


def analyze_market(
    regime_data: dict,
    indices: list[dict],
    fund_flow_signals: list[str],
    hotspots: list[dict] | None = None,
) -> tuple[MarketAssessment | None, int]:
    """用轻量模型摘要市场环境"""
    model = get_analysis_model()

    # 构建指数文本
    indices_lines = []
    for idx in indices:
        change = idx.get("change_pct")
        change_str = f"{change:+.2f}%" if change is not None else "-"
        indices_lines.append(f"- {idx['name']}: {idx['close']:,.2f} ({change_str})")
    indices_text = "\n".join(indices_lines) if indices_lines else "暂无数据"

    fund_flow_text = "\n".join(f"- {s}" for s in fund_flow_signals) if fund_flow_signals else "暂无数据"

    hotspot_lines = []
    if hotspots:
        for h in hotspots[:5]:
            hotspot_lines.append(
                f"- {h.get('sector_name', '')}: {h.get('hotspot_type', '')} "
                f"(热度 {h.get('score', 0):.0f})"
            )
    hotspot_text = "\n".join(hotspot_lines) if hotspot_lines else "暂无明显热点"

    # ── 增强数据收集 ──
    valuation_text = "暂无数据"
    try:
        from src.data.valuation import get_valuation_signal
        v = get_valuation_signal()
        pe_pct = v.get("pe_percentile", "?")
        valuation_text = f"{v.get('narrative', '')} (PE分位: {pe_pct}%)"
    except Exception:
        pass

    macro_text = "暂无数据"
    try:
        from src.data.macro import get_macro_snapshot
        m = get_macro_snapshot()
        credit = m.get("credit_cycle", "?")
        macro_text = f"{m.get('narrative', '')} (信贷周期: {credit})"
    except Exception:
        pass

    sentiment_text = "暂无数据"
    try:
        from src.data.sentiment import get_sentiment_snapshot
        s = get_sentiment_snapshot()
        sentiment_text = s.get("narrative", "暂无数据")
    except Exception:
        pass

    news_text = "暂无数据"
    try:
        from src.agent.news import summarize_news_for_llm
        raw_news = summarize_news_for_llm(max_items=8)
        # 移除子标题 (### )，避免与模板的 ### 财经新闻 冲突
        news_text = raw_news.replace("### ", "**").replace("\n\n", "\n") if raw_news else "暂无数据"
    except Exception:
        pass

    user_message = get_market_analyst_template().format(
        regime=regime_data.get("regime", "unknown"),
        regime_description=regime_data.get("description", ""),
        trend_score=regime_data.get("trend_score", 0),
        volatility=regime_data.get("volatility", 0),
        indices_text=indices_text,
        fund_flow_text=fund_flow_text,
        hotspot_text=hotspot_text,
        valuation_text=valuation_text,
        macro_text=macro_text,
        sentiment_text=sentiment_text,
        news_text=news_text,
    )

    try:
        text, tokens = call_llm(
            system=get_market_analyst_system(),
            user_message=user_message,
            model=model,
            max_tokens=1500,
        )
        data = parse_json_response(text)
        assessment = MarketAssessment.model_validate(data)
        return assessment, tokens
    except LLMError as e:
        console.print(f"  [red]市场分析 LLM 调用失败: {e}[/]")
        return None, 0
    except Exception as e:
        console.print(f"  [red]市场分析失败: {e}[/]")
        return None, 0


def make_decision(
    market_summary: str,
    quant_signals: list[dict],
    portfolio_state: dict,
    knowledge: list[str] | None = None,
) -> tuple[dict | None, int]:
    """用最强模型三步反思决策 (Opus 级别)

    使用 budget-aware prompt 构建，按优先级裁剪。
    """
    from src.agent.budget import PromptSection, build_prompt

    critical_model = get_critical_model()
    signal_lines = []
    for sig in quant_signals:
        category_tag = f"[{sig.get('category', 'equity')}] " if sig.get('category') else ""
        signal_lines.append(
            f"- {category_tag}{sig.get('fund_name', sig['fund_code'])} ({sig['fund_code']}): "
            f"{sig['signal_type']} | 置信度 {sig.get('confidence', 0):.0%} | "
            f"原因: {sig.get('reason', '')}"
        )
    quant_signals_text = "\n".join(signal_lines) if signal_lines else "当前无交易信号"

    # 注入资产配置上下文
    allocation_context = portfolio_state.get("allocation_context", "")
    if allocation_context:
        quant_signals_text += f"\n\n## 资产配置\n{allocation_context}"

    holdings = portfolio_state.get("holdings", [])
    if holdings:
        holding_lines = []
        for h in holdings:
            holding_lines.append(
                f"- {h.get('fund_name', h['fund_code'])} ({h['fund_code']}): "
                f"成本 {h.get('cost_price', 0):.4f}, "
                f"现价 {h.get('current_nav', 0):.4f}, "
                f"份额 {h.get('shares', 0):.2f}"
            )
        portfolio_text = "\n".join(holding_lines)
    else:
        portfolio_text = "当前空仓"

    knowledge_text = "\n".join(f"- {k}" for k in knowledge) if knowledge else "尚无历史教训积累"

    # 数据质量报告
    data_quality = portfolio_state.get("data_quality", {})
    quality_note = ""
    if data_quality:
        dq_parts = [f"{k}: {v}" for k, v in data_quality.items()]
        quality_note = f"\n\n数据可靠度: {', '.join(dq_parts)}"

    account_text = (
        f"- 总资产: {portfolio_state.get('total_value', CONFIG['initial_capital']):,.2f} RMB\n"
        f"- 现金: {portfolio_state.get('cash', CONFIG['current_cash']):,.2f} RMB\n"
        f"- 已投资: {portfolio_state.get('invested', 0):,.2f} RMB\n"
        f"- 当前回撤: {portfolio_state.get('drawdown', 0):.2%}"
    )

    # 增强上下文 (估值/宏观/情绪/新闻)
    enhanced_context = portfolio_state.get("enhanced_context", "")

    # MI 市场情报
    mi_context = portfolio_state.get("mi_context", "")

    # 按优先级构建 sections
    sections = [
        PromptSection("市场摘要", f"## 市场环境摘要\n{market_summary}", priority=1),
        PromptSection("量化信号", f"## 量化信号\n{quant_signals_text}{quality_note}", priority=1),
        PromptSection("账户状态", f"## 账户状态\n{account_text}", priority=1),
        PromptSection("持仓", f"## 当前持仓\n{portfolio_text}", priority=2),
    ]
    if enhanced_context:
        sections.append(PromptSection("增强数据", f"## 增强市场数据\n{enhanced_context}", priority=2))
    if mi_context:
        sections.append(PromptSection("市场情报", f"## Market Intelligence 研判\n{mi_context}", priority=2))
    sections.append(PromptSection("教训", f"## 历史教训\n{knowledge_text}", priority=3))
    user_message = build_prompt(sections, max_tokens=8000)
    user_message += "\n\n请按三步决策流程，给出你的投资建议。"

    try:
        text, tokens = call_llm(
            system=get_decision_engine_system(),
            user_message=user_message,
            model=critical_model,
        )
        decision = parse_json_response(text)

        # 验证 recommendations 中每个推荐
        if "recommendations" in decision and isinstance(decision["recommendations"], list):
            validated = []
            for rec in decision["recommendations"]:
                try:
                    validated_rec = FundRecommendation.model_validate(rec)
                    validated.append(validated_rec.model_dump())
                except Exception:
                    validated.append(rec)  # 验证失败仍保留原始数据
            decision["recommendations"] = validated

        return decision, tokens
    except LLMError as e:
        console.print(f"  [red]决策引擎 LLM 调用失败: {e}[/]")
        return None, 0
    except Exception as e:
        console.print(f"  [red]决策引擎失败: {e}[/]")
        return None, 0


def reflect_on_decision(
    decision_record: dict,
    actual_outcome: str,
    period: str = "7d",
) -> tuple[ReflectionResult | None, int]:
    """对过去的决策进行反思复盘"""
    user_message = get_reflection_template().format(
        decision_date=decision_record.get("decision_date", ""),
        market_context=decision_record.get("market_context", ""),
        llm_analysis=decision_record.get("llm_analysis", ""),
        llm_decision=decision_record.get("llm_decision", ""),
        confidence=decision_record.get("confidence", 0),
        quant_signals=decision_record.get("quant_signals", ""),
        period=period,
        actual_outcome=actual_outcome,
    )

    try:
        text, tokens = call_llm(
            system=get_reflection_system(),
            user_message=user_message,
        )
        data = parse_json_response(text)
        result = ReflectionResult.model_validate(data)
        return result, tokens
    except LLMError as e:
        console.print(f"  [red]反思引擎 LLM 调用失败: {e}[/]")
        return None, 0
    except Exception as e:
        console.print(f"  [red]反思引擎失败: {e}[/]")
        return None, 0


def save_agent_decision(
    decision: dict,
    market_context: str,
    quant_signals_json: str,
    model_used: str,
    tokens_used: int,
) -> int | None:
    """保存 LLM 决策到数据库"""
    from src.memory.database import get_connection

    thinking = decision.get("thinking_process", {})
    recommendations = decision.get("recommendations", [])

    conn = get_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO agent_decisions
               (decision_date, market_context, quant_signals, llm_analysis,
                llm_decision, confidence, reasoning, challenge, model_used, tokens_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now().strftime("%Y-%m-%d"),
                market_context,
                quant_signals_json,
                json.dumps(decision, ensure_ascii=False),
                json.dumps(recommendations, ensure_ascii=False),
                _avg_confidence(recommendations),
                thinking.get("final_conclusion", ""),
                thinking.get("challenge", ""),
                model_used,
                tokens_used,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        console.print(f"  [red]保存决策记录失败: {e}[/]")
        return None
    finally:
        conn.close()


def _avg_confidence(recommendations: list[dict]) -> float:
    """计算推荐列表的平均置信度"""
    if not recommendations:
        return 0.0
    confs = [r.get("confidence", 0) for r in recommendations]
    return sum(confs) / len(confs)
