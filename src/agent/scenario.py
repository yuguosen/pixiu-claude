"""场景推演 — 不做单点预测，做概率分布

让 LLM 生成三种情景：
- 乐观 (概率 P1): 如果发生 X, 预期收益 Y
- 基准 (概率 P2): 最可能的走势
- 悲观 (概率 P3): 如果发生 Z, 最大亏损 W

决策基于期望值，不是单点预测。
"""

import json
from datetime import datetime

from rich.console import Console

from src.agent.llm import call_llm, get_decision_model, parse_json_response
from src.config import CONFIG
from src.memory.database import get_connection

console = Console()

SCENARIO_SYSTEM = """你是一位专业的 A 股基金市场场景分析师。
你的任务是基于当前市场数据，生成未来 1-3 个月的三种情景。

要求：
- 三种情景的概率之和必须为 1.0
- 每个情景必须有明确的触发条件和预期收益
- 悲观情景的概率不得低于 15%（永远要考虑最坏情况）
- 收益预估要基于历史类似情景

输出 JSON（不要输出其他内容）：
{
    "analysis_horizon": "1-3个月",
    "scenarios": {
        "bullish": {
            "probability": 0.30,
            "triggers": ["触发条件1", "触发条件2"],
            "expected_return": 8.0,
            "description": "乐观情景描述",
            "key_indicators": ["需要关注的指标"]
        },
        "base": {
            "probability": 0.50,
            "triggers": ["基准假设1"],
            "expected_return": 2.0,
            "description": "基准情景描述",
            "key_indicators": ["需要关注的指标"]
        },
        "bearish": {
            "probability": 0.20,
            "triggers": ["风险因素1", "风险因素2"],
            "expected_return": -10.0,
            "description": "悲观情景描述",
            "key_indicators": ["需要关注的指标"]
        }
    },
    "expected_value": 1.6,
    "recommendation": "基于期望值的操作建议",
    "risk_reward_ratio": "风险收益比分析"
}"""


def run_scenario_analysis(market_context: str) -> dict | None:
    """运行场景推演

    Args:
        market_context: 市场数据上下文

    Returns:
        场景分析结果 dict 或 None
    """
    model = get_decision_model()

    prompt = f"""以下是当前市场的完整数据，请生成三种情景分析：

{market_context}

请特别注意：
- 估值分位数据是否处于极端位置
- 宏观指标的趋势方向
- 市场情绪是否过热或过冷
- 资金面的流入流出方向"""

    try:
        text, tokens = call_llm(
            system=SCENARIO_SYSTEM,
            user_message=prompt,
            model=model,
            max_tokens=2048,
        )
        result = parse_json_response(text)

        # 计算期望值 (如果 LLM 没计算)
        scenarios = result.get("scenarios", {})
        if "expected_value" not in result and scenarios:
            ev = sum(
                s.get("probability", 0) * s.get("expected_return", 0)
                for s in scenarios.values()
            )
            result["expected_value"] = round(ev, 2)

        result["tokens_used"] = tokens
        console.print(f"  [dim]场景推演完成 ({tokens} tokens), 期望收益: {result.get('expected_value', 0):+.1f}%[/]")

        # 保存到数据库
        _save_scenario(result, model)

        return result

    except Exception as e:
        console.print(f"  [dim]场景推演失败: {e}[/]")
        return None


def _save_scenario(result: dict, model_used: str):
    """保存场景分析到数据库"""
    scenarios = result.get("scenarios", {})
    bullish = scenarios.get("bullish", {})
    base = scenarios.get("base", {})
    bearish = scenarios.get("bearish", {})

    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO scenario_analysis
               (analysis_date, bullish_scenario, bullish_probability,
                base_scenario, base_probability,
                bearish_scenario, bearish_probability,
                expected_return, model_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now().strftime("%Y-%m-%d"),
                json.dumps(bullish, ensure_ascii=False),
                bullish.get("probability"),
                json.dumps(base, ensure_ascii=False),
                base.get("probability"),
                json.dumps(bearish, ensure_ascii=False),
                bearish.get("probability"),
                result.get("expected_value"),
                model_used,
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def format_scenario_for_report(result: dict) -> str:
    """将场景推演结果格式化为报告段落"""
    if not result:
        return ""

    sections = ["## 场景推演\n"]
    scenarios = result.get("scenarios", {})

    for label, key, emoji in [("乐观", "bullish", "+"), ("基准", "base", "="), ("悲观", "bearish", "-")]:
        s = scenarios.get(key, {})
        if s:
            prob = s.get("probability", 0) * 100
            ret = s.get("expected_return", 0)
            color_hint = "+" if ret > 0 else ""
            sections.append(f"### {label}情景 (概率 {prob:.0f}%, 预期 {color_hint}{ret:.1f}%)")
            sections.append(f"\n{s.get('description', '')}\n")
            triggers = s.get("triggers", [])
            if triggers:
                sections.append("触发条件:")
                for t in triggers:
                    sections.append(f"- {t}")
            sections.append("")

    ev = result.get("expected_value", 0)
    sections.append(f"### 综合期望收益: {ev:+.1f}%\n")

    recommendation = result.get("recommendation", "")
    if recommendation:
        sections.append(f"**操作建议**: {recommendation}\n")

    risk_reward = result.get("risk_reward_ratio", "")
    if risk_reward:
        sections.append(f"**风险收益比**: {risk_reward}\n")

    return "\n".join(sections)
