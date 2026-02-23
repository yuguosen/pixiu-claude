"""资金流向与基金规模分析

核心能力:
1. 市场整体资金流向 (主力净流入) — 判断机构态度
2. 行业资金流向排行 — 增强热点检测
3. 股票型基金仓位估计 — 极端值逆向信号
4. ETF 大额资金动向 — 跟踪聪明钱

数据来源: 东方财富 via AKShare
"""

import akshare as ak
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()


def get_market_fund_flow(days: int = 20) -> dict | None:
    """获取市场整体资金流向

    使用 A 股市场资金流向数据，判断主力/机构资金态度。

    Returns:
        {
            "flow_5d": 近5日主力净流入 (亿),
            "flow_10d": 近10日主力净流入 (亿),
            "flow_20d": 近20日主力净流入 (亿),
            "trend": "inflow" | "outflow" | "neutral",
            "score": -15 ~ +15,
            "detail": str,
        }
    """
    try:
        df = ak.stock_market_fund_flow()
        if df is None or df.empty:
            return None

        # 列名: 日期, 上证-收盘价, 上证-涨跌幅, 深证-..., 主力净流入-净额, 主力净流入-净占比, ...
        # 找到主力净流入列
        flow_col = None
        for col in df.columns:
            if "主力净流入" in str(col) and "净额" in str(col):
                flow_col = col
                break

        if flow_col is None:
            return None

        df[flow_col] = pd.to_numeric(df[flow_col], errors="coerce")
        df = df.dropna(subset=[flow_col]).tail(days)

        if len(df) < 5:
            return None

        # 近5日、10日、20日主力净流入 (单位: 亿)
        flow_5d = df[flow_col].tail(5).sum() / 1e8
        flow_10d = df[flow_col].tail(10).sum() / 1e8
        flow_20d = df[flow_col].sum() / 1e8

        # 评分 (-15 ~ +15)
        score = 0
        if flow_5d > 200:
            score += 10
        elif flow_5d > 50:
            score += 5
        elif flow_5d < -200:
            score -= 10
        elif flow_5d < -50:
            score -= 5

        if flow_20d > 500:
            score += 5
        elif flow_20d < -500:
            score -= 5

        score = max(-15, min(15, score))

        if score > 5:
            trend = "inflow"
        elif score < -5:
            trend = "outflow"
        else:
            trend = "neutral"

        detail = f"5日主力净流入 {flow_5d:+.0f}亿, 20日 {flow_20d:+.0f}亿"

        return {
            "flow_5d": round(flow_5d, 1),
            "flow_10d": round(flow_10d, 1),
            "flow_20d": round(flow_20d, 1),
            "trend": trend,
            "score": score,
            "detail": detail,
        }
    except Exception as e:
        console.print(f"  [dim]市场资金流向获取失败: {e}[/]")
        return None


def get_sector_fund_flow_ranking(period: str = "5日") -> list[dict]:
    """获取行业资金流向排行

    Args:
        period: "今日" | "5日" | "10日"

    Returns:
        [{sector_name, net_inflow, net_inflow_pct, rank}, ...]
    """
    try:
        df = ak.stock_sector_fund_flow_rank(indicator=period, sector_type="行业资金流")
        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            name = row.get("名称", "")
            # 尝试多种可能的列名
            inflow = 0
            for col in df.columns:
                if "主力净流入" in str(col) and "净额" in str(col):
                    inflow = pd.to_numeric(row.get(col, 0), errors="coerce") or 0
                    break

            inflow_pct = 0
            for col in df.columns:
                if "主力净流入" in str(col) and "净占比" in str(col):
                    inflow_pct = pd.to_numeric(row.get(col, 0), errors="coerce") or 0
                    break

            results.append({
                "sector_name": name,
                "net_inflow": inflow / 1e8 if abs(inflow) > 1e6 else inflow,  # 转亿
                "net_inflow_pct": inflow_pct,
                "rank": len(results) + 1,
            })

        return results
    except Exception as e:
        console.print(f"  [dim]行业资金流向获取失败: {e}[/]")
        return []


def get_fund_position_estimate() -> dict | None:
    """获取股票型基金仓位估计 (乐咕乐股)

    仓位极端值是逆向指标:
    - 仓位 > 90%: 市场过热，谨慎
    - 仓位 < 75%: 市场冷淡，可能是底部机会

    Returns:
        {
            "position": 当前仓位 %,
            "position_20d_avg": 近20日平均仓位,
            "signal": "overweight" | "underweight" | "neutral",
            "score": -10 ~ +10,
            "detail": str,
        }
    """
    try:
        df = ak.fund_stock_position_lg()
        if df is None or df.empty:
            return None

        # 列名: date, close, position
        df["position"] = pd.to_numeric(df["position"], errors="coerce")
        df = df.dropna(subset=["position"])

        if len(df) < 10:
            return None

        current_pos = float(df["position"].iloc[-1])
        avg_20 = float(df["position"].tail(20).mean())

        # 逆向评分: 仓位越高越看空 (机构已满仓无力加仓)
        score = 0
        if current_pos > 90:
            score = -10  # 极度过热
        elif current_pos > 85:
            score = -5   # 偏热
        elif current_pos < 70:
            score = 10   # 极度低仓, 底部区域
        elif current_pos < 75:
            score = 5    # 偏低, 有加仓空间

        if current_pos > 88:
            signal = "overweight"
        elif current_pos < 75:
            signal = "underweight"
        else:
            signal = "neutral"

        detail = f"当前基金仓位 {current_pos:.1f}% (近20期均值 {avg_20:.1f}%)"

        return {
            "position": round(current_pos, 1),
            "position_20d_avg": round(avg_20, 1),
            "signal": signal,
            "score": score,
            "detail": detail,
        }
    except Exception as e:
        console.print(f"  [dim]基金仓位估计获取失败: {e}[/]")
        return None


def get_etf_flow_snapshot(top_n: int = 20) -> list[dict]:
    """获取 ETF 主力资金流向快照

    追踪宽基 ETF 和行业 ETF 的主力净流入,
    机构大额买入 ETF 是重要的市场信号。

    Returns:
        [{code, name, main_inflow, main_inflow_pct, shares, turnover}, ...]
    """
    try:
        df = ak.fund_etf_spot_em()
        if df is None or df.empty:
            return []

        # 找到主力净流入列
        inflow_col = None
        for col in df.columns:
            if "主力净流入" in str(col) and "净额" in str(col):
                inflow_col = col
                break

        if inflow_col is None:
            return []

        df[inflow_col] = pd.to_numeric(df[inflow_col], errors="coerce")
        df = df.dropna(subset=[inflow_col])

        # 过滤: 只看有成交的 (排除迷你 ETF)
        amount_col = None
        for col in df.columns:
            if "成交额" in str(col):
                amount_col = col
                break

        if amount_col:
            df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce")
            df = df[df[amount_col] > 1e7]  # 成交额 > 1000万

        # 按主力净流入排序, 取前 top_n 和后 top_n
        df_sorted = df.sort_values(inflow_col, ascending=False)

        results = []
        # 净流入最多的 (机构买入)
        for _, row in df_sorted.head(top_n).iterrows():
            inflow = row[inflow_col]
            results.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "main_inflow": round(inflow / 1e8, 2),  # 亿
                "direction": "inflow",
            })

        # 净流出最多的 (机构卖出)
        for _, row in df_sorted.tail(top_n).iterrows():
            inflow = row[inflow_col]
            if inflow < 0:
                results.append({
                    "code": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "main_inflow": round(inflow / 1e8, 2),  # 亿
                    "direction": "outflow",
                })

        return results
    except Exception as e:
        console.print(f"  [dim]ETF 资金快照获取失败: {e}[/]")
        return []


def get_fund_flow_composite() -> dict:
    """综合资金流向信号

    汇总市场资金流、基金仓位、ETF 动向，生成综合评分。

    Returns:
        {
            "score": -30 ~ +30 (叠加到 market_regime),
            "signals": [str, ...],
            "market_flow": dict | None,
            "position": dict | None,
            "etf_top_inflow": [dict, ...],
        }
    """
    score = 0
    signals = []

    # 1. 市场资金流向
    market_flow = get_market_fund_flow()
    if market_flow:
        score += market_flow["score"]
        if market_flow["trend"] == "inflow":
            signals.append(f"主力资金流入: {market_flow['detail']}")
        elif market_flow["trend"] == "outflow":
            signals.append(f"主力资金流出: {market_flow['detail']}")

    # 2. 基金仓位
    position = get_fund_position_estimate()
    if position:
        score += position["score"]
        if position["signal"] != "neutral":
            signals.append(position["detail"])

    # 3. ETF 动向 (不计入评分，仅供参考)
    etf_flows = get_etf_flow_snapshot(top_n=10)

    score = max(-30, min(30, score))

    return {
        "score": score,
        "signals": signals,
        "market_flow": market_flow,
        "position": position,
        "etf_top_inflow": [e for e in etf_flows if e["direction"] == "inflow"][:5],
    }


def print_fund_flow_report():
    """输出资金流向分析报告"""
    console.print("\n[bold]═══ 资金流向分析 ═══[/]\n")

    composite = get_fund_flow_composite()

    # 市场资金流
    mf = composite["market_flow"]
    if mf:
        trend_color = "green" if mf["trend"] == "inflow" else "red" if mf["trend"] == "outflow" else "yellow"
        console.print(f"[bold]市场主力资金:[/] [{trend_color}]{mf['detail']}[/]")
        console.print(f"  5日: {mf['flow_5d']:+.0f}亿  10日: {mf['flow_10d']:+.0f}亿  20日: {mf['flow_20d']:+.0f}亿")
    else:
        console.print("[dim]市场资金流向数据暂不可用[/]")

    # 基金仓位
    pos = composite["position"]
    if pos:
        pos_color = "red" if pos["signal"] == "overweight" else "green" if pos["signal"] == "underweight" else "yellow"
        console.print(f"\n[bold]股票基金仓位:[/] [{pos_color}]{pos['position']:.1f}%[/] (均值 {pos['position_20d_avg']:.1f}%)")
        if pos["signal"] == "overweight":
            console.print("  [yellow]仓位偏高，注意回调风险[/]")
        elif pos["signal"] == "underweight":
            console.print("  [green]仓位偏低，可能存在底部机会[/]")

    # ETF 资金动向
    etf_inflows = composite["etf_top_inflow"]
    if etf_inflows:
        console.print("\n[bold]ETF 主力净流入 Top 5:[/]")
        table = Table()
        table.add_column("代码", style="cyan")
        table.add_column("名称")
        table.add_column("主力净流入(亿)")

        for e in etf_inflows[:5]:
            color = "green" if e["main_inflow"] > 0 else "red"
            table.add_row(
                e["code"],
                e["name"][:16],
                f"[{color}]{e['main_inflow']:+.2f}[/]",
            )
        console.print(table)

    # 行业资金流向
    console.print("\n[bold]行业资金流向 (5日):[/]")
    sector_flows = get_sector_fund_flow_ranking("5日")
    if sector_flows:
        table = Table()
        table.add_column("排名", style="dim")
        table.add_column("行业")
        table.add_column("主力净流入(亿)")

        # 前5 + 后5
        for item in sector_flows[:5]:
            color = "green" if item["net_inflow"] > 0 else "red"
            table.add_row(
                str(item["rank"]),
                item["sector_name"],
                f"[{color}]{item['net_inflow']:+.1f}[/]",
            )

        if len(sector_flows) > 10:
            table.add_row("...", "...", "...")
            for item in sector_flows[-5:]:
                color = "green" if item["net_inflow"] > 0 else "red"
                table.add_row(
                    str(item["rank"]),
                    item["sector_name"],
                    f"[{color}]{item['net_inflow']:+.1f}[/]",
                )
        console.print(table)

    # 综合评分
    score = composite["score"]
    if score > 10:
        verdict = "[green]资金面偏暖，机构积极布局[/]"
    elif score > 0:
        verdict = "[green]资金面中性偏多[/]"
    elif score > -10:
        verdict = "[yellow]资金面中性偏空[/]"
    else:
        verdict = "[red]资金面偏冷，机构撤退[/]"
    console.print(f"\n[bold]综合判断:[/] {verdict} (评分: {score:+d})")

    return composite
