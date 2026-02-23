# 貔貅 (Pixiu) — 智能基金交易分析系统

## 项目概述

面向中国公募基金（支付宝可购买）的智能交易分析系统。

- 起始资金: 10,000 RMB
- 风险偏好: "可以少赚，不能多亏" — 下行保护优先
- 系统定位: 分析和建议，最终交易决策由用户做出
- 核心能力: 6 策略加权信号 + LLM 智能推理 + 行业热点检测 + 跨资产配置 + 自动学习进化

## 技术栈

- Python 3.12 + uv 包管理
- AKShare: 数据获取 (基金净值、指数、行业板块、资金流向、宏观、估值)
- LLM 双后端: Gemini (Flash/Pro) 或 Anthropic Claude (Haiku/Sonnet/Opus)
- pandas/numpy/scipy: 数据分析
- SQLite: 数据存储 (`db/pixiu.db`, 18 张表)
- Rich: CLI 美化输出
- lark-oapi: 飞书机器人 SDK (WebSocket 长连接)

## 运行命令

```bash
uv run pixiu help          # 查看所有命令
uv run pixiu daily         # 一键日常流程 (11 步全量智能体)
uv run pixiu update        # 更新市场数据
uv run pixiu analyze       # 执行市场分析
uv run pixiu recommend     # 生成交易建议
uv run pixiu hotspot       # 行业热点扫描 (29 个板块)
uv run pixiu discover      # 基金发现 (热点+全市场筛选)
uv run pixiu learn         # 查看学习进化报告
uv run pixiu fund <code>   # 查看单只基金
uv run pixiu portfolio     # 查看组合状态
uv run pixiu watchlist     # 管理观察池 (支持 add/remove)
uv run pixiu backtest      # 回测策略
uv run pixiu record-trade  # 记录交易
uv run pixiu history       # 交易历史
uv run pixiu context       # 系统上下文
uv run pixiu stats         # 交易统计
uv run pixiu reflect       # LLM 反思复盘
uv run pixiu knowledge     # 查看知识库
uv run pixiu valuation     # 查看估值分位
uv run pixiu macro         # 宏观经济指标
uv run pixiu sentiment     # 市场情绪
uv run pixiu managers      # 基金经理评估
uv run pixiu allocation    # 资产配置检查
uv run pixiu fund-flow     # 资金流向分析
uv run pixiu scenario      # LLM 场景推演
uv run pixiu intel         # Market Intelligence 市场情报
uv run pixiu debate        # LLM 多角色辩论
uv run pixiu walk-forward  # 走前验证回测
uv run pixiu monte-carlo   # 蒙特卡洛模拟
uv run pixiu llm           # 查看/切换 LLM 后端

# 飞书机器人
uv run pixiu-bot           # 启动飞书机器人 (WebSocket 长连接, 24/7 运行)
```

## 项目结构

```
src/
├── main.py          # CLI 入口 (26+ 个命令)
├── config.py        # 全局配置 (含 fund_universe 种子池 + scoring_targets)
├── bot/             # 飞书机器人
│   ├── app.py             # 入口: 初始化飞书客户端 + 调度器, 启动 WebSocket
│   ├── router.py          # 命令解析 + 分发
│   ├── handlers.py        # 业务适配层 (调用现有函数, 返回数据)
│   ├── cards.py           # 飞书消息卡片构建器 (10 种卡片模板)
│   ├── sender.py          # 消息发送工具 (回复/主动发送/更新卡片)
│   └── session.py         # 多步会话状态机 (交易录入)
├── agent/           # LLM 智能体层
│   ├── schemas.py          # 结构化输出模型
│   ├── prompts.py          # 系统提示词 (中文 A 股语境)
│   ├── brain.py            # LLM 调用核心 (分析/决策/反思)
│   ├── reflection.py       # 反思引擎 (复盘/知识提炼/教训检索)
│   ├── news.py             # 新闻/政策获取 (AKShare 财经+全球要闻)
│   ├── scenario.py         # 场景推演 (牛/基/熊三情景概率)
│   ├── market_intel.py     # Market Intelligence (多维情报研判)
│   └── debate.py           # 多角色辩论 (乐观/悲观/裁判)
├── data/            # 数据层 (AKShare 封装, 缓存 + 重试)
│   ├── fetcher.py          # AKShare 封装 (缓存 + 重试)
│   ├── fund_data.py        # 基金数据管理
│   ├── fund_discovery.py   # 基金发现 (热点+全市场+种子池导入)
│   ├── market_data.py      # 市场指数数据
│   ├── valuation.py        # 指数估值 (PE/PB 分位)
│   ├── macro.py            # 宏观经济 (PMI/M2/CPI/信贷周期)
│   ├── sentiment.py        # 市场情绪 (融资余额/换手率)
│   └── fund_manager.py     # 基金经理评估
├── analysis/        # 分析引擎
│   ├── indicators.py       # 技术指标 (RSI/MACD/MA/BB 等)
│   ├── fund_scorer.py      # 基金综合评分 (4 维度, 分类别阈值)
│   ├── market_regime.py    # 市场状态检测 (5 种状态 + 资金面)
│   ├── sector_rotation.py  # 行业热点检测 (29 个板块)
│   ├── fund_flow.py        # 资金流向分析 (主力/基金仓位/ETF)
│   ├── seasonal.py         # 季节性/日历因子 (8 种 A 股效应)
│   └── learner.py          # 自动学习引擎 (信号验证 + 权重调整)
├── strategy/        # 策略引擎 (6 策略)
│   ├── base.py             # 策略基类 + Signal 数据类
│   ├── trend_following.py  # 趋势跟踪 (主策略)
│   ├── mean_reversion.py   # 均值回归 (震荡市)
│   ├── momentum.py         # 动量策略 (多维评分 v2)
│   ├── valuation.py        # 估值策略 (PE/PB 分位驱动)
│   ├── macro_cycle.py      # 宏观周期策略
│   ├── manager_alpha.py    # 经理 Alpha 策略
│   ├── portfolio.py        # 组合构建 + 综合信号 (含 category 标签)
│   ├── walk_forward.py     # 走前验证回测
│   └── monte_carlo.py      # 蒙特卡洛模拟
├── risk/            # 风险管理
│   ├── position_sizing.py  # 仓位计算 (半凯利)
│   ├── drawdown.py         # 回撤监控 + 止损
│   ├── cost_calculator.py  # 交易费用计算
│   └── asset_allocation.py # 资产配置保护层 (硬性底线)
├── memory/          # 记忆系统
│   ├── database.py         # SQLite (18 张表, 含 classify_fund)
│   ├── trade_journal.py    # 交易日志统计
│   └── context.py          # 上下文构建
├── report/          # 报告生成
│   ├── recommendation.py   # 买卖建议报告 (含 LLM + 资产配置段落)
│   ├── portfolio_report.py # 组合状态报告
│   └── templates.py        # Markdown 模板
└── scheduler/       # 定时任务 (工作日 15:45)
    └── jobs.py
```

## 基金池 — 5 大资产类别 (26 只)

```
偏股 13 只 (自动发现) — 进攻
债券  5 只 (种子) — 招商产业债A / 易方达增强回报债A / 广发国开债指数A / 嘉实超短债C / 易方达安悦超短债A
指数  3 只 (种子) — 沪深300联接A / 中证500联接A / 创业板联接C
黄金  2 只 (种子) — 易方达黄金联接A / 博时黄金联接A
QDII  3 只 (种子) — 纳斯达克100联接A / 标普500联接A / 标普500指数A
```

分类逻辑 (`classify_fund`): watchlist.category → 基金名称关键词 → 默认 equity

分类别评分阈值 (`CONFIG["scoring_targets"]`):
| 类别 | 年化目标 | 波动率上限 | 回撤上限 |
|------|---------|-----------|---------|
| equity | 20% | 40% | 30% |
| bond | 5% | 8% | 5% |
| index | 15% | 35% | 25% |
| gold | 10% | 25% | 20% |
| qdii | 15% | 35% | 25% |

## 风险参数

- 单基金最大仓位: 30%
- 最大总仓位: 90%
- 软性回撤警报: 5%
- 硬性止损回撤: 10%
- 单基金止损: 8%
- 移动止盈: 从峰值回落 10%
- 申购费折扣: 1折 (支付宝)

### 资产配置硬性底线 (`risk/asset_allocation.py`)

| 规则 | 值 |
|------|-----|
| 股票型基金上限 | ≤ 70% |
| 现金/货币基金下限 | ≥ 20% |
| 债券基金下限 | ≥ 10% |

按市场状态动态调整目标配比:
- 牛市: 股 60% / 债 15% / 现金 25%
- 震荡: 股 45% / 债 25% / 现金 30%
- 熊市: 股 25% / 债 35% / 现金 40%

叠加估值修正: PE 分位 <20% 加股减债, >80% 减股加债。

## 策略体系 (6 策略加权)

| 策略 | 类型 | 核心逻辑 |
|------|------|----------|
| **趋势跟踪** | 主策略 | 均线排列 + MACD + RSI, 多重确认 |
| **均值回归** | 辅助 | RSI 超买超卖 + 布林带, 震荡市专用 |
| **动量策略** | 辅助 | 夏普动量 + 路径质量 + 加速因子 (v2 多维) |
| **估值策略** | 核心增强 | PE/PB 分位驱动, 权重 0.25 |
| **宏观周期** | 辅助 | PMI/M2/CPI → 信贷周期 → 配置偏向 |
| **经理 Alpha** | 微调 | 基金经理年限/规模/业绩评分 |

信号合成: 加权合并 → 冲突检测 (矛盾时降低置信度) → 季节性修正 → 按优先级排序

每个信号携带 `metadata.category` 标签, LLM 可据此做跨资产配置决策。

## 学习闭环

```
信号记录 → 7d/30d 验证 → 策略×市场状态统计 → 动态权重调整
```

## LLM 智能体 (双后端)

```
量化信号 + 资产配置偏差 → Flash/Haiku 市场摘要 → Pro/Opus 三步决策 → 报告
                                                                       ↓
知识库 ← 教训提炼 ← Pro/Sonnet 反思复盘 (7d/30d) ← 实际结果对比
  ↓
  └→ 注入未来决策上下文 (知识驱动进化)
```

- 后端: Gemini (`Flash`/`Pro`) 或 Anthropic (`Haiku`/`Sonnet`/`Opus`), .env 中 `LLM_PROVIDER` 切换
- 无 API Key 时自动回退到纯量化模式
- 决策上下文包含: 各类别信号汇总 + 当前/目标配置比例 + 历史教训

## daily 流程 (11 步)

```
步骤 1:  学习进化 (验证历史信号, 更新权重)
步骤 2:  LLM 反思复盘
步骤 2b: 种子基金池导入 (seed_fund_universe, 幂等)
步骤 3:  更新市场数据 (指数 + 基金净值)
步骤 4:  增强数据采集 (估值/宏观/情绪)
步骤 5:  市场分析 (指数概况 + 状态检测 + 基金评分)
步骤 6:  热点扫描 (29 个行业板块)
步骤 7:  基金发现 (热点驱动 + 全市场筛选 + 下载净值)
步骤 8:  资产配置检查 (硬性底线 + 偏差报警)
步骤 9:  Market Intelligence (多维情报研判)
步骤 10: 生成建议 (6 策略信号 + LLM 裁决 + 资产配置段落)
步骤 11: 组合快照
```

## 数据库 (18 张表)

| 表 | 用途 |
|----|------|
| funds | 基金基本信息 |
| fund_nav | 净值历史 |
| market_indices | 指数历史 |
| portfolio | 持仓记录 |
| trades | 交易记录 |
| account_snapshots | 账户快照 |
| analysis_log | 分析日志 |
| watchlist | 观察池 (**含 category 列**) |
| sector_snapshots | 行业板块每日快照 |
| hotspots | 热点记录 |
| signal_validation | 信号预测 → 7d/30d 验证 |
| strategy_performance | 策略表现聚合 |
| agent_decisions | LLM 决策记录 |
| reflections | 反思日志 |
| knowledge_base | 知识库 (教训积累) |
| index_valuation | 指数估值 (PE/PB) |
| macro_indicators | 宏观经济指标 |
| fund_managers | 基金经理信息 |
| sentiment_indicators | 情绪指标 |
| scenario_analysis | LLM 场景推演 |

## 技术文档

| 文档 | 内容 |
|------|------|
| `docs/202602201430-pixiu-system-design.md` | 初始架构设计 (Phase 1-5) |
| `docs/202602201445-pixiu-project-documentation.md` | 项目全量文档 (部分过时, 见下方注释) |
| `docs/202602201830-llm-agent-layer.md` | LLM 智能体层设计 |
| `docs/202602211000-fund-universe-expansion.md` | 基金池扩容: 5 大资产类别 |

> **注意**: `202602201445` 全量文档中仍记录 "12 张表/3 策略/17 命令", 实际已扩展至 "18+ 张表/6 策略/26+ 命令"。如需全面重写该文档, 可作为后续迭代任务。

## 飞书机器人 (src/bot/)

### 架构

```
飞书服务器 ←WebSocket长连接→ pixiu-bot 进程
                                  │
                  ┌───────────────┼───────────────┐
                  │               │               │
           消息路由器        定时调度器        会话管理器
           (router)         (scheduler)      (session)
                  │               │               │
                  └───────┬───────┘               │
                          ▼                       │
                   业务逻辑适配层 (handlers)  ←────┘
                          │
                          ▼
                   现有 Pixiu 模块
```

- **连接方式**: `lark-oapi` SDK WebSocket 长连接, 无需公网 IP
- **进程模型**: 单进程 — WebSocket 客户端 (主线程阻塞) + 定时调度器 (守护线程)
- **耗时命令**: `recommend`/`daily` 在独立线程执行, 先回复"处理中"卡片

### 支持的命令

| 用户输入 | 功能 | 调用模块 |
|---------|------|---------|
| 帮助 / /help | 命令列表 | - |
| 行情 / /market | 市场快照 | market_regime + market_data |
| 持仓 / /portfolio | 持仓状态 | database |
| 历史 [N] / /history | 交易历史 | database |
| 建议 / /recommend | 交易建议 (耗时) | recommendation |
| 日报 / /daily | 11步日常流程 (耗时) | main.cmd_daily |
| 配置 / /allocation | 资产配置 | asset_allocation |
| 记录 / /trade | 多步交易录入 | database + session |

### 环境变量 (.env)

```
FEISHU_APP_ID=cli_xxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxx
FEISHU_PUSH_CHAT_ID=oc_xxxxxxxxxx   # 可选: 日报自动推送群
```

### 运行

```bash
uv run pixiu-bot                            # 前台运行
nohup uv run pixiu-bot > bot.log 2>&1 &     # 后台运行
```

## 开发约定

- 使用 `uv` 管理 Python 和依赖
- 所有数据存储在 `db/pixiu.db` (SQLite)
- 报告输出到 `reports/YYYY-MM/` 目录
- 分析文档输出到 `docs/` 目录
- 行业板块名称必须对齐 AKShare 命名 (如 "游戏Ⅱ", "白酒Ⅱ")
- 种子基金池定义在 `CONFIG["fund_universe"]`, 添加新基金直接编辑 config.py
- 基金分类逻辑在 `database.py:classify_fund()`, 关键词匹配优先级: gold > qdii > bond > index > equity
