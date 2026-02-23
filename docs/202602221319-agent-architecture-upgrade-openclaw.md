# Agent 架构升级方案 — 借鉴 OpenClaw 设计模式

> 日期：2026-02-22 13:19
> 作者：Claude Code
> 状态：草稿
> 参考：[OpenClaw](https://github.com/openclaw/openclaw) (216K+ stars, TypeScript, MIT)

## 背景与目标

貔貅的 Agent 层（`src/agent/`）已实现完整的 LLM 分析→决策→反思闭环，但在错误恢复、上下文管理、记忆检索、可扩展性等方面存在明显短板。

通过研究 OpenClaw 的 Agent 运行时架构，我们识别出 **7 个高价值设计模式**，可系统性地提升貔貅 Agent 层的健壮性和智能水平。

**目标**：

- 消除 LLM 调用的静默失败，实现自动 Provider 回退
- 防止无效 API 重复调用（循环检测）
- 解决长分析会话的上下文溢出问题
- 提升知识库检索的精准度（从平面查询到混合搜索）
- 为未来 Tool Use 架构演进打下基础

## 现状分析

### 当前架构

```
src/agent/
├── brain.py        # LLM 调用核心 (458 行)
│   ├── _call_llm()          → if/else 分发到 _call_gemini / _call_anthropic
│   ├── analyze_market()     → Haiku/Flash, 1024 tokens
│   ├── make_decision()      → Opus/Pro, budget-aware prompt
│   └── reflect_on_decision()→ Sonnet/Pro
├── reflection.py   # 反思 + 知识库 (345 行)
│   ├── run_reflection_cycle()  → 7d/30d 验证
│   └── get_relevant_knowledge()→ FTS5 + 降级查询
├── scenario.py     # 场景推演 (185 行) — 3 情景概率
├── debate.py       # 多角色辩论 (184 行) — 乐观/悲观/裁判
├── schemas.py      # 4 个 dataclass (50 行)
├── budget.py       # token 预算管理 (68 行)
└── prompts.py      # prompt 模板加载 (204 行)
```

### 当前优势

1. **模型分层**：Haiku/Flash 做分析，Sonnet/Pro 做决策，Opus 做关键裁判 — 成本/质量平衡合理
2. **优雅降级**：每个 LLM 调用返回 `(result, tokens)` 或 `(None, 0)`，无 API Key 时回退纯量化
3. **Budget-aware prompt**：`budget.py` 按优先级裁剪 sections，priority=1 强制截断保留
4. **外部 prompt**：`prompts.py` 从 `prompts/` 目录加载模板，支持热更新
5. **完整学习闭环**：信号记录 → 7d/30d 验证 → 策略权重调整 → 知识库积累

### 关键短板

| 短板 | 现状代码位置 | 影响 |
|------|-------------|------|
| **单次调用无重试** | `brain.py:270-289` `except → return None, 0` | 网络抖动直接丢失整次分析 |
| **Provider 无回退** | `brain.py:198-201` `if/else` 硬分发 | Gemini 限流时不会自动切 Anthropic |
| **错误无分类** | 所有异常统一 `except Exception as e` | 无法区分限流/认证失效/格式错误 |
| **上下文无压缩** | `budget.py` 只做裁剪，不做摘要 | 26 只基金 × 6 策略可能撑爆上下文 |
| **JSON 无验证** | `brain.py:204-226` `_parse_json_response` | 缺字段/类型错静默传播 |
| **知识检索粗糙** | `reflection.py:230-269` FTS5 MATCH + 降级 | 无向量搜索，无时间衰减模型 |
| **无循环检测** | `fetcher.py` 重试无去重 | AKShare 持续失败时浪费调用 |
| **LLM 调用串行** | `debate.py:86-138` 乐观→悲观→裁判顺序执行 | 前两步可并行但没有 |
| **无 Tool Use** | 所有上下文预加载到 prompt | 基金池扩大后不可持续 |

## 方案设计

### 概览：4 阶段渐进式改造

```
Phase 1: 健壮性 ─────── 重试 + 错误分类 + Provider 自动回退 + Schema 验证
     ↓
Phase 2: 上下文管理 ─── 比例截断 + Prompt 模块化 + 循环检测 + 并行调用
     ↓
Phase 3: 记忆升级 ───── 向量+FTS 混合搜索 + 时间衰减 + MMR 去重
     ↓
Phase 4: Tool Use ───── LLM 主动查询信号/持仓/估值 (架构质变)
```

每个 Phase 独立可交付，不阻塞后续 Phase。

---

### Phase 1: 健壮性（高影响，低风险）

#### 1.1 结构化错误分类

**借鉴 OpenClaw**: `src/agents/failover-error.ts` — 错误按类别分类，驱动不同恢复策略。

**新增 `src/agent/errors.py`**:

```python
from dataclasses import dataclass
from enum import Enum


class ErrorCategory(Enum):
    RATE_LIMIT = "rate_limit"       # 429 — 切换 Provider
    AUTH = "auth"                   # 401/403 — 停止重试，报告用户
    TIMEOUT = "timeout"             # 超时 — 重试
    FORMAT = "format"               # 响应解析失败 — 重试 (LLM 输出不稳定)
    CONTEXT_OVERFLOW = "overflow"   # 上下文超限 — 压缩后重试
    BILLING = "billing"             # 402 — 停止，通知用户
    NETWORK = "network"             # 连接错误 — 重试
    UNKNOWN = "unknown"


@dataclass
class LLMError:
    category: ErrorCategory
    provider: str               # "gemini" | "anthropic"
    model: str
    message: str
    is_retryable: bool
    status_code: int | None = None

    @classmethod
    def classify(cls, exc: Exception, provider: str, model: str) -> "LLMError":
        """从原始异常中分类出结构化错误"""
        msg = str(exc)
        status = getattr(exc, "status_code", None) or _extract_status(msg)

        if status == 429:
            return cls(ErrorCategory.RATE_LIMIT, provider, model, msg, True, status)
        elif status in (401, 403):
            return cls(ErrorCategory.AUTH, provider, model, msg, False, status)
        elif status == 402:
            return cls(ErrorCategory.BILLING, provider, model, msg, False, status)
        elif status in (408, 503, 529):
            return cls(ErrorCategory.TIMEOUT, provider, model, msg, True, status)
        elif "context" in msg.lower() or "token" in msg.lower():
            return cls(ErrorCategory.CONTEXT_OVERFLOW, provider, model, msg, True, status)
        elif isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            return cls(ErrorCategory.NETWORK, provider, model, msg, True, status)
        elif isinstance(exc, (json.JSONDecodeError, ValueError, KeyError)):
            return cls(ErrorCategory.FORMAT, provider, model, msg, True, status)
        else:
            return cls(ErrorCategory.UNKNOWN, provider, model, msg, True, status)
```

#### 1.2 重试 + Provider 自动回退

**借鉴 OpenClaw**: `runWithModelFallback()` → `runEmbeddedPiAgent()` → `runEmbeddedAttempt()` 三层嵌套。

**改造 `brain.py:_call_llm()`**:

```python
def _call_llm(
    system: str,
    user_message: str,
    model: str | None = None,
    max_tokens: int | None = None,
    max_retries: int = 3,
    fallback_provider: bool = True,
) -> tuple[str, int]:
    """统一 LLM 调用入口 — 自动重试 + Provider 回退

    重试策略:
    1. 同 Provider 重试 (指数退避, 最多 max_retries 次)
    2. 如果所有重试失败且 fallback_provider=True, 切换到备用 Provider
    3. 备用 Provider 也失败 → raise LLMError
    """
    providers = _get_provider_chain()  # e.g. ["anthropic", "gemini"]

    for provider in providers:
        for attempt in range(max_retries):
            try:
                return _dispatch(provider, system, user_message, model, max_tokens)
            except Exception as exc:
                error = LLMError.classify(exc, provider, model)
                if not error.is_retryable:
                    raise error
                if error.category == ErrorCategory.RATE_LIMIT and fallback_provider:
                    break  # 跳到下一个 provider
                backoff = min(2 ** attempt, 8)
                time.sleep(backoff)
        # 当前 provider 耗尽重试

    raise LLMError(ErrorCategory.UNKNOWN, "all", model or "", "所有 Provider 均失败", False)
```

**Provider 链**:

```python
def _get_provider_chain() -> list[str]:
    """获取 Provider 优先级链 (主 → 备)"""
    primary = _get_provider()
    fallback = "gemini" if primary == "anthropic" else "anthropic"
    # 只有备用 Provider 有 API Key 时才加入链
    if _has_api_key(fallback):
        return [primary, fallback]
    return [primary]
```

#### 1.3 Pydantic Schema 验证

**借鉴 OpenClaw**: 所有 LLM 输出经过严格结构化验证。

**改造 `schemas.py`** — 从 `dataclass` 迁移到 `pydantic.BaseModel`:

```python
from pydantic import BaseModel, Field, field_validator


class MarketAssessment(BaseModel):
    regime_agreement: bool
    regime_override: str | None = None
    key_risks: list[str] = Field(default_factory=list, min_length=0, max_length=10)
    key_opportunities: list[str] = Field(default_factory=list)
    sentiment: str = "neutral"
    narrative: str = ""

    @field_validator("sentiment")
    @classmethod
    def validate_sentiment(cls, v):
        allowed = {"bullish", "bearish", "cautious", "neutral"}
        return v if v in allowed else "neutral"


class FundRecommendation(BaseModel):
    fund_code: str
    action: str = "hold"
    confidence: float = Field(ge=0, le=1, default=0.5)
    amount: float = Field(ge=0, default=0)
    reasoning: str = ""
    key_factors: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    stop_loss_trigger: str = ""

    @field_validator("action")
    @classmethod
    def validate_action(cls, v):
        allowed = {"buy", "sell", "hold", "watch"}
        return v if v in allowed else "hold"
```

这样 `_parse_json_response` 之后用 `MarketAssessment.model_validate(data)` 即可获得类型安全的对象，缺字段自动填默认值，非法值自动修正。

---

### Phase 2: 上下文管理（中等工作量）

#### 2.1 比例截断

**借鉴 OpenClaw**: `tool-result-truncation.ts` — 单个工具结果不超过上下文窗口 30%。

**改造 `budget.py`**:

```python
# 新增: 单 section 上限 = 总预算的 30%
SECTION_MAX_RATIO = 0.30

def build_prompt(sections: list[PromptSection], max_tokens: int = 8000) -> str:
    section_cap = int(max_tokens * SECTION_MAX_RATIO)

    for s in sections:
        tokens = estimate_tokens(s.content)
        if tokens > section_cap:
            # 比例截断，保留开头和结尾
            ratio = section_cap / tokens
            head_len = int(len(s.content) * ratio * 0.7)
            tail_len = int(len(s.content) * ratio * 0.3)
            s.content = (
                s.content[:head_len]
                + f"\n\n[...已截断 {tokens - section_cap} tokens...]\n\n"
                + s.content[-tail_len:]
            )
    # ... 原有逻辑
```

#### 2.2 Prompt 模块化拼装

**借鉴 OpenClaw**: `system-prompt.ts` — `full` / `minimal` / `none` 三种模式。

```python
class PromptMode(Enum):
    FULL = "full"         # daily 完整分析: 身份+工具+记忆+安全+市场
    MINIMAL = "minimal"   # 快速查询 (fund/portfolio): 身份+市场
    NONE = "none"         # 纯 JSON 应答 (scenario/debate): 仅任务指令

def build_system_prompt(mode: PromptMode, **context) -> str:
    sections = [_identity_section()]  # 始终包含

    if mode == PromptMode.FULL:
        sections += [
            _risk_rules_section(),
            _knowledge_section(context.get("regime")),
            _allocation_rules_section(),
            _output_format_section(),
        ]
    elif mode == PromptMode.MINIMAL:
        sections += [_output_format_section()]
    # NONE: 仅身份

    return "\n\n".join(s for s in sections if s)
```

**效果**: `fund <code>` 查询从 ~3000 tokens system prompt 降到 ~500 tokens。

#### 2.3 AKShare 循环检测

**借鉴 OpenClaw**: `tool-loop-detection.ts` — 滑动窗口 + 输入/输出 hash 比对。

**新增 `src/data/loop_guard.py`**:

```python
import hashlib
from collections import deque
from dataclasses import dataclass


@dataclass
class CallRecord:
    args_hash: str
    result_hash: str


class LoopGuard:
    """滑动窗口循环检测器"""

    def __init__(self, window_size: int = 20, repeat_threshold: int = 3):
        self._window: deque[CallRecord] = deque(maxlen=window_size)
        self._threshold = repeat_threshold

    def check_and_record(self, func_name: str, args: tuple, result) -> bool:
        """记录调用并检测是否循环。返回 True 表示应该阻断。"""
        args_hash = hashlib.md5(f"{func_name}:{args}".encode()).hexdigest()
        result_hash = hashlib.md5(str(result).encode()).hexdigest()

        # 统计相同输入+相同输出的次数
        same_count = sum(
            1 for r in self._window
            if r.args_hash == args_hash and r.result_hash == result_hash
        )

        self._window.append(CallRecord(args_hash, result_hash))

        if same_count >= self._threshold:
            return True  # 阻断: 同样的请求反复得到同样的失败结果
        return False
```

集成到 `fetcher.py` 的 `fetch_with_retry()`:

```python
_guard = LoopGuard()

def fetch_with_retry(func_name, *args, retries=3):
    for attempt in range(retries):
        try:
            result = getattr(ak, func_name)(*args)
            _guard.check_and_record(func_name, args, "ok")
            return result
        except Exception as e:
            if _guard.check_and_record(func_name, args, str(e)):
                raise LoopDetectedError(f"{func_name} 循环检测触发，停止重试")
            time.sleep(2 ** attempt)
```

#### 2.4 辩论并行化

**当前** `debate.py` 乐观派→悲观派→裁判串行执行，但前两步无依赖。

```python
import concurrent.futures

def run_debate(market_context: str) -> dict | None:
    prompt = f"以下是当前市场数据，请给出你的分析：\n\n{market_context}"

    # 乐观派和悲观派并行
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future_opt = pool.submit(_call_llm, OPTIMIST_SYSTEM, prompt, analysis_model, 1024)
        future_pes = pool.submit(_call_llm, PESSIMIST_SYSTEM, prompt, analysis_model, 1024)

        optimist_text, t1 = future_opt.result()
        pessimist_text, t2 = future_pes.result()

    # 裁判串行 (依赖前两步)
    judge_text, t3 = _call_llm(JUDGE_SYSTEM, judge_prompt, critical_model, 2048)
    ...
```

**效果**: 辩论耗时从 ~3x LLM 延迟 降到 ~2x。

---

### Phase 3: 记忆系统升级（中高工作量）

#### 3.1 混合搜索架构

**借鉴 OpenClaw**: `src/memory/hybrid.ts` — 向量 + FTS 加权合并 + 时间衰减 + MMR 去重。

**当前系统**: `reflection.py:230-269` — FTS5 MATCH 单一检索，降级到 `ORDER BY times_validated DESC`。

**目标架构**:

```
查询 ──→ [查询扩展] ──→ [并行搜索]
                           ├── 向量相似度 (sentence-transformers)
                           ├── 关键词 FTS5 (BM25)
                           └──→ 合并结果
                                ├── 加权评分: α × vec_score + β × fts_score
                                ├── 时间衰减: score × exp(-λ × age_days)
                                ├── MMR 去冗余 (λ=0.7)
                                └──→ Top-K 结果
```

#### 3.2 时间衰减模型

**借鉴 OpenClaw**: `src/memory/temporal-decay.ts` — 指数衰减，半衰期可配置。

```python
import math

def temporal_decay(score: float, age_days: float, half_life: float = 30.0) -> float:
    """指数时间衰减

    Args:
        score: 原始相关性得分
        age_days: 教训距今天数
        half_life: 半衰期 (天)

    Returns:
        衰减后的得分
    """
    decay_lambda = math.log(2) / half_life
    return score * math.exp(-decay_lambda * age_days)
```

**效果**: 6 个月前牛市中的教训自然衰减到 ~1.5% 权重，不再主导决策上下文。

#### 3.3 MMR 去冗余排序

**借鉴 OpenClaw**: `src/memory/mmr.ts` — 防止语义重复的教训占据所有 Top-K 位置。

```python
def mmr_rerank(
    candidates: list[dict],   # [{content, score}]
    lambda_: float = 0.7,
    top_k: int = 10,
) -> list[dict]:
    """Maximal Marginal Relevance 重排序

    公式: MMR = λ × relevance - (1-λ) × max_similarity_to_selected
    """
    selected = []
    remaining = list(candidates)

    while remaining and len(selected) < top_k:
        best_idx, best_mmr = -1, float("-inf")
        for i, cand in enumerate(remaining):
            relevance = cand["score"]
            if selected:
                max_sim = max(
                    _jaccard_similarity(cand["content"], s["content"])
                    for s in selected
                )
            else:
                max_sim = 0
            mmr = lambda_ * relevance - (1 - lambda_) * max_sim
            if mmr > best_mmr:
                best_mmr, best_idx = mmr, i
        selected.append(remaining.pop(best_idx))

    return selected
```

#### 3.4 向量搜索（可选，依赖 embedding 模型）

两种实现路径:

| 方案 | 依赖 | 适用场景 |
|------|------|---------|
| **A: 本地 embedding** | `sentence-transformers` + `sqlite-vec` | 离线优先，无网络依赖 |
| **B: API embedding** | Gemini/Anthropic embedding API | 质量更高，需网络 |

建议先用 **方案 A**（`paraphrase-multilingual-MiniLM-L12-v2`，支持中文，384 维），后续可切换到 API。

---

### Phase 4: Tool Use 架构演进（高工作量，高价值）

#### 4.1 问题

当前所有上下文**预加载**到 prompt:

```python
# brain.py:make_decision() — 当前模式
sections = [
    PromptSection("市场摘要", market_summary, priority=1),
    PromptSection("量化信号", quant_signals_text, priority=1),   # 26只 × 6策略 = ~156行
    PromptSection("账户状态", account_text, priority=1),
    PromptSection("持仓", portfolio_text, priority=2),
    PromptSection("教训", knowledge_text, priority=3),
]
```

基金池从 26 只扩展到 50+ 只时，`quant_signals_text` 将超过 8000 tokens。

#### 4.2 Tool Use 方案

**借鉴 OpenClaw**: `src/agents/tools/memory-tool.ts` — LLM 主动调用工具查询。

让 LLM 拥有以下工具:

```python
TOOLS = [
    {
        "name": "query_signals",
        "description": "查询指定类别或基金的量化信号",
        "parameters": {
            "category": "equity|bond|index|gold|qdii|all",
            "fund_code": "可选，查询特定基金",
            "signal_type": "可选，buy|sell|hold",
        }
    },
    {
        "name": "query_portfolio",
        "description": "查询当前持仓和账户状态",
        "parameters": {}
    },
    {
        "name": "query_valuation",
        "description": "查询指数估值分位数",
        "parameters": {"index_code": "000300|000905|399006"}
    },
    {
        "name": "search_knowledge",
        "description": "从知识库检索相关历史教训",
        "parameters": {"query": "搜索关键词"}
    },
    {
        "name": "query_fund_detail",
        "description": "查询单只基金的详细数据",
        "parameters": {"fund_code": "基金代码"}
    },
]
```

**工作流变化**:

```
当前: 预加载 156 行信号 → 一次性塞给 LLM → LLM 输出决策
未来: 给 LLM 市场摘要 → LLM 决定查询哪些类别 → 按需获取 → 迭代推理 → 输出决策
```

**效果**: prompt tokens 从 ~8000 降到 ~3000 (首轮) + 按需加载，支持 100+ 只基金池。

#### 4.3 实现路径

Anthropic Claude 原生支持 Tool Use:

```python
response = client.messages.create(
    model=model,
    system=system,
    messages=messages,
    tools=TOOLS,
    max_tokens=4096,
)

# 处理 tool_use 类型的 content block
for block in response.content:
    if block.type == "tool_use":
        result = execute_tool(block.name, block.input)
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": block.id, "content": result}
        ]})
        # 继续对话...
```

Gemini 也支持 Function Calling，接口类似。

---

## 影响范围

| 模块 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|---------|---------|---------|---------|
| `agent/brain.py` | **重构** (重试+回退) | 小改 (prompt 模式) | 不变 | **重构** (tool use 循环) |
| `agent/errors.py` | **新增** | 不变 | 不变 | 不变 |
| `agent/schemas.py` | **重构** (→ Pydantic) | 不变 | 不变 | 小改 (tool schemas) |
| `agent/budget.py` | 不变 | **改造** (比例截断) | 不变 | 可能废弃 |
| `agent/debate.py` | 受益 (自动重试) | **改造** (并行) | 不变 | 不变 |
| `agent/reflection.py` | 受益 (自动重试) | 不变 | **重构** (混合搜索) | 不变 |
| `data/fetcher.py` | 不变 | **改造** (循环检测) | 不变 | 不变 |
| `data/loop_guard.py` | 不变 | **新增** | 不变 | 不变 |
| `memory/database.py` | 不变 | 不变 | **改造** (向量表) | **改造** (tool 查询) |
| `config.py` | 小改 (重试配置) | 小改 | 小改 (向量配置) | 小改 (tool 配置) |

## 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Pydantic 迁移破坏现有 JSON 解析 | 中 | 高 | 先写测试覆盖现有解析逻辑，再迁移 |
| Provider 回退增加延迟 | 低 | 低 | 回退只在主 Provider 失败时触发，正常路径零开销 |
| 向量 embedding 模型下载大（~500MB） | 中 | 低 | 首次运行自动下载，后续本地缓存 |
| Tool Use 增加 LLM 调用轮数和 token 消耗 | 高 | 中 | 设置最大轮数限制（如 5 轮），超出降级到预加载模式 |
| 辩论并行可能触发 API 并发限制 | 低 | 低 | 2 个并发在所有 Provider 限制范围内 |

## 实现计划

### Phase 1: 健壮性（预估 1-2 天）

1. 新增 `src/agent/errors.py` — 错误分类体系
2. 重构 `brain.py:_call_llm()` — 重试 + Provider 回退链
3. `schemas.py` 迁移到 Pydantic BaseModel
4. 所有 `_parse_json_response()` 调用处加 schema 验证
5. 补充测试: 错误分类、重试逻辑、schema 验证

### Phase 2: 上下文管理（预估 1-2 天）

1. `budget.py` 增加比例截断逻辑
2. 新增 `src/data/loop_guard.py`，集成到 `fetcher.py`
3. `debate.py` 改造为并行调用
4. 新增 PromptMode 枚举，改造 prompt 拼装

### Phase 3: 记忆升级（预估 2-3 天）

1. 引入 `sentence-transformers` 依赖
2. `database.py` 新增向量表 + embedding 索引
3. 新增 `src/memory/search.py` — 混合搜索引擎
4. 实现时间衰减 + MMR 去重
5. 改造 `reflection.py:get_relevant_knowledge()`

### Phase 4: Tool Use（预估 3-5 天）

1. 定义 Tool 列表和执行器
2. 改造 `brain.py:make_decision()` 为 tool-use 循环
3. 适配 Gemini Function Calling + Anthropic Tool Use
4. 增加最大轮数限制和降级策略
5. 端到端测试
