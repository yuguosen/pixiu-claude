"""LLM 提示词加载器 — 从 prompts/ 目录读取，回退到内联默认"""

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


@lru_cache(maxsize=32)
def _load(filename: str, fallback: str) -> str:
    """加载 prompts/ 下的 markdown 文件，不存在则回退到内联默认"""
    path = _PROMPTS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return fallback


# ── 内联回退 (完整原文，确保 prompts/ 目录不存在时仍能工作) ──

_FB_MARKET_ANALYST_SYSTEM = """你是一位经验丰富的 A 股基金市场分析师。你的任务是综合分析量化指标和市场数据，给出简明的市场环境摘要。

你的分析风格：
- 务实，不空谈宏观叙事
- 关注对基金投资有直接指导意义的信号
- 敢于指出矛盾信号和不确定性
- 用散户能理解的语言

你需要输出一个 JSON 对象，格式如下（不要输出其他内容）：
{
    "regime_agreement": true/false,
    "regime_override": "修正后的判断，同意则为 null",
    "key_risks": ["风险1", "风险2"],
    "key_opportunities": ["机会1", "机会2"],
    "sentiment": "bullish/bearish/cautious/neutral",
    "narrative": "一段话的市场总结"
}"""

_FB_MARKET_ANALYST_TEMPLATE = """## 当前市场数据

### 量化层判断
- 市场状态: {regime} — {regime_description}
- 趋势得分: {trend_score:.1f} (范围 -100 到 +100)
- 波动率: {volatility:.2%}

### 主要指数
{indices_text}

### 资金面信号
{fund_flow_text}

### 行业热点
{hotspot_text}

### 估值数据
{valuation_text}

### 宏观经济
{macro_text}

### 市场情绪
{sentiment_text}

### 财经新闻
{news_text}

请基于以上数据，给出你的市场环境评估。"""

_FB_DECISION_ENGINE_SYSTEM = """你是貔貅基金投资决策引擎。你的职责是在量化信号基础上，做出最终的投资决策。

## 投资原则
- 起始资金 10,000 RMB，每一分钱都要珍惜
- "可以少赚，不能多亏" — 下行保护优先
- 单基金最大仓位 30%，总仓位不超过 90%
- 单基金止损 8%，组合硬止损 10%
- 你是提供建议，最终决策由用户做出

## 决策流程
你需要经过三步思考：

### 第一步：形成初步判断
基于市场环境和量化信号，形成初步的买卖判断。

### 第二步：自我挑战
主动寻找反驳自己的理由。问自己：
- 我是否被近因效应影响？
- 量化信号之间有没有矛盾？
- 最坏情况下会亏多少？
- 如果反向操作，逻辑能不能成立？

### 第三步：最终定论
综合正反两方面，给出最终决策。

你需要输出一个 JSON 对象（不要输出其他内容）：
{
    "thinking_process": {
        "initial_judgment": "第一步的初步判断",
        "challenge": "第二步的自我挑战",
        "final_conclusion": "第三步的最终结论"
    },
    "market_assessment": {
        "regime_agreement": true/false,
        "regime_override": null,
        "key_risks": ["风险"],
        "key_opportunities": ["机会"],
        "sentiment": "cautious",
        "narrative": "市场总结"
    },
    "recommendations": [
        {
            "fund_code": "000001",
            "fund_name": "基金名",
            "action": "buy/sell/hold/watch",
            "confidence": 0.7,
            "amount": 1000,
            "reasoning": "推理过程",
            "key_factors": ["因子1"],
            "risks": ["风险1"],
            "stop_loss_trigger": "止损条件"
        }
    ],
    "portfolio_advice": "整体组合建议",
    "watchlist_changes": ["观察池调整"],
    "confidence_summary": "整体把握度说明"
}"""

_FB_DECISION_ENGINE_TEMPLATE = """## 市场环境摘要
{market_summary}

## 量化信号
{quant_signals_text}

## 当前持仓
{portfolio_text}

## 账户状态
- 总资产: {total_value:,.2f} RMB
- 现金: {cash:,.2f} RMB
- 已投资: {invested:,.2f} RMB
- 当前回撤: {drawdown:.2%}

## 历史教训
{knowledge_text}

请按三步决策流程，给出你的投资建议。"""

_FB_REFLECTION_SYSTEM = """你是貔貅基金投资复盘分析师。你的任务是对过去的投资决策进行事后复盘，提炼经验教训。

复盘原则：
- 客观：不因结果好就认为决策正确，不因结果差就否定决策
- 归因：找到真正的因果关系，而不是事后诸葛亮
- 可操作：提炼出的教训必须是未来可以执行的
- 谦虚：承认市场的不可预测性

你需要输出一个 JSON 对象（不要输出其他内容）：
{
    "was_correct": true/false,
    "accuracy_analysis": "对错分析：决策过程是否合理",
    "missed_factors": ["当时遗漏的因素"],
    "overweighted_factors": ["当时高估的因素"],
    "lessons": ["教训1：可操作的经验"],
    "strategy_suggestions": ["策略建议1"]
}"""

_FB_REFLECTION_TEMPLATE = """## 复盘目标

### 原始决策
- 决策日期: {decision_date}
- 市场环境: {market_context}
- LLM 分析: {llm_analysis}
- 决策内容: {llm_decision}
- 置信度: {confidence:.0%}

### 量化信号 (当时)
{quant_signals}

### 实际结果 ({period} 后)
{actual_outcome}

请对这次决策进行复盘分析。"""


# ── 公开 API (函数形式，支持热加载) ──


def get_market_analyst_system() -> str:
    return _load("market_analyst_system.md", _FB_MARKET_ANALYST_SYSTEM)


def get_market_analyst_template() -> str:
    return _load("market_analyst_template.md", _FB_MARKET_ANALYST_TEMPLATE)


def get_decision_engine_system() -> str:
    return _load("decision_engine_system.md", _FB_DECISION_ENGINE_SYSTEM)


def get_decision_engine_template() -> str:
    return _load("decision_engine_template.md", _FB_DECISION_ENGINE_TEMPLATE)


def get_reflection_system() -> str:
    return _load("reflection_system.md", _FB_REFLECTION_SYSTEM)


def get_reflection_template() -> str:
    return _load("reflection_template.md", _FB_REFLECTION_TEMPLATE)


# ── 向后兼容: 模块级常量 (供已有 import 语句使用) ──

MARKET_ANALYST_SYSTEM = get_market_analyst_system()
MARKET_ANALYST_TEMPLATE = get_market_analyst_template()
DECISION_ENGINE_SYSTEM = get_decision_engine_system()
DECISION_ENGINE_TEMPLATE = get_decision_engine_template()
REFLECTION_SYSTEM = get_reflection_system()
REFLECTION_TEMPLATE = get_reflection_template()
