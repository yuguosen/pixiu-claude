# 貔貅 (Pixiu) 智能基金交易分析系统 — 项目文档

> 日期：2026-02-20 14:45 (初版) / 2026-02-21 更新
> 作者：Claude Code
> 状态：已实现

---

## 一、项目概述

### 1.1 定位

貔貅是一个面向中国公募基金（支付宝可购买）的 CLI 智能交易分析系统。系统自动获取市场数据、计算技术指标、检测市场状态、评分筛选基金，通过 6 策略加权 + LLM 智能推理生成带有详细理由的买卖建议，并覆盖 5 大资产类别实现跨资产配置。

**系统只负责分析和建议，最终交易决策由用户做出。**

### 1.2 核心约束

| 约束 | 说明 |
|------|------|
| 起始资金 | 10,000 RMB |
| 风险偏好 | "可以少赚，不能多亏" — 下行保护优先 |
| 标的范围 | 支付宝可购买的中国公募基金 (5 大资产类别) |
| 交互方式 | CLI 命令行 + Markdown 报告 |

### 1.3 技术栈

| 组件 | 技术选型 |
|------|----------|
| 语言 | Python 3.12 |
| 包管理 | uv (Rust-based) |
| 数据源 | AKShare（东方财富等） |
| LLM | 双后端: Gemini (Flash/Pro) 或 Anthropic Claude (Haiku/Sonnet/Opus) |
| 数据分析 | pandas / numpy / scipy |
| 数据存储 | SQLite (单文件 `db/pixiu.db`) |
| CLI 输出 | Rich (表格美化) |
| 定时调度 | schedule |

---

## 二、项目结构

```
D:\project\pixiu-claude/
├── pyproject.toml                      # uv 项目配置 + 依赖
├── CLAUDE.md                           # 项目记忆文件 (系统全貌)
├── .env                                # API Key (gitignored)
├── .gitignore
│
├── src/                                # 源代码
│   ├── __init__.py
│   ├── main.py                         # CLI 入口 (26+ 个命令)
│   ├── config.py                       # 全局配置 (含 fund_universe + scoring_targets)
│   │
│   ├── agent/                          # LLM 智能体层
│   │   ├── schemas.py                  # 结构化输出模型
│   │   ├── prompts.py                  # 系统提示词 (中文 A 股语境)
│   │   ├── brain.py                    # LLM 调用核心 (分析/决策/反思)
│   │   ├── reflection.py              # 反思引擎 (复盘/知识提炼/教训检索)
│   │   ├── scenario.py                # 场景推演 (牛/基/熊三情景概率)
│   │   └── debate.py                  # 多角色辩论 (乐观/悲观/裁判)
│   │
│   ├── data/                           # 数据层
│   │   ├── fetcher.py                  # AKShare 封装 (缓存 + 重试)
│   │   ├── fund_data.py                # 基金数据管理
│   │   ├── fund_discovery.py           # 基金发现 (热点+全市场+种子池导入)
│   │   ├── market_data.py              # 市场指数数据
│   │   ├── valuation.py                # 指数估值 (PE/PB 分位)
│   │   ├── macro.py                    # 宏观经济 (PMI/M2/CPI/信贷周期)
│   │   ├── sentiment.py                # 市场情绪 (融资余额/换手率)
│   │   └── fund_manager.py             # 基金经理评估
│   │
│   ├── analysis/                       # 分析引擎
│   │   ├── indicators.py               # 技术指标 (10 个)
│   │   ├── fund_scorer.py              # 基金综合评分 (4 维度, 分类别阈值)
│   │   ├── fund_flow.py                # 资金流向分析 (主力资金/基金仓位/ETF)
│   │   ├── market_regime.py            # 市场状态检测 (5 种状态 + 资金面)
│   │   ├── seasonal.py                 # 季节性/日历因子 (8 种模式)
│   │   ├── sector_rotation.py          # 行业热点检测 (29 个板块)
│   │   └── learner.py                  # 自动学习引擎
│   │
│   ├── strategy/                       # 策略引擎 (6 策略)
│   │   ├── base.py                     # 策略基类 + Signal 数据类
│   │   ├── trend_following.py          # 趋势跟踪策略 (主策略)
│   │   ├── mean_reversion.py           # 均值回归策略
│   │   ├── momentum.py                 # 动量策略 (v2 多维评分)
│   │   ├── valuation.py                # 估值策略 (PE/PB 分位驱动)
│   │   ├── macro_cycle.py              # 宏观周期策略
│   │   ├── manager_alpha.py            # 经理 Alpha 策略
│   │   ├── portfolio.py                # 组合构建 + 综合信号 (含 category 标签)
│   │   ├── walk_forward.py             # 走前验证回测
│   │   └── monte_carlo.py              # 蒙特卡洛模拟
│   │
│   ├── risk/                           # 风险管理
│   │   ├── position_sizing.py          # 仓位计算 (半凯利)
│   │   ├── drawdown.py                 # 回撤监控 + 止损
│   │   ├── cost_calculator.py          # 交易费用计算
│   │   └── asset_allocation.py         # 资产配置保护层 (硬性底线)
│   │
│   ├── memory/                         # 记忆系统
│   │   ├── database.py                 # SQLite (18+ 张表, 含 classify_fund)
│   │   ├── trade_journal.py            # 交易日志统计
│   │   └── context.py                  # 上下文构建
│   │
│   ├── report/                         # 报告生成
│   │   ├── recommendation.py           # 买卖建议报告 (LLM + 资产配置段落)
│   │   ├── portfolio_report.py         # 组合状态报告
│   │   └── templates.py                # Markdown 模板
│   │
│   └── scheduler/                      # 调度器
│       └── jobs.py                     # 工作日 15:45 定时任务
│
├── db/                                 # SQLite 数据库 (运行时生成)
├── data/cache/                         # AKShare 数据缓存
├── reports/                            # 生成的 Markdown 报告
└── docs/                               # 技术文档
```

---

## 三、CLI 命令

所有命令通过 `uv run pixiu <命令>` 调用。

### 3.1 命令一览

| 命令 | 说明 | 示例 |
|------|------|------|
| `help` | 显示帮助 | `uv run pixiu help` |
| `update` | 更新市场指数 + 基金净值 | `uv run pixiu update` |
| `fund <代码>` | 查看单只基金详情 | `uv run pixiu fund 110011` |
| `analyze` | 市场分析 (指数 + 状态 + 评分) | `uv run pixiu analyze` |
| `recommend` | 生成交易建议报告 (含 LLM) | `uv run pixiu recommend` |
| `portfolio` | 查看当前持仓 | `uv run pixiu portfolio` |
| `history [N]` | 查看最近 N 条交易记录 | `uv run pixiu history 10` |
| `watchlist` | 管理观察池 (显示类别) | `uv run pixiu watchlist` |
| `record-trade` | 交互式记录交易 | `uv run pixiu record-trade` |
| `backtest` | 回测趋势策略 | `uv run pixiu backtest` |
| `daily` | 一键日常流程 (10 步) | `uv run pixiu daily` |
| `discover` | 基金发现 (热点+全市场筛选) | `uv run pixiu discover` |
| `fund-flow` | 资金流向分析 | `uv run pixiu fund-flow` |
| `hotspot` | 行业热点扫描 | `uv run pixiu hotspot` |
| `learn` | 查看学习进化报告 | `uv run pixiu learn` |
| `context` | 查看系统上下文 | `uv run pixiu context` |
| `stats` | 查看交易统计 | `uv run pixiu stats` |
| `schedule` | 启动定时调度器 | `uv run pixiu schedule` |
| `reflect` | LLM 反思复盘 | `uv run pixiu reflect` |
| `knowledge` | 查看知识库 | `uv run pixiu knowledge` |
| `valuation` | 查看估值分位 | `uv run pixiu valuation` |
| `macro` | 宏观经济指标 | `uv run pixiu macro` |
| `sentiment` | 市场情绪 | `uv run pixiu sentiment` |
| `managers` | 基金经理评估 | `uv run pixiu managers` |
| `allocation` | 资产配置检查 | `uv run pixiu allocation` |
| `scenario` | LLM 场景推演 | `uv run pixiu scenario` |
| `debate` | LLM 多角色辩论 | `uv run pixiu debate` |
| `walk-forward` | 走前验证回测 | `uv run pixiu walk-forward` |
| `monte-carlo` | 蒙特卡洛模拟 | `uv run pixiu monte-carlo` |
| `llm` | 查看/切换 LLM 后端 | `uv run pixiu llm anthropic` |

### 3.2 核心工作流

#### 日常流程 (`daily`) — 10 步全量智能体

```
uv run pixiu daily
  ├── 步骤 1:  learn         → 学习进化 (验证历史信号, 更新策略权重)
  ├── 步骤 2:  reflect       → LLM 反思复盘 (7d/30d)
  ├── 步骤 2b: seed          → 种子基金池导入 (幂等, 5 大资产类别)
  ├── 步骤 3:  update        → 获取最新指数 + 基金净值 (AKShare → SQLite)
  ├── 步骤 4:  enhanced data → 估值/宏观/情绪数据采集
  ├── 步骤 5:  analyze       → 指数概况 + 市场状态 + 基金评分
  ├── 步骤 6:  hotspot       → 行业热点扫描 (29 个板块)
  ├── 步骤 7:  discover      → 基金发现 (热点驱动 + 全市场 + 下载净值)
  ├── 步骤 8:  allocation    → 资产配置检查 (硬性底线 + 偏差报警)
  ├── 步骤 9:  recommend     → 生成建议 (6 策略 + LLM 裁决 + 资产配置)
  └── 步骤 10: snapshot      → 保存组合快照
```

#### 观察池管理 (`watchlist`)

```bash
uv run pixiu watchlist                      # 显示观察池 (含类别列和分类统计)
uv run pixiu watchlist add 110011 低估值    # 添加基金
uv run pixiu watchlist remove 110011        # 移除基金
```

---

## 四、数据流架构

```
┌──────────────────────────────────────────────────────────────────────┐
│  外部数据源 (AKShare)                                                │
│  · 基金净值 (fund_open_fund_info_em)                                 │
│  · 指数日线 (index_zh_a_hist)                                        │
│  · 基金信息 (fund_individual_basic_info_xq)                          │
│  · 估值数据 / 宏观经济 / 市场情绪 / 资金流向                         │
└──────────────┬───────────────────────────────────────────────────────┘
               │ fetch_with_retry (max_retries=3, 指数退避)
               ▼
┌──────────────────────────┐
│  本地缓存 (data/cache/)   │  JSON 文件, TTL 12 小时
│  MD5(请求参数) → .json    │  避免重复请求
└──────────────┬───────────┘
               ▼
┌──────────────────────────┐
│  SQLite (db/pixiu.db)     │  18+ 张表, WAL 模式
│  · fund_nav              │  净值历史
│  · market_indices        │  指数历史
│  · funds                 │  基金信息
│  · portfolio             │  持仓记录
│  · trades                │  交易记录
│  · account_snapshots     │  账户快照
│  · analysis_log          │  分析日志
│  · watchlist (+ category)│  观察池 (含资产类别)
│  · sector_snapshots      │  行业板块每日快照
│  · hotspots              │  热点记录与生命周期
│  · signal_validation     │  信号验证 (7d/30d 回查)
│  · strategy_performance  │  策略表现统计
│  · agent_decisions       │  LLM 决策记录
│  · reflections           │  反思日志
│  · knowledge_base        │  知识库 (教训积累)
│  · index_valuation       │  指数估值 (PE/PB)
│  · macro_indicators      │  宏观经济指标
│  · fund_managers         │  基金经理信息
│  · sentiment_indicators  │  情绪指标
│  · scenario_analysis     │  LLM 场景推演
└──────────────┬───────────┘
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  分析引擎                                                            │
│                                                                      │
│  indicators.py ──→ 技术指标 (RSI/MACD/MA/BB/Vol/Sharpe/MDD)         │
│  fund_scorer.py ──→ 综合评分 (分类别阈值: equity/bond/index/gold/qdii)│
│  market_regime.py ──→ 市场状态 (趋势评分 -100~+100 + 资金面)        │
│  sector_rotation.py ──→ 板块强弱 (动量 + 趋势)                      │
│  fund_flow.py ──→ 资金流向 (主力/基金仓位/ETF)                       │
│  seasonal.py ──→ 日历效应 (8 种 A 股季节性)                          │
└──────────────┬───────────────────────────────────────────────────────┘
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  策略引擎 (6 策略加权)                                               │
│                                                                      │
│  趋势跟踪 ──┐                                                       │
│  均值回归 ──┤                                                        │
│  动量策略 ──┼──→ 加权合并 ──→ 综合信号 (按优先级排序)               │
│  估值策略 ──┤   (权重由市场状态 + 学习系统决定)                      │
│  宏观周期 ──┤   每个信号携带 category 标签                           │
│  经理Alpha──┘                                                        │
└──────────────┬───────────────────────────────────────────────────────┘
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  LLM 智能体层 (可选, 无 API Key 时回退到纯量化)                      │
│                                                                      │
│  Flash/Haiku ──→ 市场摘要 (综合指数/资金/热点)                       │
│  Pro/Opus ──→ 三步决策 (假设→挑战→定论)                              │
│               → 跨资产配置裁决 (各类别信号 + 配置偏差)               │
│  Pro/Sonnet ──→ 反思复盘 (7d/30d) → 知识库                          │
└──────────────┬───────────────────────────────────────────────────────┘
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  风险管理 + 资产配置                                                  │
│                                                                      │
│  position_sizing ──→ 仓位金额 (半凯利 + 市场状态 + 置信度)          │
│  drawdown ──→ 回撤检查 (5% 警告 / 10% 硬止损)                       │
│  cost_calculator ──→ 费用估算 (申购1折 + 赎回分档)                   │
│  asset_allocation ──→ 配置底线 (股≤70%, 现金≥20%, 债≥10%)           │
└──────────────┬───────────────────────────────────────────────────────┘
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  报告输出                                                            │
│                                                                      │
│  · CLI 终端表格 (Rich)                                               │
│  · Markdown 报告 → reports/YYYY-MM/YYYYMMDDHHmm_type.md             │
│  · 含: LLM 分析段落 + 资产配置 (当前 vs 目标 vs 偏差) 段落          │
│  · 分析日志 → analysis_log 表                                        │
│  · 交易建议 → trades 表 (status=pending)                             │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 五、模块详细说明

### 5.1 数据层 (`src/data/`)

#### `fetcher.py` — AKShare 封装

| 函数 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `fetch_fund_nav` | fund_code, start_date?, end_date? | DataFrame | 基金净值 (nav_date, nav, acc_nav, daily_return) |
| `fetch_fund_info` | fund_code | dict | 基金基本信息 (名称、类型、公司、基准) |
| `fetch_index_daily` | index_code, start_date?, end_date? | DataFrame | 指数日线 OHLCV |
| `fetch_fund_ranking` | fund_type | DataFrame | 基金排名 |

**缓存机制**：
- 请求参数 MD5 → `data/cache/{hash}.json`
- TTL 12 小时 (`cache_ttl_hours`)
- 缓存命中时直接返回，不请求网络

**重试机制**：
- `fetch_with_retry`: 最多 3 次重试，指数退避 (1s, 2s, 4s)

#### `fund_data.py` — 基金数据管理

| 函数 | 说明 |
|------|------|
| `update_fund_nav(code, start_date?)` | 单基金净值更新到 DB |
| `update_fund_info(code)` | 基金信息更新到 DB |
| `get_fund_details(code)` | 合并信息 + 近期收益率 (1w/1m/3m/6m/1y) |
| `batch_update_funds(codes, start_date?)` | 批量更新 |

#### `fund_discovery.py` — 基金发现

| 函数 | 说明 |
|------|------|
| `seed_fund_universe()` | 从 config 导入种子基金到观察池 (幂等, 自动下载净值) |
| `discover_sector_funds(sector, top_n)` | 按板块名发现主题基金 (允许 ETF联接/QDII) |
| `discover_top_funds(top_n)` | 全市场综合排名筛选 |
| `update_dynamic_pool(hotspots?)` | 更新动态候选池 (热点+排名+观察池) |

#### `market_data.py` — 市场指数

| 函数 | 说明 |
|------|------|
| `update_all_indices(start_date?)` | 更新 5 个基准指数 |
| `get_latest_index_snapshot()` | 各指数最新收盘 + 涨跌幅 |

**基准指数列表**：上证指数 / 深证成指 / 创业板指 / 沪深300 / 中证500

#### 增强数据源

| 模块 | 说明 |
|------|------|
| `valuation.py` | 指数 PE/PB 分位，信号: 低估/合理/高估 |
| `macro.py` | PMI/M2/CPI → 信贷周期 (宽松/收紧/中性) |
| `sentiment.py` | 融资余额/换手率 → 情绪水平 (恐惧/中性/贪婪) |
| `fund_manager.py` | 基金经理年限/规模/业绩 → 评分/等级 (A/B/C/D) |

---

### 5.2 分析引擎 (`src/analysis/`)

#### `indicators.py` — 技术指标

| 指标 | 函数 | 默认参数 | 输出 |
|------|------|----------|------|
| 移动平均 | `calculate_ma` | [5,10,20,60,120,250] | `{"MA5": series, ...}` |
| 指数移动平均 | `calculate_ema` | [12,26] | `{"EMA12": series, ...}` |
| RSI | `calculate_rsi` | period=14 | 0-100 序列 |
| MACD | `calculate_macd` | 12,26,9 | `{"dif", "dea", "histogram"}` |
| 布林带 | `calculate_bollinger` | period=20, std=2 | `{"upper", "middle", "lower", "width"}` |
| 波动率 | `calculate_volatility` | window=20 | 年化波动率序列 |
| 夏普比率 | `calculate_sharpe_ratio` | rf=2% | float |
| 索提诺比率 | `calculate_sortino_ratio` | rf=2% | float |
| 最大回撤 | `calculate_max_drawdown` | — | (回撤%, 起始, 结束) |

**`get_technical_summary(prices)`** — 汇总函数，返回：

```python
{
    "current_price": float,
    "rsi": 43.9,
    "rsi_signal": "中性",          # 超买(>70) / 超卖(<30) / 中性
    "macd_dif": 0.0012,
    "macd_dea": 0.0008,
    "macd_histogram": 0.0004,
    "macd_signal": "金叉",         # 金叉 / 死叉 / 多头 / 空头
    "ma": {"MA5": ..., "MA10": ..., "MA20": ..., "MA60": ...},
    "ma_alignment": "多头排列",    # 多头排列 / 空头排列 / 交叉
    "bb_upper": ..., "bb_middle": ..., "bb_lower": ...,
    "bb_signal": "通道内",         # 突破上轨 / 突破下轨 / 通道内
    "bb_position": 0.65,           # 0=下轨, 1=上轨
    "volatility": 0.1334,
}
```

#### `fund_scorer.py` — 基金综合评分 (分类别阈值)

四维度评分，总分 100 分：

| 维度 | 分值 | 计算方式 |
|------|------|----------|
| 收益 | 40 分 | 近1月(15%) + 近3月(25%) + 近6月(30%) + 近1年(30%)，年化对齐后评分 |
| 风险 | 30 分 | 基础30分 - 回撤罚分(0~15) - 波动罚分(0~10) + 夏普加分(±5) |
| 稳定性 | 20 分 | 月度正收益占比：>70%满分，<30%最低 |
| 费用 | 10 分 | 申购费率越低越好，默认7分 |

**分类别阈值** (`CONFIG["scoring_targets"]`)：

评分公式中的收益目标、波动率上限、回撤上限根据基金类别动态切换：

| 类别 | 年化收益目标 | 波动率上限 | 回撤上限 | 效果 |
|------|------------|-----------|---------|------|
| equity | 20% | 40% | 30% | 偏股基金的默认标准 |
| bond | 5% | 8% | 5% | 债券年化5%即满分 |
| index | 15% | 35% | 25% | 指数宽基 |
| gold | 10% | 25% | 20% | 黄金 |
| qdii | 15% | 35% | 25% | 海外 |

分类逻辑: `classify_fund(fund_code)` → watchlist.category → 基金名称关键词 → 默认 equity。

**数据要求**：最少 60 条净值记录。

#### `market_regime.py` — 市场状态检测

基于沪深300指数，通过趋势评分 (-100 ~ +100) 判断市场状态：

| 状态 | 趋势评分 | 描述 |
|------|----------|------|
| `bull_strong` | > 40 | 强势上涨，均线多头排列 |
| `bull_weak` | 15 ~ 40 | 弱势上涨，动能减弱 |
| `ranging` | -15 ~ 15 | 震荡盘整，无明确方向 |
| `bear_weak` | -40 ~ -15 | 弱势下跌 |
| `bear_strong` | < -40 | 强势下跌，均线空头排列 |

**评分因子**：
1. 价格与 MA20/60/120 的关系 (±40)
2. 均线斜率 (±30)
3. 均线排列程度 (±30)
4. 北向资金流向 (±15) — 沪股通+深股通近5日/20日净流入
5. 资金流向综合 (±15) — 市场主力资金流+基金仓位逆向信号

#### `sector_rotation.py` — 行业热点检测

跟踪 29 个东方财富行业板块（已对齐 AKShare 命名规范），覆盖 6 大类：

| 分类 | 板块 |
|------|------|
| 大科技 | 半导体、消费电子、软件开发、计算机设备、通信设备、游戏Ⅱ、互联网电商 |
| 新能源 | 电池、光伏设备、风电设备、电力 |
| 大消费 | 白酒Ⅱ、食品饮料、医疗器械、化学制药、中药Ⅱ、乘用车、家用电器 |
| 金融周期 | 银行、证券Ⅱ、保险Ⅱ、房地产开发 |
| 制造 | 航天装备Ⅱ、航海装备Ⅱ、工程机械、专用设备 |
| 资源 | 贵金属、煤炭开采、石油石化 |

**热度评分 (0~100+)，6 个维度**：

| 维度 | 最高分 | 逻辑 |
|------|--------|------|
| 涨幅加速 | 35 | 近5日涨幅本身 + 对比前5日的加速度 |
| 成交量放大 | 25 | 近5日成交额 vs 前15日平均，>2倍满分 |
| 换手率异常 | 15 | 近5日换手率 vs 历史平均 |
| 趋势确认 | 15 | MA5 > MA10 > MA20 均线多头排列 |
| 排名上升 | 10 | 板块排名变化 |
| 资金流入 | 10 | 主力净流入金额 |

**热点分类**：

| 阶段 | 条件 | 含义 |
|------|------|------|
| `accelerating` | 评分≥70 + 加速 + 放量 | 最热阶段 |
| `emerging` | 评分≥50 + 放量或多头 | 新兴热点 |
| `peak` | 5日涨幅>8% + 未加速 | 可能见顶 |
| `fading` | 评分下降 | 衰退 |

#### `learner.py` — 自动学习引擎

**学习闭环**：

```
信号记录 → 7d/30d 验证 → 策略表现统计 → 动态权重调整
```

| 函数 | 说明 |
|------|------|
| `record_signal()` | 记录预测信号到 signal_validation 表 |
| `record_signals_from_composite()` | 批量记录综合信号 |
| `validate_pending_signals()` | 回查 7d/30d 实际收益，标记信号正确性 |
| `update_strategy_performance()` | 按策略×市场状态聚合胜率/收益 |
| `get_learned_weights()` | 计算动态策略权重 (需≥5个已验证信号) |
| `run_learning_cycle()` | 完整学习周期 (daily 流程调用) |

#### 资金流向分析 (`fund_flow.py`)

综合三大资金面指标，评分 -30 ~ +30 叠加到市场状态评分：

| 指标 | 数据源 | 评分范围 |
|------|--------|----------|
| 市场主力资金流 | `stock_market_fund_flow()` | ±15 |
| 股票基金仓位估计 | `fund_stock_position_lg()` | ±10 (逆向) |
| ETF 大额资金动向 | `fund_etf_spot_em()` | 参考 |
| 行业资金流向排行 | `stock_sector_fund_flow_rank()` | 增强热点评分 |

---

### 5.3 策略引擎 (`src/strategy/`)

#### 信号定义 (`base.py`)

```python
class SignalType(Enum):
    STRONG_BUY = "strong_buy"    # 强烈买入
    BUY = "buy"                  # 买入
    HOLD = "hold"                # 持有
    SELL = "sell"                # 卖出
    STRONG_SELL = "strong_sell"  # 强烈卖出

@dataclass
class Signal:
    fund_code: str               # 基金代码
    signal_type: SignalType      # 信号类型
    confidence: float            # 置信度 0~1
    reason: str                  # 理由说明
    strategy_name: str           # 产生信号的策略
    target_amount: float = 0     # 建议金额
    priority: int = 0            # 优先级
    metadata: dict = None        # 元数据 (含 category 等)
```

#### 趋势跟踪 (`trend_following.py`) — 主策略

**信号评分**：

| 因子 | 买入得分 | 卖出得分 |
|------|----------|----------|
| 均线多头/空头排列 | +3 / 0 | 0 / +3 |
| MACD 金叉/死叉 | +2 / 0 | 0 / +2 |
| RSI 超卖/超买 | +1 / 0 | 0 / +1 |
| 价格在 MA20 上/下方 | +1 / 0 | 0 / +1 |
| 价格在 MA60 上/下方 | +1 / 0 | 0 / +1 |
| 牛市/熊市修正 | +1 / 0 | 0 / +1 |

- 净分 ≥ 6 + 均线确认 → STRONG_BUY
- 净分 ≥ 4 + 均线确认 + 辅助确认 → BUY
- **多周期确认**：周线级别 MA4/MA8 排列确认日线信号
- 含回测功能：**8% 固定止损 + 10% 移动止盈**

#### 均值回归 (`mean_reversion.py`) — 辅助策略

**适用**：震荡市。强趋势市（bull_strong / bear_strong）自动禁用。

| 因子 | 买入得分 | 卖出得分 |
|------|----------|----------|
| RSI < 25 / > 75 | +3 / 0 | 0 / +3 |
| RSI < 35 / > 65 | +1 / 0 | 0 / +1 |
| 跌破/突破布林带 | +2 / 0 | 0 / +2 |
| 偏离 MA20 < -5% / > 5% | +2 / 0 | 0 / +2 |

#### 动量策略 (`momentum.py`) — 辅助策略 (v2 多维评分)

**多维动量评分体系**：
1. **夏普动量** — 风险调整后的动量 (核心因子, 权重 x10)
2. **原始动量** — 60 日收益率，剔除最近 5 天短期反转噪音 (辅助, x0.3)
3. **路径质量** — 上涨一致性 (正收益比例 70% + 连续下跌惩罚 30%, x10)
4. **动量加速** — 短期(20日) vs 长期(60日) 动量对比 (加速奖励 +5)

#### 估值策略 (`valuation.py`) — 核心增强 (权重 0.25)

基于 PE/PB 分位驱动：低估时加仓，高估时减仓。数据来源：`data/valuation.py`。

#### 宏观周期策略 (`macro_cycle.py`) — 辅助 (权重 0.10)

根据 PMI/M2/CPI 推导的信贷周期 (宽松/收紧/中性) 决定偏向。数据来源：`data/macro.py`。

#### 经理 Alpha 策略 (`manager_alpha.py`) — 微调 (权重 0.05)

基金经理评分高的基金给予小幅加成。数据来源：`data/fund_manager.py`。

#### 综合信号 (`portfolio.py`)

```
学习权重 (如有) 或 默认权重 → 6 策略信号 → 加权合并 → 冲突检测 → 按优先级排序
```

- 每只基金汇总加权后的买入/卖出得分
- 净得分 > 0.5 → STRONG_BUY，> 0.2 → BUY
- 净得分 < -0.5 → STRONG_SELL，< -0.2 → SELL
- **策略冲突检测**：当买入和卖出策略同时存在时，置信度按冲突比例惩罚（最多降 50%）
- **季节性修正**：根据 A 股日历效应调整信号置信度（±0.2 范围）
- **每个信号携带 `metadata.category`**：equity / bond / index / gold / qdii

#### 季节性因子 (`seasonal.py`)

8 种 A 股日历效应，返回 -0.2 ~ +0.2 的置信度修正因子：

| 效应 | 时段 | 方向 | 幅度 |
|------|------|------|------|
| 春节红包行情 | 1/20-2/10 | 看多 | +0.10 |
| 两会维稳期 | 3/1-3/15 | 看多 | +0.05 |
| 财报季波动 | 4/8/10月中下旬 | 看空 | -0.10 |
| 年末基金粉饰 | 12/15-12/31 | 看多 | +0.05 |
| 月末资金紧张 | 每月28-31日 | 看空 | -0.05 |
| 开门红效应 | 1/1-1/7 | 看多 | +0.05 |
| 国庆后效应 | 10/1-10/12 | 看多 | +0.05 |
| 五穷六绝 | 5-6月 | 看空 | -0.05 |

#### 高级回测

| 模块 | 说明 |
|------|------|
| `walk_forward.py` | 走前验证: 滚动训练窗口 + 测试窗口, 消除过拟合 |
| `monte_carlo.py` | 蒙特卡洛模拟: 随机路径生成, 统计风险分布 |

---

### 5.4 LLM 智能体层 (`src/agent/`)

#### 架构

```
量化信号 + 资产配置偏差 → Flash/Haiku 市场摘要 → Pro/Opus 三步决策 → 报告
                                                                       ↓
知识库 ← 教训提炼 ← Pro/Sonnet 反思复盘 (7d/30d) ← 实际结果对比
  ↓
  └→ 注入未来决策上下文 (知识驱动进化)
```

#### 模型配置 (双后端)

| 场景 | Gemini | Anthropic |
|------|--------|-----------|
| 市场摘要 | Flash | Haiku 4.5 |
| 决策/反思 | Pro | Sonnet 4.5 |
| 核心决策/辩论裁判 | Pro | Opus 4.6 |

通过 `.env` 中 `LLM_PROVIDER=gemini|anthropic` 切换，运行时 `uv run pixiu llm <provider>` 切换。

#### 决策流程

1. **Haiku/Flash 市场摘要** — 综合指数/资金/热点/估值/宏观/情绪
2. **Opus/Pro 三步决策** — 形成假设 → 自我挑战 → 最终定论
3. **跨资产配置** — LLM 上下文包含各类别信号汇总 + 当前/目标配置比例
4. **持久化** — 决策存入 agent_decisions，教训存入 knowledge_base
5. **7/30d 复盘** — 自动触发 LLM 反思，提炼可操作教训
6. **知识注入** — 未来决策时检索历史教训作为上下文

#### 高级功能

| 模块 | 说明 |
|------|------|
| `scenario.py` | 场景推演: 牛/基/熊三情景 + 概率分配 + 期望收益 |
| `debate.py` | 多角色辩论: 乐观派/悲观派/裁判, 碰撞出更稳健结论 |

#### 成本控制

无 API Key 时自动回退到纯量化模式，不影响现有功能。月成本约 $8-10。

---

### 5.5 风险管理 (`src/risk/`)

#### `position_sizing.py` — 仓位计算

**半凯利公式**：

```
f* = (b × p - q) / b × 0.5
其中: b = 平均盈利/平均亏损, p = 胜率, q = 1-p
```

**实际仓位计算**：

```
可用资金 = 现金 - 最低现金保留(10%)
基础比例 = 市场状态乘数 × 置信度
    强牛 0.90, 弱牛 0.70, 震荡 0.50, 弱熊 0.35, 强熊 0.20
仓位调整:
    已有 ≥3 个持仓 → 乘以 0.5
    已有 ≥2 个持仓 → 乘以 0.7
最终金额 = min(可用资金 × 基础比例, 总资产 × 30%)
最小交易 = 100 RMB
```

#### `drawdown.py` — 回撤监控

| 级别 | 回撤阈值 | 建议操作 |
|------|----------|----------|
| `normal` | < 5% | 正常操作 |
| `warning` | 5% ~ 10% | 谨慎操作，不建议加仓，准备减仓 |
| `critical` | > 10% | 立即减仓至 50% 以下，暂停买入 |

**单基金止损**：亏损 > 8% 触发卖出建议。

#### `cost_calculator.py` — 费用计算

**申购费**（支付宝 1 折）：1.50% → 0.15%

**赎回费**（按持有天数分档）：

| 持有天数 | 赎回费率 |
|----------|----------|
| < 7 天 | 1.50% (惩罚性) |
| 7 ~ 30 天 | 0.75% |
| 30 天 ~ 1 年 | 0.50% |
| 1 ~ 2 年 | 0.25% |
| > 2 年 | 0% |

#### `asset_allocation.py` — 资产配置保护层

**硬性底线 (不可违反)**：

| 规则 | 值 |
|------|-----|
| 股票型基金上限 | ≤ 70% |
| 现金/货币基金下限 | ≥ 20% |
| 债券基金下限 | ≥ 10% |

**按市场状态动态调整目标配比**：

| 市场状态 | 偏股 | 债券 | 现金 |
|----------|------|------|------|
| 强牛 | 60% | 15% | 25% |
| 弱牛 | 55% | 20% | 25% |
| 震荡 | 45% | 25% | 30% |
| 弱熊 | 35% | 30% | 35% |
| 强熊 | 25% | 35% | 40% |

**估值修正**：PE 分位 <20% → 加股减债减现; >80% → 减股加债加现。

---

### 5.6 记忆系统 (`src/memory/`)

#### `database.py` — 数据库 Schema

18+ 张表：

| 表名 | 主键 | 用途 |
|------|------|------|
| `funds` | fund_code | 基金基本信息 |
| `fund_nav` | (fund_code, nav_date) | 净值历史 |
| `market_indices` | (index_code, trade_date) | 指数历史 |
| `portfolio` | id (自增) | 持仓记录 (holding/sold) |
| `trades` | id (自增) | 交易记录 (pending/executed/cancelled) |
| `account_snapshots` | snapshot_date | 每日账户快照 |
| `analysis_log` | id (自增) | 分析日志 |
| `watchlist` | fund_code | 观察池 (**含 `category` 列**: equity/bond/index/gold/qdii) |
| `sector_snapshots` | (sector_code, snapshot_date) | 行业板块每日快照 |
| `hotspots` | id (自增) | 热点记录 (active/expired) |
| `signal_validation` | id (自增) | 信号预测 → 7d/30d 验证 |
| `strategy_performance` | (strategy_name, regime) | 策略表现聚合 |
| `agent_decisions` | id (自增) | LLM 决策记录 (市场上下文/量化信号/分析/推理) |
| `reflections` | id (自增) | 反思日志 (7d/30d 复盘/对错/教训) |
| `knowledge_base` | id (自增) | 知识库 (教训积累/验证次数/活跃状态) |
| `index_valuation` | (index_code, trade_date) | 指数估值 (PE/PB/分位) |
| `macro_indicators` | (indicator_name, report_date) | 宏观经济指标 |
| `fund_managers` | manager_id | 基金经理信息 |
| `sentiment_indicators` | (indicator_name, trade_date) | 情绪指标 |
| `scenario_analysis` | id (自增) | LLM 场景推演 |

数据库选项：WAL 日志模式，外键约束开启。

**重要函数**: `classify_fund(fund_code, fund_name?)` — 基金分类 (watchlist.category → 关键词 → 默认 equity)。

#### `trade_journal.py` — 交易统计

统计已执行交易的胜率、平均盈亏、交易次数。

#### `context.py` — 上下文构建

汇总当前系统完整状态，包括：账户信息、持仓详情、交易统计、最近分析记录、最新快照、观察池、风险参数。

---

### 5.7 报告系统 (`src/report/`)

#### 报告类型

| 类型 | 文件名格式 | 触发命令 |
|------|------------|----------|
| 交易建议 | `YYYYMMDDHHmm_recommendation.md` | `recommend` / `daily` |
| 组合状态 | `YYYYMMDDHHmm_portfolio.md` | `daily` |

报告存储路径：`reports/YYYY-MM/`

#### 交易建议报告结构

```markdown
# 交易建议报告 — {日期}

## LLM 智能分析
### 市场研判 / 初步判断 / 自我挑战 / 最终结论
### 组合建议
LLM 情绪 / Token 消耗

## 操作建议: {买入/卖出/持有}
| 操作 | 基金名称 | 建议金额 | 置信度 |

### 分析依据 / LLM 洞察 / 技术面 / 风险评估 / 费用明细 / 操作步骤

## 资产配置                    ← 新增
| 资产类别 | 当前 | 目标 | 偏差 |

## 市场环境
| 指数 | 收盘价 | 涨跌幅 |
### 资金面

## 账户状态
总资产 / 现金 / 已投资 / 回撤
```

---

### 5.8 调度器 (`src/scheduler/`)

- 工作日 (周一至周五) 15:45 自动执行 `daily` 流程
- 60 秒轮询间隔
- `Ctrl+C` 优雅退出

---

## 六、配置参数

所有配置集中在 `src/config.py` 的 `CONFIG` 字典中：

### 6.1 账户参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `initial_capital` | 10,000 | 初始资金 (RMB) |
| `current_cash` | 10,000 | 当前现金 (RMB) |

### 6.2 风险参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `max_single_position_pct` | 30% | 单基金最大仓位 |
| `max_total_position_pct` | 90% | 最大总仓位 |
| `min_cash_reserve_pct` | 10% | 最低现金保留 |
| `max_drawdown_soft` | 5% | 软性回撤警报 |
| `max_drawdown_hard` | 10% | 硬性止损回撤 |
| `single_fund_stop_loss` | 8% | 单基金止损线 |
| `kelly_fraction` | 0.5 | 半凯利系数 |

### 6.3 费用参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `subscription_fee_discount` | 0.1 | 申购费折扣 (支付宝 1 折) |
| `short_term_penalty_days` | 7 | 短期惩罚天数 |
| `short_term_penalty_rate` | 1.5% | 7 天内赎回费 |

### 6.4 系统参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `cache_ttl_hours` | 12 | 缓存有效期 |
| `db_path` | `db/pixiu.db` | 数据库路径 |
| `cache_dir` | `data/cache` | 缓存目录 |
| `reports_dir` | `reports` | 报告目录 |

### 6.5 LLM 配置

| 参数 | 值 | 说明 |
|------|-----|------|
| `llm.provider` | `"gemini"` | 默认后端, 运行时从 .env 覆盖 |
| `llm.gemini.analysis_model` | `gemini-2.0-flash` | 市场摘要 |
| `llm.gemini.decision_model` | `gemini-2.5-pro` | 决策/反思 |
| `llm.gemini.critical_model` | `gemini-2.5-pro` | 核心决策 |
| `llm.anthropic.analysis_model` | `claude-haiku-4-5` | 市场摘要 |
| `llm.anthropic.decision_model` | `claude-sonnet-4-5` | 决策/反思 |
| `llm.anthropic.critical_model` | `claude-opus-4-6` | 核心决策 |

### 6.6 基金池配置

`fund_universe` — 5 大资产类别种子基金池：

| 类别 | 基金 |
|------|------|
| equity | 空 (通过 watchlist 自动发现) |
| bond | 217022 招商产业债A / 110017 易方达增强回报债A / 003376 广发国开债指数A / 070009 嘉实超短债C / 006662 易方达安悦超短债A |
| index | 110020 沪深300联接A / 000962 中证500联接A / 001593 创业板联接C |
| gold | 000307 易方达黄金联接A / 002610 博时黄金联接A |
| qdii | 270042 纳斯达克100联接A / 050025 标普500联接A / 161125 标普500指数A |

`scoring_targets` — 分类别评分阈值：见 5.2 节 fund_scorer 部分。

---

## 七、快速上手

### 7.1 安装

```bash
# 1. 安装 uv
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. 进入项目目录
cd D:\project\pixiu-claude

# 3. 同步依赖 (自动下载 Python 3.12 + 所有包)
uv sync

# 4. 配置 LLM API Key (可选, 无则纯量化模式)
# 复制 .env.example → .env, 填入 ANTHROPIC_API_KEY 或 GEMINI_API_KEY
```

### 7.2 首次运行

```bash
# 更新数据 (首次会下载近1年数据，约2分钟)
uv run pixiu update

# 查看市场分析
uv run pixiu analyze

# 生成交易建议
uv run pixiu recommend

# 或一键完成全流程 (10 步)
uv run pixiu daily
```

### 7.3 日常使用

```bash
# 每天收盘后运行 (全量智能体, 10 步)
uv run pixiu daily

# 查看行业热点
uv run pixiu hotspot

# 查看资产配置状态
uv run pixiu allocation

# 查看 LLM 配置和基金池统计
uv run pixiu llm

# 查看学习进化报告
uv run pixiu learn

# 添加感兴趣的基金到观察池
uv run pixiu watchlist add 001938 医药主题

# 查看某只基金详情
uv run pixiu fund 001938

# 记录已执行的交易
uv run pixiu record-trade

# 查看持仓和收益
uv run pixiu portfolio

# LLM 高级分析
uv run pixiu scenario       # 场景推演
uv run pixiu debate          # 多角色辩论
```

### 7.4 自动化

```bash
# 启动定时调度器 (工作日 15:45 自动分析)
uv run pixiu schedule
```

---

## 八、依赖清单

| 包 | 版本 | 用途 |
|---|---|---|
| akshare | ≥1.18.25 | 中国基金/股票/宏观数据获取 |
| pandas | ≥3.0.1 | 数据分析、时间序列 |
| numpy | ≥2.4.2 | 数值计算、技术指标 |
| scipy | ≥1.17.0 | 统计分析 |
| rich | ≥14.3.3 | CLI 表格美化输出 |
| tabulate | ≥0.9.0 | 表格格式化 |
| schedule | ≥1.2.2 | 轻量级定时任务 |
| requests | ≥2.32.5 | HTTP 请求 |
| anthropic | (可选) | Claude API |
| google-genai | (可选) | Gemini API |

---

## 九、基金池 — 5 大资产类别

当前基金池 **26 只**，覆盖 5 大资产类别：

| 类别 | 数量 | 来源 | 代表基金 | 作用 |
|------|------|------|----------|------|
| 偏股 | 13 | 自动发现 (热点+排名) | 华夏能源革新、红土创新新兴产业 | 进攻 |
| 债券 | 5 | 种子池 | 招商产业债A、易方达超短债A | 防守 |
| 指数 | 3 | 种子池 | 沪深300联接A、中证500联接A | 核心配置 |
| 黄金 | 2 | 种子池 | 易方达黄金联接A、博时黄金联接A | 避险 |
| QDII | 3 | 种子池 | 纳斯达克100联接A、标普500联接A | 海外分散 |

种子池由 `CONFIG["fund_universe"]` 定义，通过 `seed_fund_universe()` 幂等导入。

观察池为空时的默认基金（兜底）：110011 易方达优质精选 / 161725 招商白酒 / 003834 华夏能源革新 / 005827 易方达蓝筹精选 / 320007 诺安成长。

---

## 十、输出示例

### 10.1 观察池 (含类别)

```
分类统计: 债券 5 | 偏股 13 | 黄金 2 | 指数 3 | QDII 3 | 合计 26

                                 观察池
┌──────────┬──────┬────────────┬──────────┬─────────────────────────────┐
│ 基金代码 │ 类别 │ 添加日期   │ 目标操作 │ 备注                        │
├──────────┼──────┼────────────┼──────────┼─────────────────────────────┤
│ 217022   │ 债券 │ 2026-02-20 │ watch    │ seed:bond                   │
│ 000307   │ 黄金 │ 2026-02-20 │ watch    │ seed:gold                   │
│ 270042   │ QDII │ 2026-02-20 │ watch    │ seed:qdii                   │
│ ...      │ ...  │ ...        │ ...      │ ...                         │
└──────────┴──────┴────────────┴──────────┴─────────────────────────────┘
```

### 10.2 市场分析

```
                 市场指数概况
┌──────────┬───────────┬────────┬────────────┐
│ 指数     │ 收盘价    │ 涨跌幅 │ 日期       │
├──────────┼───────────┼────────┼────────────┤
│ 上证指数 │ 4,082.07  │ -1.26% │ 2026-02-20 │
│ ...      │ ...       │ ...    │ ...        │
└──────────┴───────────┴────────┴────────────┘

市场状态: ranging — 震荡盘整 — 无明确方向，均线交织
  趋势得分: 12.5  波动率: 13.34%
```

### 10.3 LLM 配置

```
═══ LLM 配置 ═══

  当前后端: anthropic
  分析模型: claude-haiku-4-5  (市场摘要)
  决策模型: claude-sonnet-4-5  (反思/情景)
  关键模型: claude-opus-4-6  (核心决策/辩论裁判)

  基金池: 债券 5 | 偏股 13 | 黄金 2 | 指数 3 | QDII 3 | 合计 26
```

---

## 十一、回测结果

基于趋势跟踪策略回测：

| 指标 | 数值 |
|------|------|
| 总收益率 | +9.94% |
| 最大回撤 | -10.30% |
| 交易次数 | 14 |
| 盈利次数 | 4 |
| 胜率 | 66.7% |

**风控机制已验证**：
- 8% 固定止损和 10% 移动止盈有效限制了单笔亏损
- 最大回撤从优化前的 -42.29% 降至 -10.30%
- 胜率从 31% 提升至 66.7%

---

## 十二、自动学习进化

系统具备持续学习能力，通过以下闭环不断优化：

```
每日信号 → 记录预测 → 7天/30天后验证 → 统计策略表现 → 动态调整权重
```

1. **信号记录**：每次 `recommend` 生成的信号自动记录到 `signal_validation` 表
2. **定期验证**：`learn` 命令回查历史信号的 7d/30d 实际收益
3. **胜率统计**：按 策略×市场状态 维度统计每个策略的胜率和平均收益
4. **权重调整**：当某策略在特定市场状态下积累≥5个已验证信号后，自动用学习后的权重替代默认权重
5. **渐进优化**：随着数据积累，系统会逐步发现哪些策略在哪种市场环境下表现更好

---

## 十三、技术文档索引

| 文档 | 说明 |
|------|------|
| `docs/202602201430-pixiu-system-design.md` | 初始架构设计 (Phase 1-5 实现计划) |
| `docs/202602201445-pixiu-project-documentation.md` | 本文档 (项目全量参考) |
| `docs/202602201830-llm-agent-layer.md` | LLM 智能体层设计方案 |
| `docs/202602211000-fund-universe-expansion.md` | 基金池扩容: 5 大资产类别 |
