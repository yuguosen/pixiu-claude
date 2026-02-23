# 飞书机器人集成

> 日期：2026-02-23 15:15
> 作者：Claude Code
> 状态：已实现

## 背景与目标

貔貅系统此前仅支持 CLI 交互，日常使用需要 SSH 到服务器或打开终端手动执行命令。对于每日收盘后的例行分析流程（`daily` 11 步），缺乏自动触发和移动端查看能力。

**目标**：接入飞书机器人，实现：
1. 命令式交互 — 在飞书对话中发送中文/斜杠命令，获取市场行情、持仓、交易建议等
2. 消息卡片展示 — 结构化卡片替代纯文本，适配移动端阅读
3. 定时推送 — 工作日 15:50 自动执行日报并推送到指定群
4. 多步交易录入 — 通过对话式状态机完成交易记录，无需 CLI 的 `input()` 交互
5. 24/7 运行 — WebSocket 长连接模式，Mac/服务器均可运行，无需公网 IP

## 现状分析

### 已有能力
- `src/main.py` 提供 26+ 个 CLI 命令，覆盖数据更新、市场分析、交易建议、持仓查询、资产配置等
- `src/scheduler/jobs.py` 有基于 `schedule` 库的定时调度基础
- 所有业务逻辑封装在独立模块中（`report/`, `analysis/`, `strategy/`, `memory/`, `risk/`, `agent/`），可被外部调用

### 局限性
- CLI 命令使用 Rich Console 输出，绑定终端环境
- `cmd_record_trade()` 使用 `input()` 阻塞式交互，无法在机器人场景使用
- 无消息推送能力，需人工触发所有操作

### 设计决策
- **WebSocket 长连接** vs Webhook：选择 WebSocket，因为无需公网 IP/域名，本地 Mac 即可运行
- **卡片消息** vs 纯文本：选择卡片，支持表格、颜色、分栏，移动端体验更好
- **适配层模式** vs 重写：选择在现有模块上加适配层，handlers 直接 import 调用现有函数，不重写业务逻辑

## 方案设计

### 架构

```
飞书服务器 ←WebSocket长连接→ pixiu-bot 进程
                                  │
                  ┌───────────────┼───────────────┐
                  │               │               │
           消息路由器        定时调度器        会话管理器
           (router.py)     (app.py内)       (session.py)
                  │               │               │
                  └───────┬───────┘               │
                          ▼                       │
                   业务适配层 (handlers.py)  ←─────┘
                          │
                          ▼
                   现有 Pixiu 模块
          (report/ analysis/ strategy/ memory/ agent/)
```

**进程模型**：单进程多线程
- 主线程：WebSocket 客户端（`lark.ws.Client.start()` 阻塞）
- 守护线程 1：定时调度器（`schedule` 库，每 30 秒检查待执行任务）
- 临时线程：耗时命令（`recommend`/`daily`）在独立线程执行，避免阻塞消息处理

### 新增文件

```
src/bot/
├── __init__.py        # 包初始化
├── app.py             # 入口: 加载 .env, 初始化飞书客户端, 启动调度器, WebSocket 阻塞
├── router.py          # 命令解析 (中英文映射) + 分发 + 耗时命令线程化
├── handlers.py        # 业务适配层 (调用现有函数, 返回卡片 dict)
├── cards.py           # 飞书消息卡片构建器 (14 种模板)
├── sender.py          # 消息发送工具 (reply/send/update)
└── session.py         # 多步会话状态机 (交易录入 7 步)
```

### 数据流

#### 只读命令（如"持仓"）

```
用户发送"持仓"
  → 飞书服务器 → WebSocket → router.py._extract_text()
  → _parse_command("持仓") → ("portfolio", [])
  → handlers.handle_portfolio()
      → database.execute_query("SELECT * FROM portfolio ...")
      → cards.portfolio_card(holdings, cash, ...)
  → sender.reply_card(client, message_id, card)
  → 飞书服务器 → 用户收到持仓卡片
```

#### 耗时命令（如"建议"）

```
用户发送"建议"
  → router → 识别为 LONG_RUNNING_COMMANDS
  → sender.reply_card(processing_card("生成交易建议"))  ← 立即回复
  → threading.Thread(_run_long_command, "recommend")     ← 后台线程
      → handlers.handle_recommend()
          → recommendation.generate_recommendation()  (数分钟)
          → cards.recommendation_card(report_path, recs)
      → sender.reply_card(client, message_id, result_card)
  → 用户收到建议卡片
```

#### 多步交易录入

```
用户发送"记录"
  → router → session_manager.start_trade_session(user_id)
  → reply_card(trade_prompt_card("第1步", "请输入基金代码"))

用户发送"110011"
  → router → session_manager.has_active_session() → True
  → session.process("110011") → 校验通过 → 返回下一步提示
  → reply_card(trade_prompt_card("第2步", "买入还是卖出?"))

... (共 6 步输入 + 1 步确认)

用户发送"确认"
  → session.process("确认") → ("success", trade_data)
  → handlers.handle_trade_record(trade_data)
      → database.execute_write(INSERT INTO trades ...)
      → database.execute_write(INSERT INTO portfolio ...)  (buy 时)
  → reply_card(trade_success_card(trade_data))
```

### 命令路由

| 用户输入 | 内部命令 | 类型 | Handler |
|---------|---------|------|---------|
| 帮助 / /help / help | `help` | 即时 | `handle_help()` |
| 行情 / /market / 市场 | `market` | 即时 | `handle_market()` |
| 持仓 / /portfolio / 组合 | `portfolio` | 即时 | `handle_portfolio()` |
| 历史 [N] / /history / 交易 | `history` | 即时 | `handle_history(limit)` |
| 配置 / /allocation / 资产配置 | `allocation` | 即时 | `handle_allocation()` |
| 建议 / /recommend / 推荐 | `recommend` | 耗时 | `handle_recommend()` |
| 日报 / /daily | `daily` | 耗时 | `handle_daily()` |
| 记录 / /trade | `trade` | 多步会话 | `SessionManager` |
| 无法识别 | — | — | 回复帮助卡片 |

### 卡片模板（14 种）

| 模板 | 颜色 | 用途 |
|------|------|------|
| `help_card` | purple | 命令列表 |
| `processing_card` | wathet (浅蓝) | 耗时操作等待提示 |
| `error_card` | red | 错误提示 |
| `portfolio_card` | blue | 持仓表格 + 盈亏汇总 |
| `history_card` | blue | 交易历史表格 |
| `market_card` | green/yellow/red (随市场状态) | 指数概况 + 市场状态 |
| `recommendation_card` | green/red/blue (随买卖方向) | 交易建议 + 置信度 |
| `daily_summary_card` | green/red | 日报完成/失败摘要 |
| `allocation_card` | blue | 资产配置表格 + 合规状态 |
| `trade_prompt_card` | indigo | 交易录入步骤提示 |
| `trade_confirm_card` | indigo | 交易确认（含全部信息） |
| `trade_success_card` | green | 交易记录成功 |

所有卡片采用飞书卡片 v1 JSON 结构：
```json
{
  "config": {"wide_screen_mode": true},
  "header": {"title": {"tag": "plain_text", "content": "标题"}, "template": "blue"},
  "elements": [
    {"tag": "markdown", "content": "**加粗** 表格等"},
    {"tag": "hr"}
  ]
}
```

### 会话状态机

交易录入采用 `TradeSession` 数据类管理 7 步流程：

```
step 0: fund_code  → 校验 6 位数字
step 1: action     → buy/sell/买入/卖出
step 2: amount     → 正数浮点
step 3: nav        → 正数浮点
step 4: trade_date → YYYY-MM-DD 或 "今天"
step 5: reason     → 自由文本或 "跳过"
step 6: confirm    → 确认/取消
```

- `SessionManager` 以 `user_id` 为 key 的内存字典存储会话
- 5 分钟无操作自动过期
- 任何步骤输入 "取消" 立即中止
- 输入校验失败不推进步骤，返回错误提示

### 定时调度

```python
schedule.every().day.at("15:50").do(daily_job)
```

- 守护线程每 30 秒检查 `schedule.run_pending()`
- `daily_job` 仅在工作日（`weekday() < 5`）执行
- 执行流程：发送"处理中"卡片 → `handle_daily()` → 发送结果卡片
- 需要配置 `FEISHU_PUSH_CHAT_ID` 环境变量指定目标群

### 环境变量

```
FEISHU_APP_ID=cli_xxxxxxxxxx        # 飞书应用 ID（必须）
FEISHU_APP_SECRET=xxxxxxxxxx        # 飞书应用密钥（必须）
FEISHU_PUSH_CHAT_ID=oc_xxxxxxxxxx   # 日报推送群 ID（可选）
```

## 影响范围

### 新增
- `src/bot/` 包（7 个文件，约 34KB）
- `pyproject.toml` 新增 `lark-oapi>=1.3.0` 依赖 + `pixiu-bot` 入口
- `.env` 新增 3 个飞书配置变量

### 修改
- `CLAUDE.md` 更新技术栈、项目结构、新增飞书机器人文档段落

### 未修改
- 所有现有业务模块（`main.py`, `report/`, `analysis/`, `strategy/`, `memory/`, `risk/`, `agent/`）零改动
- 现有 CLI 入口 `pixiu` 不受影响，两个入口完全独立

### 依赖关系

```
src/bot/app.py
  ├─ lark_oapi (新增外部依赖)
  ├─ schedule (已有依赖)
  ├─ src.memory.database.init_db
  ├─ src.bot.router
  ├─ src.bot.sender
  └─ src.bot.cards

src/bot/handlers.py
  ├─ src.config.CONFIG
  ├─ src.memory.database (execute_query, execute_write)
  ├─ src.data.market_data (get_latest_index_snapshot)
  ├─ src.analysis.market_regime (detect_market_regime)
  ├─ src.report.recommendation (generate_recommendation)
  ├─ src.risk.asset_allocation (check_allocation_compliance)
  ├─ src.data.valuation (get_valuation_signal)
  └─ src.main.cmd_daily
```

## 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| WebSocket 断线 | 机器人离线 | `lark-oapi` SDK 内置自动重连机制 |
| 耗时命令阻塞 | 其他消息延迟 | 耗时命令在独立线程执行，主线程不阻塞 |
| 多用户并发 | 会话混乱 | `SessionManager` 按 `user_id` 隔离 |
| 会话泄漏 | 内存增长 | 5 分钟自动过期 + 检查时清理 |
| 飞书 API 限流 | 消息发送失败 | 错误日志记录，不影响主流程 |
| 日报推送失败 | 用户未收到通知 | 错误日志记录，下次定时仍会触发 |
| SQLite 并发写入 | 数据竞争 | Python GIL + SQLite WAL 模式在低并发下安全 |

## 实现计划

已全部实现，分为 4 个阶段：

### Phase 1: 基础框架 + 只读命令 ✅
- 创建 7 个文件
- 命令：help, portfolio, history, market
- 验证：所有 imports 通过，14 种卡片模板生成合法 JSON

### Phase 2: 分析命令 ✅
- 命令：recommend, daily, allocation
- 耗时命令在独立线程执行 + "处理中"提示

### Phase 3: 交易录入 ✅
- 多步会话状态机（7 步）
- 输入校验 + 超时 + 取消
- 写入 trades + portfolio 表

### Phase 4: 定时推送 ✅
- 工作日 15:50 自动触发
- 推送到 `FEISHU_PUSH_CHAT_ID` 配置的群

### 激活步骤

1. 登录 [飞书开放平台](https://open.feishu.cn) → 创建企业自建应用
2. 添加"机器人"能力
3. 权限：开启 `im:message`, `im:message:send_as_bot`, `im:resource`
4. 事件订阅：添加 `im.message.receive_v1`，选择"使用长连接接收事件"
5. 发布应用，获取 App ID + App Secret
6. 填入 `.env`
7. 运行 `uv run pixiu-bot`
