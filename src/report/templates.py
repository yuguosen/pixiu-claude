"""报告 Markdown 模板"""

from datetime import datetime


def recommendation_template(data: dict) -> str:
    """生成交易建议报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    sections = [f"# 交易建议报告 — {data.get('date', now)}\n"]

    # LLM 智能分析段落
    llm = data.get("llm_analysis")
    if llm:
        sections.append("## LLM 智能分析\n")
        if llm.get("market_narrative"):
            sections.append(f"### 市场研判\n\n{llm['market_narrative']}\n")
        if llm.get("initial_judgment"):
            sections.append(f"### 初步判断\n\n{llm['initial_judgment']}\n")
        if llm.get("challenge"):
            sections.append(f"### 自我挑战\n\n{llm['challenge']}\n")
        if llm.get("final_conclusion"):
            sections.append(f"### 最终结论\n\n{llm['final_conclusion']}\n")
        if llm.get("portfolio_advice"):
            sections.append(f"### 组合建议\n\n{llm['portfolio_advice']}\n")
        if llm.get("confidence_summary"):
            sections.append(f"**整体把握度**: {llm['confidence_summary']}\n")
        sections.append(f"*LLM 情绪: {llm.get('sentiment', '-')} | Token 消耗: {llm.get('tokens_used', 0)}*\n")
        sections.append("---\n")

    # 操作建议
    for rec in data.get("recommendations", []):
        confidence_label = "高" if rec["confidence"] > 0.7 else "中" if rec["confidence"] > 0.4 else "低"
        sections.append(f"""## 操作建议: {rec['action_label']}

| 项目 | 内容 |
|------|------|
| 操作 | **{rec['action_label']}** |
| 基金 | {rec.get('fund_name', '')} ({rec['fund_code']}) |
| 建议金额 | {rec.get('amount', 0):,.2f} RMB |
| 置信度 | {confidence_label} ({rec['confidence']:.0%}) |

### 分析依据

{rec.get('reason', '')}
""")

        # LLM 增强信息
        llm_factors = rec.get("llm_key_factors", [])
        llm_risks = rec.get("llm_risks", [])
        llm_stop = rec.get("llm_stop_loss", "")
        if llm_factors or llm_risks:
            sections.append("### LLM 洞察\n")
            if llm_factors:
                sections.append("**关键因子:**")
                for f in llm_factors:
                    sections.append(f"- {f}")
                sections.append("")
            if llm_risks:
                sections.append("**风险提示:**")
                for r in llm_risks:
                    sections.append(f"- {r}")
                sections.append("")
            if llm_stop:
                sections.append(f"**止损条件:** {llm_stop}\n")

        # 技术指标
        tech = rec.get("tech_summary", {})
        if tech:
            sections.append("### 技术面\n")
            if "rsi" in tech:
                sections.append(f"- RSI: {tech['rsi']:.1f} → {tech.get('rsi_signal', '')}")
            if "macd_signal" in tech:
                sections.append(f"- MACD: {tech['macd_signal']}")
            if "ma_alignment" in tech:
                sections.append(f"- 均线系统: {tech['ma_alignment']}")
            if "bb_signal" in tech:
                sections.append(f"- 布林带: {tech['bb_signal']}")
            sections.append("")

        # 风险评估
        risk = rec.get("risk", {})
        if risk:
            sections.append(f"""### 风险评估

- 预估最大亏损: {risk.get('max_loss_pct', 0):.1f}%
- 仓位建议: 总资产的 {risk.get('position_pct', 0):.0%}
""")

        # 费用明细
        cost = rec.get("cost", {})
        if cost:
            sections.append(f"""### 费用明细

- 申购费: {cost.get('subscription_fee', 0):.2f} RMB
- 赎回费(预估30天): {cost.get('redemption_fee', 0):.2f} RMB
- 总费用: {cost.get('total_fee', 0):.2f} RMB ({cost.get('total_fee_pct', 0):.3f}%)
- 净投入: {cost.get('net_investment', 0):.2f} RMB
- 保本收益率: {cost.get('breakeven_return_pct', 0):.3f}%
""")

        # 操作步骤
        sections.append(f"""### 操作步骤

1. 打开支付宝 → 理财 → 基金
2. 搜索 **{rec['fund_code']}**
3. {rec['action_label']} {rec.get('amount', 0):,.2f} RMB
4. 确认订单
""")

    # 市场环境
    market = data.get("market", {})
    if market:
        sections.append(f"""## 市场环境

- 市场状态: **{market.get('regime', '')}** — {market.get('description', '')}
- 趋势得分: {market.get('trend_score', 0):.1f}
- 波动率: {market.get('volatility', 0):.2%}
""")

        # 资金流向信号
        flow_signals = market.get("fund_flow_signals", [])
        if flow_signals:
            sections.append("### 资金面\n")
            for fs in flow_signals:
                sections.append(f"- {fs}")
            sections.append("")

        indices = market.get("indices", [])
        if indices:
            sections.append("### 主要指数\n")
            sections.append("| 指数 | 收盘价 | 涨跌幅 |")
            sections.append("|------|--------|--------|")
            for idx in indices:
                change = idx.get("change_pct")
                change_str = f"{change:+.2f}%" if change is not None else "-"
                sections.append(f"| {idx['name']} | {idx['close']:,.2f} | {change_str} |")
            sections.append("")

    # 资产配置
    alloc = data.get("asset_allocation")
    if alloc:
        cur = alloc.get("current", {})
        tgt = alloc.get("target", {})
        sections.append(f"""## 资产配置

| 资产类别 | 当前 | 目标 | 偏差 |
|----------|------|------|------|
| 偏股 | {cur.get('equity', 0):.0%} | {tgt.get('equity', 0):.0%} | {cur.get('equity', 0) - tgt.get('equity', 0):+.0%} |
| 债券 | {cur.get('bond', 0):.0%} | {tgt.get('bond', 0):.0%} | {cur.get('bond', 0) - tgt.get('bond', 0):+.0%} |
| 现金 | {cur.get('cash', 1):.0%} | {tgt.get('cash', 0):.0%} | {cur.get('cash', 1) - tgt.get('cash', 0):+.0%} |
""")

    # 账户状态
    account = data.get("account", {})
    if account:
        sections.append(f"""## 账户状态

- 总资产: {account.get('total_value', 0):,.2f} RMB
- 现金: {account.get('cash', 0):,.2f} RMB
- 已投资: {account.get('invested', 0):,.2f} RMB
- 当前回撤: {account.get('drawdown', 0):.2%}
""")

    sections.append(f"\n---\n*生成时间: {now} | 貔貅智能基金分析系统*\n")
    return "\n".join(sections)


def portfolio_template(data: dict) -> str:
    """生成组合状态报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections = [f"# 组合状态报告 — {data.get('date', now)}\n"]

    # 总览
    account = data.get("account", {})
    sections.append(f"""## 账户总览

| 项目 | 数值 |
|------|------|
| 总资产 | {account.get('total_value', 0):,.2f} RMB |
| 现金 | {account.get('cash', 0):,.2f} RMB |
| 已投资 | {account.get('invested', 0):,.2f} RMB |
| 总收益 | {account.get('total_return', 0):+.2f}% |
| 最大回撤 | {account.get('max_drawdown', 0):.2f}% |
""")

    # 持仓明细
    holdings = data.get("holdings", [])
    if holdings:
        sections.append("## 持仓明细\n")
        sections.append("| 基金 | 份额 | 成本 | 现价 | 盈亏 | 买入日期 |")
        sections.append("|------|------|------|------|------|----------|")
        for h in holdings:
            pnl = h.get("profit_loss_pct", 0)
            sections.append(
                f"| {h.get('fund_name', h['fund_code'])} | {h['shares']:.2f} | "
                f"{h['cost_price']:.4f} | {h.get('current_nav', 0):.4f} | "
                f"{pnl:+.2f}% | {h['buy_date']} |"
            )
        sections.append("")

    sections.append(f"\n---\n*生成时间: {now}*\n")
    return "\n".join(sections)
