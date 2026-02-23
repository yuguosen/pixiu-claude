"""多角色辩论决策 — 乐观派 vs 悲观派 vs 裁判

比单一"三步反思"更有张力：
- 角色A (乐观派): 找所有买入理由
- 角色B (悲观派): 找所有不买的理由
- 角色C (裁判): 综合 A 和 B, 给出判决
"""

import json
from rich.console import Console

from src.agent.llm import call_llm, get_analysis_model, get_critical_model, parse_json_response
from src.config import CONFIG

console = Console()

OPTIMIST_SYSTEM = """你是一位乐观的 A 股基金投资分析师。
你的任务是从当前数据中找到所有看多/买入的理由。
你要尽力说服别人现在是好的买入时机。

但你必须基于数据说话，不能无中生有。每个理由都要有数据支撑。

输出 JSON（不要输出其他内容）：
{
    "bullish_case": "你的看多论点总结",
    "key_arguments": ["论据1", "论据2", "论据3"],
    "target_funds": [{"fund_code": "代码", "reason": "为什么看好"}],
    "confidence": 0.7,
    "risks_acknowledged": ["你承认的风险"]
}"""

PESSIMIST_SYSTEM = """你是一位谨慎的 A 股基金投资分析师。
你的任务是从当前数据中找到所有看空/不买的理由。
你要尽力说服别人现在不应该买入，甚至应该减仓。

但你必须基于数据说话，不能危言耸听。每个理由都要有数据支撑。

输出 JSON（不要输出其他内容）：
{
    "bearish_case": "你的看空论点总结",
    "key_arguments": ["论据1", "论据2", "论据3"],
    "warnings": ["警告1", "警告2"],
    "confidence": 0.7,
    "opportunities_acknowledged": ["你承认的机会"]
}"""

JUDGE_SYSTEM = """你是一位资深的基金投资决策裁判。
你刚刚听完乐观派和悲观派的辩论，现在需要做出最终判决。

你的原则：
- "可以少赚，不能多亏" — 下行保护优先
- 10,000 RMB 起始资金，每一分钱都珍贵
- 倾向于谨慎但不错过明显机会
- 不偏向任何一方，只看论据质量

输出 JSON（不要输出其他内容）：
{
    "verdict": "最终判决总结",
    "side_taken": "bullish/bearish/neutral",
    "reasoning": "你的推理过程",
    "winning_arguments": ["说服你的论据"],
    "dismissed_arguments": ["你否决的论据及原因"],
    "action": "buy/sell/hold/watch",
    "confidence": 0.7,
    "position_advice": "仓位建议"
}"""


def run_debate(market_context: str) -> dict | None:
    """运行多角色辩论

    Args:
        market_context: 市场数据上下文文本

    Returns:
        辩论结果 dict 或 None
    """
    critical_model = get_critical_model()
    analysis_model = get_analysis_model()
    total_tokens = 0

    prompt = f"以下是当前市场数据，请给出你的分析：\n\n{market_context}"

    # 1. 乐观派发言 (用 Haiku 节省成本)
    console.print("  [dim]辩论: 乐观派发言中...[/]")
    try:
        optimist_text, tokens = call_llm(
            system=OPTIMIST_SYSTEM,
            user_message=prompt,
            model=analysis_model,
            max_tokens=1024,
        )
        total_tokens += tokens
        optimist = parse_json_response(optimist_text)
    except Exception as e:
        console.print(f"  [dim]乐观派失败: {e}[/]")
        return None

    # 2. 悲观派发言 (用 Haiku)
    console.print("  [dim]辩论: 悲观派发言中...[/]")
    try:
        pessimist_text, tokens = call_llm(
            system=PESSIMIST_SYSTEM,
            user_message=prompt,
            model=analysis_model,
            max_tokens=1024,
        )
        total_tokens += tokens
        pessimist = parse_json_response(pessimist_text)
    except Exception as e:
        console.print(f"  [dim]悲观派失败: {e}[/]")
        return None

    # 3. 裁判判决 (用 Opus，关键决策值得最强模型)
    console.print("  [dim]辩论: 裁判判决中...[/]")
    judge_prompt = f"""## 市场数据
{market_context}

## 乐观派论点
{json.dumps(optimist, ensure_ascii=False, indent=2)}

## 悲观派论点
{json.dumps(pessimist, ensure_ascii=False, indent=2)}

请做出你的最终判决。"""

    try:
        judge_text, tokens = call_llm(
            system=JUDGE_SYSTEM,
            user_message=judge_prompt,
            model=critical_model,
            max_tokens=2048,
        )
        total_tokens += tokens
        verdict = parse_json_response(judge_text)
    except Exception as e:
        console.print(f"  [dim]裁判失败: {e}[/]")
        return None

    console.print(f"  [dim]辩论完成 ({total_tokens} tokens)[/]")

    return {
        "optimist": optimist,
        "pessimist": pessimist,
        "verdict": verdict,
        "tokens_used": total_tokens,
    }


def format_debate_for_report(debate_result: dict) -> str:
    """将辩论结果格式化为报告段落"""
    if not debate_result:
        return ""

    sections = ["## 多角色辩论分析\n"]

    optimist = debate_result.get("optimist", {})
    if optimist:
        sections.append(f"### 乐观派 (置信度: {optimist.get('confidence', 0):.0%})")
        sections.append(f"\n{optimist.get('bullish_case', '')}\n")
        for arg in optimist.get("key_arguments", []):
            sections.append(f"- {arg}")
        sections.append("")

    pessimist = debate_result.get("pessimist", {})
    if pessimist:
        sections.append(f"### 悲观派 (置信度: {pessimist.get('confidence', 0):.0%})")
        sections.append(f"\n{pessimist.get('bearish_case', '')}\n")
        for arg in pessimist.get("key_arguments", []):
            sections.append(f"- {arg}")
        sections.append("")

    verdict = debate_result.get("verdict", {})
    if verdict:
        side = verdict.get("side_taken", "neutral")
        side_label = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}.get(side, side)
        sections.append(f"### 裁判判决: {side_label} (置信度: {verdict.get('confidence', 0):.0%})")
        sections.append(f"\n{verdict.get('verdict', '')}\n")
        sections.append(f"**推理过程**: {verdict.get('reasoning', '')}\n")
        sections.append(f"**仓位建议**: {verdict.get('position_advice', '')}\n")

    sections.append(f"*辩论消耗 {debate_result.get('tokens_used', 0)} tokens*\n")
    return "\n".join(sections)
