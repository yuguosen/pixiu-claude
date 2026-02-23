"""飞书消息卡片构建器 — 使用飞书原生 table 组件"""


def _card(title: str, color: str, elements: list[dict]) -> dict:
    """构建飞书卡片基础结构"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        },
        "elements": elements,
    }


def _md(content: str) -> dict:
    return {"tag": "markdown", "content": content}


def _hr() -> dict:
    return {"tag": "hr"}


def _table(columns: list[dict], rows: list[dict], page_size: int = 20) -> dict:
    """构建飞书原生表格组件"""
    return {
        "tag": "table",
        "page_size": page_size,
        "row_height": "low",
        "header_style": {
            "text_align": "center",
            "text_size": "normal",
            "background_style": "grey",
            "text_color": "default",
            "bold": True,
            "lines": 1,
        },
        "columns": columns,
        "rows": rows,
    }


def _col(name: str, display_name: str, width: str = "auto", align: str = "left") -> dict:
    """构建表格列定义"""
    return {
        "name": name,
        "display_name": display_name,
        "data_type": "text",
        "width": width,
        "horizontal_align": align,
    }


# ── 卡片模板 ──


def help_card() -> dict:
    """命令列表卡片"""
    columns = [
        _col("cmd", "命令"),
        _col("desc", "说明"),
    ]
    rows = [
        {"cmd": "帮助", "desc": "显示此命令列表"},
        {"cmd": "行情", "desc": "市场快照 (指数+状态)"},
        {"cmd": "持仓", "desc": "当前持仓状态"},
        {"cmd": "历史 [N]", "desc": "最近 N 条交易"},
        {"cmd": "建议", "desc": "生成交易建议 (耗时较长)"},
        {"cmd": "日报", "desc": "完整日常流程 (11步)"},
        {"cmd": "配置", "desc": "资产配置检查"},
        {"cmd": "记录", "desc": "记录交易 (多步对话)"},
    ]
    return _card("貔貅 — 命令列表", "purple", [
        _table(columns, rows, page_size=10),
        _hr(),
        _md("直接发送中文或 `/命令` 均可"),
    ])


def processing_card(task: str = "分析") -> dict:
    """处理中提示卡片"""
    return _card(f"正在{task}...", "wathet", [
        _md(f"⏳ 正在执行{task}，请稍候...\n\n完成后会自动推送结果。"),
    ])


def error_card(message: str) -> dict:
    """错误提示卡片"""
    return _card("出错了", "red", [
        _md(f"❌ {message}"),
    ])


def portfolio_card(holdings: list[dict], cash: float, total_invested: float, total_current: float) -> dict:
    """持仓状态卡片"""
    if not holdings:
        return _card("当前持仓", "blue", [
            _md("暂无持仓"),
            _md(f"**现金**: {cash:,.2f} RMB"),
        ])

    columns = [
        _col("fund", "基金"),
        _col("nav", "成本→现价", align="right"),
        _col("pl", "盈亏", align="right"),
    ]
    rows = []
    for h in holdings:
        shares = h["shares"]
        cost = h["cost_price"]
        current = h["current_nav"] or cost
        pl = (current - cost) * shares
        pl_pct = (current - cost) / cost * 100 if cost > 0 else 0
        sign = "+" if pl >= 0 else ""
        rows.append({
            "fund": f"{h['fund_code']} ({shares:.0f}份)",
            "nav": f"{cost:.4f}→{current:.4f}",
            "pl": f"{sign}{pl:.2f} ({sign}{pl_pct:.1f}%)",
        })

    total_pl = total_current - total_invested
    sign = "+" if total_pl >= 0 else ""

    return _card("当前持仓", "blue", [
        _table(columns, rows, page_size=50),
        _hr(),
        _md(
            f"**投入**: {total_invested:,.0f}  **市值**: {total_current:,.0f}  "
            f"**盈亏**: {sign}{total_pl:,.0f}  **现金**: {cash:,.0f}"
        ),
    ])


def history_card(trades: list[dict], limit: int) -> dict:
    """交易历史卡片"""
    if not trades:
        return _card("交易历史", "blue", [_md("暂无交易记录")])

    columns = [
        _col("info", "交易信息"),
        _col("amount", "金额", align="right"),
        _col("nav", "净值", align="right"),
    ]
    rows = []
    for t in trades:
        emoji = "🟢" if t["action"] == "buy" else "🔴"
        action = "买" if t["action"] == "buy" else "卖"
        # 日期取 MM-DD 精简显示
        date_short = t["trade_date"][5:] if len(t["trade_date"]) >= 10 else t["trade_date"]
        rows.append({
            "info": f"{emoji}{action} {t['fund_code']} {date_short}",
            "amount": f"{t['amount']:,.0f}",
            "nav": f"{t['nav']:.4f}",
        })

    return _card(f"最近 {limit} 条交易", "blue", [
        _table(columns, rows, page_size=50),
    ])


def market_card(regime: dict | None, snapshots: list[dict] | None) -> dict:
    """市场快照卡片"""
    elements = []

    if snapshots:
        columns = [
            _col("name", "指数"),
            _col("close", "收盘价", align="right"),
            _col("change", "涨跌幅", align="right"),
        ]
        rows = []
        for s in snapshots:
            change = s.get("change_pct")
            if change is not None:
                sign = "+" if change >= 0 else ""
                change_str = f"{sign}{change:.2f}%"
            else:
                change_str = "-"
            rows.append({
                "name": s["name"],
                "close": f"{s['close']:,.2f}",
                "change": change_str,
            })
        elements.append(_table(columns, rows, page_size=10))

    if regime:
        regime_labels = {
            "bull_strong": "🟢 强势上涨",
            "bull_weak": "🟢 弱势上涨",
            "ranging": "🟡 震荡",
            "bear_weak": "🔴 弱势下跌",
            "bear_strong": "🔴 强势下跌",
        }
        label = regime_labels.get(regime["regime"], regime["regime"])
        elements.append(_hr())
        elements.append(_md(
            f"**市场状态**: {label}\n"
            f"**趋势得分**: {regime['trend_score']:.1f}\n"
            f"**波动率**: {regime['volatility']:.2%}\n"
            f"{regime.get('description', '')}"
        ))

    color_map = {
        "bull_strong": "green",
        "bull_weak": "green",
        "ranging": "yellow",
        "bear_weak": "red",
        "bear_strong": "red",
    }
    color = color_map.get(regime["regime"], "blue") if regime else "blue"

    return _card("市场行情", color, elements or [_md("暂无市场数据")])


def recommendation_card(report_path: str, recommendations: list[dict] | None = None) -> dict:
    """交易建议卡片"""
    elements = []

    if recommendations:
        columns = [
            _col("action", "操作", align="center"),
            _col("fund", "基金"),
            _col("amount", "金额", align="right"),
            _col("confidence", "置信度", align="center"),
        ]
        rows = []
        for rec in recommendations:
            action = rec.get("action_label", "持有")
            emoji = "🟢" if action == "买入" else "🔴" if action == "卖出" else "🟡"
            fund_name = rec.get("fund_name", "")
            fund_code = rec.get("fund_code", "")
            rows.append({
                "action": f"{emoji} {action}",
                "fund": f"{fund_name} ({fund_code})",
                "amount": f"{rec.get('amount', 0):,.2f}",
                "confidence": f"{rec.get('confidence', 0):.0%}",
            })
        elements.append(_table(columns, rows, page_size=10))

        # 添加理由摘要
        for rec in recommendations:
            if rec.get("reason"):
                action = rec.get("action_label", "")
                fund_code = rec.get("fund_code", "")
                elements.append(_md(f"**{action} {fund_code}**: {rec['reason'][:200]}"))
    else:
        try:
            from pathlib import Path
            content = Path(report_path).read_text(encoding="utf-8")
            summary = content[:2000]
            elements.append(_md(summary))
        except Exception:
            elements.append(_md(f"报告已生成: {report_path}"))

    if recommendations:
        has_buy = any(r.get("action_label") == "买入" for r in recommendations)
        has_sell = any(r.get("action_label") == "卖出" for r in recommendations)
        if has_buy and not has_sell:
            color = "green"
        elif has_sell and not has_buy:
            color = "red"
        else:
            color = "blue"
    else:
        color = "blue"

    return _card("交易建议", color, elements or [_md("无建议")])


def daily_summary_card(success: bool, report_path: str | None = None) -> dict:
    """日报完成摘要卡片"""
    if success:
        msg = "✅ 日常分析流程 (11步) 已完成"
        if report_path:
            msg += f"\n\n报告: `{report_path}`"
        return _card("日报完成", "green", [_md(msg)])
    else:
        return _card("日报异常", "red", [_md("❌ 日常分析流程执行出错，请检查日志")])


def allocation_card(result: dict, regime: str, pe_pct: float) -> dict:
    """资产配置检查卡片"""
    compliant = result.get("compliant", False)
    status = "✅ 合规" if compliant else "❌ 不合规"

    columns = [
        _col("asset", "资产类别"),
        _col("target", "目标", align="center"),
        _col("current", "当前", align="center"),
        _col("dev", "偏差", align="center"),
    ]
    names = {"equity": "股票基金", "bond": "债券基金", "cash": "现金"}
    rows = []
    for asset in ["equity", "bond", "cash"]:
        target = result["target"][asset]
        current = result["current"][asset]
        dev = result["deviations"][asset]
        sign = "+" if dev >= 0 else ""
        rows.append({
            "asset": names.get(asset, asset),
            "target": f"{target:.0%}",
            "current": f"{current:.0%}",
            "dev": f"{sign}{dev:.0%}",
        })

    elements = [
        _md(f"**市场状态**: {regime} | **PE分位**: {pe_pct:.0f}% | **状态**: {status}"),
        _table(columns, rows, page_size=5),
    ]

    for v in result.get("violations", []):
        elements.append(_md(f"🚨 违规: {v}"))
    for s in result.get("suggestions", []):
        elements.append(_md(f"💡 建议: {s}"))

    return _card("资产配置检查", "blue", elements)


def trade_prompt_card(step: str, prompt: str) -> dict:
    """交易录入步骤提示卡片"""
    return _card(f"记录交易 — {step}", "indigo", [_md(prompt)])


def trade_confirm_card(trade_info: dict) -> dict:
    """交易确认卡片"""
    action_emoji = "🟢 买入" if trade_info["action"] == "buy" else "🔴 卖出"
    return _card("确认交易", "indigo", [
        _md(
            f"**操作**: {action_emoji}\n"
            f"**基金代码**: {trade_info['fund_code']}\n"
            f"**金额**: {trade_info['amount']:,.2f} RMB\n"
            f"**净值**: {trade_info['nav']:.4f}\n"
            f"**日期**: {trade_info['trade_date']}\n"
            f"**备注**: {trade_info.get('reason', '无')}"
        ),
        _hr(),
        _md("回复 **确认** 提交，回复 **取消** 放弃"),
    ])


def trade_success_card(trade_info: dict) -> dict:
    """交易成功卡片"""
    action_label = "买入" if trade_info["action"] == "buy" else "卖出"
    shares = trade_info["amount"] / trade_info["nav"] if trade_info["nav"] > 0 else 0
    return _card("交易已记录", "green", [
        _md(
            f"✅ 已记录: {action_label} {trade_info['fund_code']}\n"
            f"金额 {trade_info['amount']:,.2f} RMB @ {trade_info['nav']:.4f}\n"
            f"份额 {shares:.2f}"
        ),
    ])
