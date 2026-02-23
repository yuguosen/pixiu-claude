# 貔貅进化：从规则引擎到 LLM 智能体

> 日期：2026-02-20 18:30
> 作者：Claude Code
> 状态：已实现

## 背景与目标

当前系统是规则驱动的量化工具，按固定公式（if RSI < 30 then buy）做决策，不能推理、不能反思、不能进化。

**目标**：在现有量化信号基础上叠加 Claude API 作为"推理大脑"，赋予系统推理、反思、知识进化和自然语言解释能力。

## 现状分析

- 三策略加权信号（趋势跟踪/均值回归/动量）→ 机械合成
- 学习系统仅做权重微调，不理解 WHY
- 报告是数字堆砌，缺乏可读性和推理链

## 方案设计

### 架构

```
量化层 (不变) → 结构化数据 → LLM 智能体层 (新增)
                                ├── 市场分析师 (Haiku) — 摘要环境
                                ├── 决策引擎 (Sonnet) — 三步反思决策
                                ├── 反思引擎 (Sonnet) — 7/30d 复盘
                                └── 知识库 — 教训积累 → 反馈决策
```

### 新增文件

| 文件 | 职责 |
|------|------|
| `src/agent/__init__.py` | 模块入口 |
| `src/agent/schemas.py` | 数据模型 (MarketAssessment, FundRecommendation, AgentDecision, ReflectionResult) |
| `src/agent/prompts.py` | 系统提示词 (市场分析/决策/反思) |
| `src/agent/brain.py` | LLM 调用核心 (analyze_market, make_decision, reflect_on_decision) |
| `src/agent/reflection.py` | 反思引擎 (run_reflection_cycle, get_relevant_knowledge) |

### 修改文件

| 文件 | 变更 |
|------|------|
| `pyproject.toml` | 新增 anthropic 依赖 |
| `src/config.py` | 新增 llm 配置段 |
| `src/memory/database.py` | 新增 3 张表 (agent_decisions, reflections, knowledge_base) |
| `src/report/recommendation.py` | 集成 LLM 决策，支持增强/回退两种模式 |
| `src/report/templates.py` | 报告模板加入 LLM 分析段落 |
| `src/main.py` | 新增 reflect/knowledge 命令，daily 流程加入反思步骤 |

### 数据库新增表

- `agent_decisions` — LLM 决策记录 (市场上下文、量化信号、分析全文、推理逻辑)
- `reflections` — 反思日志 (7d/30d 复盘、对错判定、教训提炼)
- `knowledge_base` — 知识库 (教训积累、验证次数、活跃状态)

### 决策流程

1. **Haiku 市场摘要** — 综合指数/资金/热点，提炼关键矛盾
2. **Sonnet 三步决策** — 形成假设 → 自我挑战 → 最终定论
3. **持久化** — 决策存入 agent_decisions，教训存入 knowledge_base
4. **7/30d 复盘** — 自动触发 LLM 反思，提炼可操作教训
5. **知识注入** — 未来决策时检索历史教训作为上下文

### 成本控制

| 场景 | 模型 | 月成本 |
|------|------|--------|
| 市场摘要 | Haiku 4.5 | ~$0.50 |
| 决策推理 | Sonnet 4.5 | ~$5.00 |
| 反思复盘 | Sonnet 4.5 | ~$3.00 |
| **合计** | | **~$8-10/月** |

## 影响范围

- 推荐报告内容增强（新增 LLM 分析段落）
- daily 流程从 7 步变为 8 步（新增反思步骤）
- CLI 新增 2 个命令 (reflect, knowledge)
- 数据库新增 3 张表
- 无 API Key 时自动回退到纯量化模式，不影响现有功能

## 风险评估

| 风险 | 缓解策略 |
|------|----------|
| API 调用失败 | 自动回退到纯量化模式 |
| 成本超预期 | Haiku 做摘要控制成本，限制每日调用次数 |
| LLM 幻觉 | 三步反思 + 与量化信号交叉验证 |
| 反思偏差 | 多次验证的教训权重更高 |

## 实现计划

- [x] 阶段1：LLM 基础接入 (schemas, prompts, brain, config, pyproject)
- [x] 阶段2：三步反思决策 + 数据库表 + 报告集成
- [x] 阶段3：反思引擎 + 知识库 + CLI 命令
- [x] 阶段4：知识驱动进化 + daily 流程集成
- [x] 验证：模块导入、数据库建表、CLI 命令均通过
