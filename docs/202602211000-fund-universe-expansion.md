# 基金池扩容：从纯偏股到全资产配置

> 日期：2026-02-21 10:00
> 作者：Claude Code
> 状态：已实现

## 背景与目标

**问题**：候选池只有 13 只偏股型基金，涨跌高度同步，缺乏对冲能力。资产配置模块报警"债券 0% < 底线 10%"，但池子里没有债券基金可选。

**目标**：扩展基金池覆盖 5 大资产类别（偏股 / 债券 / 指数 / 黄金 / QDII），让系统具备跨资产配置能力。

**原则**：
- 量化分析管道尽量不动，靠分类别设置阈值适配
- LLM（Opus）做跨资产配置的核心裁判
- 不过度工程化债券策略，先跑通再优化

## 现状分析

改动前：
- watchlist 表无 `category` 字段，所有基金隐式当作偏股型
- `fund_scorer.py` 用固定阈值（年化 20%）打分，债券基金必然零分
- `discover_sector_funds()` 过滤掉 ETF/QDII，不允许非偏股进入候选池
- LLM 决策上下文不包含资产配置信息

## 方案设计

### 改动文件

| 文件 | 改动 |
|------|------|
| `src/config.py` | 新增 `fund_universe` 种子池 (13 只) + `scoring_targets` (分类别阈值) |
| `src/memory/database.py` | watchlist 加 `category` 列 + `classify_fund()` 分类函数 |
| `src/data/fund_discovery.py` | 新增 `seed_fund_universe()` + 放开 ETF联接/QDII 过滤 |
| `src/analysis/fund_scorer.py` | `score_fund()` 根据 category 切换评分阈值 |
| `src/strategy/portfolio.py` | 信号 metadata 携带 `category` 标签 |
| `src/report/recommendation.py` | LLM 上下文注入分类信号汇总 + 配置偏差 |
| `src/report/templates.py` | 报告新增「资产配置」段落 |
| `src/agent/brain.py` | 信号文本加 `[category]` 前缀 + 注入 allocation_context |
| `src/main.py` | daily 自动种子导入；watchlist 显示类别列；llm 显示池统计 |

### 基金分类逻辑 (`classify_fund`)

```
1. 查 watchlist.category → 有则直接返回
2. 查 funds.fund_name → 关键词匹配:
   - "黄金"/"贵金属" → gold
   - "QDII"/"标普"/"纳斯达克" → qdii
   - "债"/"纯债"/"短债"/"利率" → bond
   - "ETF联接"/"指数" → index
   - 默认 → equity
```

### 分类别评分阈值

| 类别 | 年化收益目标 | 波动率上限 | 回撤上限 |
|------|------------|-----------|---------|
| equity | 20% | 40% | 30% |
| bond | 5% | 8% | 5% |
| index | 15% | 35% | 25% |
| gold | 10% | 25% | 20% |
| qdii | 15% | 35% | 25% |

**效果**：债券基金年化 5% 从零分变为满分区间。

### 种子基金池

| 类别 | 数量 | 基金 |
|------|------|------|
| bond | 5 | 招商产业债A、易方达增强回报债A、广发国开债指数A、嘉实超短债C、易方达安悦超短债A |
| index | 3 | 易方达沪深300联接A、天弘中证500联接A、天弘创业板联接C |
| gold | 2 | 易方达黄金联接A、博时黄金联接A |
| qdii | 3 | 广发纳斯达克100联接A、博时标普500联接A、易方达标普500指数A |
| equity | 13 (已有) | 通过热点发现和全市场筛选自动进入 |
| **合计** | **26** | |

## 影响范围

- 数据库 schema 变更：watchlist 表新增 `category` 列（自动迁移兼容旧数据）
- 评分逻辑变更：债券/黄金/QDII 基金评分将显著提升
- LLM 决策变更：Opus 将看到跨资产信号和配置偏差，可能给出"买债券"建议
- daily 流程：步骤 2b 自动导入种子池
- 报告变更：新增「资产配置」段落（当前 vs 目标 vs 偏差）

## 验证结果

| 测试项 | 结果 |
|--------|------|
| 模块全量导入 | 通过 |
| classify_fund 关键词匹配 | 黄金→gold, 债→bond, ETF联接→index, 标普→qdii, 其他→equity |
| watchlist category 列迁移 | 通过（旧库自动 ALTER TABLE） |
| seed_fund_universe 幂等性 | 首次 13 只新增，二次 "已就绪" |
| 债券基金评分 | 217022 得 77.7 分（旧阈值下约 30 分） |
| 黄金基金评分 | 000307 得 79.4 分 |
| watchlist 分类显示 | 5 大类 26 只，类别列正常 |
| llm 池统计 | "债券 5 | 偏股 13 | 黄金 2 | 指数 3 | QDII 3 | 合计 26" |

## 后续迭代方向

1. **债券策略优化**：当前债券基金仍跑偏股策略（趋势/动量），效果有限，可考虑专用的久期/利差策略
2. **资产配置再平衡**：自动生成"卖偏股买债券"的再平衡建议
3. **黄金避险触发**：在市场恐慌时自动提高黄金配置权重
4. **QDII 汇率因子**：人民币贬值时 QDII 有汇率收益，可作为额外信号
5. **种子池自动更新**：定期用 AKShare 排名更新种子池中的具体基金
