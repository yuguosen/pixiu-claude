"""飞书消息卡片构建器 — 使用飞书原生 table 组件"""

import os


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


def _short_path(path: str) -> str:
    """将绝对路径转为 reports/ 开头的相对路径"""
    # 找到 "reports/" 并截取后面的部分
    sep = "reports" + os.sep
    alt_sep = "reports/"
    for prefix in (sep, alt_sep):
        idx = path.find(prefix)
        if idx >= 0:
            return path[idx:]
    return os.path.basename(path)


# ── 卡片模板 ──


def help_card() -> dict:
    """命令列表卡片"""
    columns = [
        _col("cmd", "命令"),
        _col("desc", "说明"),
    ]
    rows = [
        {"cmd": "帮助", "desc": "显示此命令列表"},
        {"cmd": "行情 [关键词]", "desc": "市场快照 / 板块行情"},
        {"cmd": "持仓", "desc": "当前持仓状态"},
        {"cmd": "历史 [N]", "desc": "最近 N 条交易"},
        {"cmd": "建议", "desc": "生成交易建议 (耗时较长)"},
        {"cmd": "日报", "desc": "完整日常流程 (11步)"},
        {"cmd": "配置", "desc": "资产配置检查"},
        {"cmd": "搜索 <关键词>", "desc": "按主题搜索基金"},
        {"cmd": "待确认", "desc": "查看今日待确认建议"},
        {"cmd": "确认 <序号> <净值>", "desc": "快捷回录交易"},
        {"cmd": "记录", "desc": "手动记录交易 (多步对话)"},
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

    return _card("市场行情", color, elements or [_md("暂无市场数据\n\n请先发送 **日报** 更新数据")])


def sector_market_card(keyword: str, match: dict, detail: dict) -> dict:
    """板块/概念行情卡片"""
    board_name = match["name"]
    board_type = "行业板块" if match["type"] == "industry" else "概念板块"
    today = detail.get("today", {})
    change = today.get("change_pct", 0) or 0

    elements = []

    # ── 基本信息 ──
    sign = "+" if change >= 0 else ""
    emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
    amount_yi = (today.get("amount") or 0) / 1e8
    turnover = today.get("turnover") or 0

    match_hint = ""
    if keyword != board_name:
        match_hint = f"  (\"{keyword}\" → {board_name})"

    elements.append(_md(
        f"**类型**: {board_type}{match_hint}\n"
        f"**最新价**: {today.get('close', 0):,.2f}  {emoji} {sign}{change:.2f}%\n"
        f"**成交额**: {amount_yi:,.1f} 亿  **换手率**: {turnover:.2f}%"
    ))

    # ── 5 日趋势 ──
    trend = detail.get("trend_5d", [])
    if trend:
        elements.append(_hr())
        trend_columns = [
            _col("date", "日期"),
            _col("change", "涨跌幅", align="right"),
            _col("amount", "成交额(亿)", align="right"),
        ]
        trend_rows = []
        for t in trend:
            c = t.get("change_pct", 0)
            s = "+" if c >= 0 else ""
            amt = (t.get("amount") or 0) / 1e8
            trend_rows.append({
                "date": str(t.get("date", ""))[-5:],  # MM-DD
                "change": f"{s}{c:.2f}%",
                "amount": f"{amt:,.1f}",
            })
        elements.append(_table(trend_columns, trend_rows, page_size=5))

    # ── 相关基金 ──
    fund_count = detail.get("related_fund_count", 0)
    if fund_count > 0:
        elements.append(_hr())
        elements.append(_md(f"观察池中有 **{fund_count}** 只相关基金"))

    color = "green" if change > 0 else "red" if change < 0 else "blue"
    return _card(f"{board_name} 行情", color, elements)


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
            elements.append(_md(f"报告已生成: `{_short_path(report_path)}`"))

    if recommendations:
        has_buy = any(r.get("action_label") == "买入" for r in recommendations)
        has_sell = any(r.get("action_label") == "卖出" for r in recommendations)
        if has_buy and not has_sell:
            color = "green"
        elif has_sell and not has_buy:
            color = "red"
        else:
            color = "blue"
        # 添加快捷确认提示
        elements.append(_hr())
        elements.append(_md("💡 在支付宝操作后，回复 `待确认` 查看列表，`确认 <序号> <净值>` 快捷回录"))
    else:
        color = "blue"

    return _card("交易建议", color, elements or [_md("无建议")])


def daily_summary_card(success: bool, summary: dict | None = None, error: str | None = None) -> dict:
    """日报完成摘要卡片 — 展示市场状态、建议、LLM 结论"""
    if not success:
        msg = "❌ 日常分析流程执行出错"
        if error:
            msg += f"\n\n{error[:500]}"
        return _card("日报异常", "red", [_md(msg)])

    if not summary:
        return _card("日报完成", "green", [_md("✅ 日常分析流程 (11步) 已完成")])

    elements = []

    # ── 市场状态 ──
    regime = summary.get("regime")
    if regime:
        regime_labels = {
            "bull_strong": "🟢 强势上涨",
            "bull_weak": "🟢 弱势上涨",
            "ranging": "🟡 震荡",
            "bear_weak": "🔴 弱势下跌",
            "bear_strong": "🔴 强势下跌",
        }
        label = regime_labels.get(regime["regime"], regime["regime"])
        elements.append(_md(
            f"**市场状态**: {label}\n"
            f"**趋势得分**: {regime['trend_score']:.1f} | "
            f"**波动率**: {regime['volatility']:.2%}"
        ))

    # ── 指数快照 ──
    indices = summary.get("indices")
    if indices:
        idx_columns = [
            _col("name", "指数"),
            _col("close", "收盘", align="right"),
            _col("change", "涨跌", align="right"),
        ]
        idx_rows = []
        for s in indices:
            change = s.get("change_pct")
            if change is not None:
                sign = "+" if change >= 0 else ""
                change_str = f"{sign}{change:.2f}%"
            else:
                change_str = "-"
            idx_rows.append({
                "name": s["name"],
                "close": f"{s['close']:,.2f}",
                "change": change_str,
            })
        elements.append(_table(idx_columns, idx_rows, page_size=5))

    # ── 交易建议 ──
    recs = summary.get("recommendations")
    if recs:
        elements.append(_hr())
        elements.append(_md("**今日建议**"))
        rec_columns = [
            _col("action", "操作", align="center"),
            _col("fund", "基金"),
            _col("amount", "金额", align="right"),
            _col("conf", "置信度", align="center"),
        ]
        rec_rows = []
        for r in recs:
            action = "买入" if r["action"] == "buy" else "卖出"
            emoji = "🟢" if r["action"] == "buy" else "🔴"
            fund_name = r.get("fund_name") or r["fund_code"]
            conf = r.get("confidence") or 0
            rec_rows.append({
                "action": f"{emoji} {action}",
                "fund": f"{fund_name} ({r['fund_code']})",
                "amount": f"{r['amount']:,.0f}",
                "conf": f"{conf:.0%}" if isinstance(conf, float) else str(conf),
            })
        elements.append(_table(rec_columns, rec_rows, page_size=10))

        # 简要理由
        for r in recs[:3]:
            reason = r.get("reason") or ""
            if reason:
                action = "买入" if r["action"] == "buy" else "卖出"
                elements.append(_md(f"**{action} {r['fund_code']}**: {reason[:200]}"))
    else:
        elements.append(_hr())
        elements.append(_md("今日无新建议 (持有/观望)"))

    # ── LLM 结论 ──
    llm_conclusion = summary.get("llm_conclusion")
    if llm_conclusion:
        elements.append(_hr())
        elements.append(_md(f"**AI 结论**\n{llm_conclusion[:800]}"))

    # ── 报告路径 ──
    report_path = summary.get("report_path")
    if report_path:
        elements.append(_md(f"\n📄 `{_short_path(report_path)}`"))

    # 卡片颜色
    if regime:
        color_map = {
            "bull_strong": "green", "bull_weak": "green",
            "ranging": "yellow",
            "bear_weak": "red", "bear_strong": "red",
        }
        color = color_map.get(regime["regime"], "green")
    else:
        color = "green"

    return _card("日报完成", color, elements or [_md("✅ 日常分析流程已完成")])


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


def search_card(keyword: str, results: list[dict]) -> dict:
    """主题搜索结果卡片"""
    if not results:
        return _card(f"搜索: {keyword}", "indigo", [
            _md(f"未找到包含 \"{keyword}\" 的基金"),
        ])

    columns = [
        _col("code", "代码"),
        _col("name", "名称"),
        _col("ret_3m", "近3月", align="right"),
        _col("ret_1y", "近1年", align="right"),
        _col("score", "评分", align="right"),
    ]
    rows = []
    for r in results:
        ret_3m = r.get("return_3m")
        ret_1y = r.get("return_1y")
        score = r.get("composite_score", 0)
        rows.append({
            "code": r["fund_code"],
            "name": r["fund_name"][:16],
            "ret_3m": f"{ret_3m:+.1f}%" if ret_3m is not None else "-",
            "ret_1y": f"{ret_1y:+.1f}%" if ret_1y is not None else "-",
            "score": f"{score:.1f}",
        })

    # 统计新加入观察池的数量
    added_count = 0
    try:
        from src.memory.database import execute_query
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        for r in results:
            watch = execute_query(
                "SELECT added_date, reason FROM watchlist WHERE fund_code = ?",
                (r["fund_code"],),
            )
            if watch and watch[0]["added_date"] == today and "主题搜索" in (watch[0].get("reason") or ""):
                added_count += 1
    except Exception:
        pass

    elements = [_table(columns, rows, page_size=20)]
    if added_count > 0:
        elements.append(_hr())
        elements.append(_md(f"已自动加入观察池 **{added_count}** 只"))

    return _card(f"搜索: {keyword} (找到 {len(results)} 只)", "indigo", elements)


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


def pending_trades_card(pending: list[dict]) -> dict:
    """待确认建议列表卡片"""
    columns = [
        _col("idx", "#", align="center"),
        _col("action", "操作", align="center"),
        _col("fund", "基金"),
        _col("amount", "金额", align="right"),
    ]
    rows = []
    for i, p in enumerate(pending, 1):
        action = "买入" if p["action"] == "buy" else "卖出"
        emoji = "🟢" if p["action"] == "buy" else "🔴"
        fund_name = p.get("fund_name") or p["fund_code"]
        rows.append({
            "idx": str(i),
            "action": f"{emoji} {action}",
            "fund": f"{fund_name} ({p['fund_code']})",
            "amount": f"{p['amount']:,.0f}",
        })

    elements = [
        _table(columns, rows, page_size=10),
        _hr(),
        _md("**快捷确认**: 回复 `确认 <序号> <净值>`\n例如: `确认 1 3.45`"),
    ]
    return _card(f"待确认建议 ({len(pending)} 条)", "indigo", elements)
