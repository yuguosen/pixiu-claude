"""板块轮动与热点发现引擎

核心能力:
1. 跟踪 20+ 行业板块的实时强弱
2. 检测新兴热点 (从弱→强的板块)
3. 跟踪资金流向 (主力净流入)
4. 计算热度评分并持续追踪生命周期
5. 按关键词搜索行业/概念板块行情
"""

import difflib
import json
import logging
from datetime import datetime

import akshare as ak
import pandas as pd
from rich.console import Console
from rich.table import Table

from src.data.fetcher import fetch_index_daily, fetch_with_cache
from src.analysis.indicators import calculate_ma
from src.memory.database import execute_query, execute_write, execute_many

logger = logging.getLogger(__name__)

console = Console()

# 重点跟踪的行业板块 (东方财富行业分类, 已对齐 AKShare 命名)
TRACKED_SECTORS = [
    # 大科技
    "半导体", "消费电子", "软件开发", "计算机设备", "通信设备",
    "游戏Ⅱ", "互联网电商",
    # 新能源
    "电池", "光伏设备", "风电设备", "电力",
    # 大消费
    "白酒Ⅱ", "食品饮料", "医疗器械", "化学制药", "中药Ⅱ",
    "乘用车", "家用电器",
    # 金融周期
    "银行", "证券Ⅱ", "保险Ⅱ", "房地产开发",
    # 制造
    "航天装备Ⅱ", "航海装备Ⅱ", "工程机械", "专用设备",
    # 资源
    "贵金属", "煤炭开采", "石油石化",
]

# 原有的宽基指数 (保留兼容)
BROAD_INDICES = [
    {"code": "000300", "name": "沪深300", "sector": "大盘价值"},
    {"code": "000905", "name": "中证500", "sector": "中盘成长"},
    {"code": "000852", "name": "中证1000", "sector": "小盘"},
    {"code": "399006", "name": "创业板指", "sector": "科技成长"},
]


# ── 数据获取 ──────────────────────────────────────────────


def fetch_sector_realtime() -> pd.DataFrame:
    """获取所有行业板块的实时行情"""
    try:
        df = ak.stock_board_industry_name_em()
        return df
    except Exception as e:
        console.print(f"[red]获取行业板块数据失败: {e}[/]")
        return pd.DataFrame()


def fetch_sector_fund_flow() -> pd.DataFrame:
    """获取行业资金流向"""
    try:
        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        return df
    except Exception as e:
        console.print(f"[yellow]获取资金流向失败: {e}[/]")
        return pd.DataFrame()


def fetch_sector_history(sector_name: str, days: int = 60) -> pd.DataFrame:
    """获取单个板块的历史行情"""
    try:
        from datetime import timedelta
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")
        df = ak.stock_board_industry_hist_em(
            symbol=sector_name, period="日k",
            start_date=start, end_date=end, adjust=""
        )
        if df is not None and not df.empty:
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "涨跌幅": "change_pct",
                "成交量": "volume", "成交额": "amount", "换手率": "turnover",
            })
            for col in ["open", "close", "high", "low", "change_pct", "volume", "amount", "turnover"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        console.print(f"  [dim]获取 {sector_name} 历史失败: {e}[/]")
        return pd.DataFrame()


# ── 板块快照 ──────────────────────────────────────────────


def update_sector_snapshots() -> int:
    """更新行业板块每日快照, 存入数据库

    Returns:
        更新的板块数量
    """
    console.print("  获取行业板块行情...")
    realtime = fetch_sector_realtime()
    if realtime.empty:
        return 0

    # 获取资金流向
    fund_flow = fetch_sector_fund_flow()
    flow_map = {}
    if not fund_flow.empty:
        for _, row in fund_flow.iterrows():
            flow_map[row.get("名称", "")] = row.get("今日主力净流入-净额", 0)

    today = datetime.now().strftime("%Y-%m-%d")
    records = []
    for _, row in realtime.iterrows():
        name = row.get("板块名称", "")
        if name not in TRACKED_SECTORS:
            continue
        records.append((
            name,
            row.get("板块代码", ""),
            today,
            row.get("最新价"),
            row.get("涨跌幅"),
            row.get("成交量") if "成交量" in realtime.columns else None,
            row.get("成交额") if "成交额" in realtime.columns else None,
            row.get("换手率"),
            flow_map.get(name, 0),
            row.get("排名"),
        ))

    if records:
        execute_many(
            """INSERT OR REPLACE INTO sector_snapshots
               (sector_name, sector_code, snapshot_date, close, change_pct,
                volume, amount, turnover_rate, net_inflow, rank_today)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            records,
        )
    console.print(f"  [green]更新 {len(records)} 个行业板块快照[/]")
    return len(records)


# ── 热点检测 ──────────────────────────────────────────────


def detect_hotspots() -> list[dict]:
    """检测当前市场热点

    检测维度:
    1. 短期涨幅加速 (近5日 vs 前5日)
    2. 资金持续流入
    3. 换手率放大
    4. 从弱势排名快速上升

    Returns:
        热点列表, 按热度评分降序
    """
    hotspots = []

    for sector_name in TRACKED_SECTORS:
        try:
            score, evidence = _score_sector_hotness(sector_name)
            if score >= 30:  # 热度阈值
                hotspot_type = _classify_hotspot(score, evidence)
                hotspots.append({
                    "sector_name": sector_name,
                    "score": round(score, 1),
                    "type": hotspot_type,
                    "evidence": evidence,
                })
        except Exception:
            continue

    hotspots.sort(key=lambda x: x["score"], reverse=True)

    # 存入数据库
    today = datetime.now().strftime("%Y-%m-%d")
    # 先将旧的活跃热点标记过期
    execute_write(
        """UPDATE hotspots SET status = 'expired', expired_date = ?
           WHERE status = 'active' AND detected_date < ?""",
        (today, today),
    )

    for h in hotspots:
        # 查是否已有今日记录
        existing = execute_query(
            "SELECT id FROM hotspots WHERE sector_name = ? AND detected_date = ?",
            (h["sector_name"], today),
        )
        if not existing:
            execute_write(
                """INSERT INTO hotspots
                   (sector_name, sector_code, detected_date, hotspot_type, score, evidence, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'active')""",
                (
                    h["sector_name"], "",
                    today, h["type"], h["score"],
                    json.dumps(h["evidence"], ensure_ascii=False, default=str),
                ),
            )

    return hotspots


def _score_sector_hotness(sector_name: str) -> tuple[float, dict]:
    """计算单个板块的热度评分

    Returns:
        (score 0-100, evidence dict)
    """
    score = 0.0
    evidence = {}

    # 获取历史行情
    hist = fetch_sector_history(sector_name, days=60)
    if hist.empty or len(hist) < 10:
        return 0, evidence

    closes = hist["close"].astype(float)
    volumes = hist["amount"].astype(float) if "amount" in hist.columns else pd.Series(dtype=float)
    turnovers = hist["turnover"].astype(float) if "turnover" in hist.columns else pd.Series(dtype=float)

    # ── 1. 涨幅加速 (最高 35 分) ──
    if len(closes) >= 10:
        ret_5d = (closes.iloc[-1] - closes.iloc[-5]) / closes.iloc[-5] * 100
        ret_prev_5d = (closes.iloc[-5] - closes.iloc[-10]) / closes.iloc[-10] * 100
        acceleration = ret_5d - ret_prev_5d
        evidence["return_5d"] = round(ret_5d, 2)
        evidence["return_prev_5d"] = round(ret_prev_5d, 2)
        evidence["acceleration"] = round(acceleration, 2)

        # 近5日涨幅本身
        if ret_5d > 5:
            score += min(20, ret_5d * 2)
        elif ret_5d > 2:
            score += ret_5d * 2

        # 加速度
        if acceleration > 3:
            score += min(15, acceleration * 3)
            evidence["加速上涨"] = True

    # ── 2. 成交量放大 (最高 25 分) ──
    if not volumes.empty and len(volumes) >= 10:
        vol_5d_avg = volumes.iloc[-5:].mean()
        vol_prev_avg = volumes.iloc[-20:-5].mean() if len(volumes) >= 20 else volumes.iloc[:-5].mean()

        if vol_prev_avg > 0:
            vol_ratio = vol_5d_avg / vol_prev_avg
            evidence["volume_ratio"] = round(vol_ratio, 2)

            if vol_ratio > 2.0:
                score += 25
                evidence["放量"] = True
            elif vol_ratio > 1.5:
                score += 15
            elif vol_ratio > 1.2:
                score += 8

    # ── 3. 换手率异常 (最高 15 分) ──
    if not turnovers.empty and len(turnovers) >= 5:
        recent_turnover = turnovers.iloc[-5:].mean()
        avg_turnover = turnovers.mean()
        if avg_turnover > 0:
            turnover_ratio = recent_turnover / avg_turnover
            evidence["turnover_ratio"] = round(turnover_ratio, 2)
            if turnover_ratio > 1.5:
                score += min(15, (turnover_ratio - 1) * 15)

    # ── 4. 趋势确认 (最高 15 分) ──
    if len(closes) >= 20:
        mas = calculate_ma(closes, [5, 10, 20])
        ma5 = float(mas["MA5"].iloc[-1])
        ma10 = float(mas["MA10"].iloc[-1])
        ma20 = float(mas["MA20"].iloc[-1])

        if ma5 > ma10 > ma20:
            score += 15
            evidence["均线多头"] = True
        elif ma5 > ma10:
            score += 8

    # ── 5. 排名上升 (最高 10 分) ──
    snapshots = execute_query(
        """SELECT rank_today, snapshot_date FROM sector_snapshots
           WHERE sector_name = ? ORDER BY snapshot_date DESC LIMIT 10""",
        (sector_name,),
    )
    if len(snapshots) >= 2:
        ranks = [s["rank_today"] for s in snapshots if s["rank_today"] is not None]
        if len(ranks) >= 2:
            rank_improvement = ranks[-1] - ranks[0]  # 正值 = 排名上升 (数字变小)
            if rank_improvement > 0:
                # 排名是从旧到新, 越小越好。如果 old=50, new=10, improvement=40
                evidence["rank_change"] = rank_improvement
                score += min(10, rank_improvement * 0.5)

    # ── 6. 资金流入 (加分项, 最高 15 分) ──
    # 6a. 数据库快照中的当日资金流
    latest_snapshot = execute_query(
        """SELECT net_inflow FROM sector_snapshots
           WHERE sector_name = ? ORDER BY snapshot_date DESC LIMIT 1""",
        (sector_name,),
    )
    if latest_snapshot and latest_snapshot[0]["net_inflow"]:
        inflow = latest_snapshot[0]["net_inflow"]
        if inflow > 0:
            evidence["net_inflow"] = round(inflow / 1e8, 2)  # 转亿
            score += min(10, inflow / 1e9 * 5)  # 每10亿加5分

    # 6b. 5日行业资金流向排名 (增强信号)
    try:
        from src.analysis.fund_flow import get_sector_fund_flow_ranking
        sector_flows = get_sector_fund_flow_ranking("5日")
        for sf in sector_flows:
            if sf["sector_name"] == sector_name and sf["net_inflow"] > 0:
                evidence["flow_5d"] = round(sf["net_inflow"], 1)
                # 5日持续流入额外加分
                score += min(5, sf["net_inflow"] / 20)  # 每20亿加1分
                break
    except Exception:
        pass

    return score, evidence


def _classify_hotspot(score: float, evidence: dict) -> str:
    """分类热点阶段"""
    has_acceleration = evidence.get("加速上涨", False)
    has_volume = evidence.get("放量", False)
    has_ma_bull = evidence.get("均线多头", False)
    ret_5d = evidence.get("return_5d", 0)

    if score >= 70 and has_acceleration and has_volume:
        return "accelerating"  # 加速阶段 — 最热
    elif score >= 50 and (has_volume or has_ma_bull):
        return "emerging"  # 新兴热点 — 值得关注
    elif ret_5d > 8 and not has_acceleration:
        return "peak"  # 可能见顶 — 谨慎
    else:
        return "emerging"


# ── 热点分析输出 ──────────────────────────────────────────


def print_hotspot_report():
    """输出热点分析报告"""
    console.print("\n[bold]═══ 行业热点扫描 ═══[/]\n")

    console.print("[dim]更新板块数据...[/]")
    update_sector_snapshots()

    console.print("[dim]检测热点...[/]")
    hotspots = detect_hotspots()

    if not hotspots:
        console.print("[yellow]当前未检测到明显热点[/]")
        return hotspots

    table = Table(title="市场热点")
    table.add_column("排名", style="dim")
    table.add_column("板块", style="bold")
    table.add_column("热度", style="bold")
    table.add_column("阶段")
    table.add_column("5日涨幅")
    table.add_column("量比")
    table.add_column("资金流入(亿)")
    table.add_column("关键信号")

    type_labels = {
        "accelerating": "[bold red]加速[/]",
        "emerging": "[bold green]新兴[/]",
        "peak": "[bold yellow]见顶[/]",
        "fading": "[dim]衰退[/]",
    }

    for i, h in enumerate(hotspots[:15], 1):
        ev = h["evidence"]
        signals = []
        if ev.get("加速上涨"):
            signals.append("加速")
        if ev.get("放量"):
            signals.append("放量")
        if ev.get("均线多头"):
            signals.append("多头")

        inflow = ev.get("net_inflow", 0)
        inflow_str = f"{inflow:+.1f}" if inflow else "-"

        # 热度条
        bar_len = int(h["score"] / 10)
        heat_bar = "[red]" + "█" * bar_len + "[/]" + "░" * (10 - bar_len)

        table.add_row(
            str(i),
            h["sector_name"],
            f"{heat_bar} {h['score']:.0f}",
            type_labels.get(h["type"], h["type"]),
            f"{ev.get('return_5d', 0):+.1f}%",
            f"{ev.get('volume_ratio', 1):.1f}x",
            inflow_str,
            " ".join(signals) if signals else "-",
        )

    console.print(table)

    # 投资建议
    top = hotspots[:3]
    if top:
        console.print("\n[bold]热点投资建议:[/]")
        for h in top:
            if h["type"] == "accelerating":
                console.print(f"  [red]▲[/] {h['sector_name']}: 处于加速阶段，可关注相关基金，但注意追高风险")
            elif h["type"] == "emerging":
                console.print(f"  [green]★[/] {h['sector_name']}: 新兴热点，建议小仓位试探")
            elif h["type"] == "peak":
                console.print(f"  [yellow]⚠[/] {h['sector_name']}: 短期涨幅过大，谨慎追入")

    return hotspots


def get_hot_sectors(min_score: float = 40) -> list[str]:
    """获取当前活跃热点板块名称列表 (供策略引擎使用)"""
    rows = execute_query(
        """SELECT sector_name, score FROM hotspots
           WHERE status = 'active' AND score >= ?
           ORDER BY score DESC""",
        (min_score,),
    )
    return [r["sector_name"] for r in rows]


# ── 保留原有的宽基指数分析 (兼容) ─────────────────────────


def analyze_sector_rotation(lookback_days: int = 60) -> list[dict]:
    """分析宽基指数轮动 (保留兼容)"""
    results = []
    for sector in BROAD_INDICES:
        try:
            df = fetch_index_daily(sector["code"])
            if df.empty or len(df) < lookback_days:
                continue

            closes = pd.Series(df["close"].values, dtype=float)
            recent = closes.iloc[-lookback_days:]
            period_return = (float(recent.iloc[-1]) - float(recent.iloc[0])) / float(recent.iloc[0]) * 100

            if len(recent) >= 40:
                recent_20 = (float(recent.iloc[-1]) - float(recent.iloc[-20])) / float(recent.iloc[-20]) * 100
                prev_20 = (float(recent.iloc[-20]) - float(recent.iloc[-40])) / float(recent.iloc[-40]) * 100
                momentum_change = recent_20 - prev_20
            else:
                recent_20 = period_return
                momentum_change = 0

            mas = calculate_ma(closes, [5, 20])
            ma5 = float(mas["MA5"].iloc[-1])
            ma20 = float(mas["MA20"].iloc[-1])

            results.append({
                "code": sector["code"],
                "name": sector["name"],
                "sector": sector["sector"],
                "period_return": round(period_return, 2),
                "recent_20d_return": round(recent_20, 2),
                "momentum_change": round(momentum_change, 2),
                "trend": "上升" if ma5 > ma20 else "下降",
                "current_price": float(closes.iloc[-1]),
            })
        except Exception as e:
            console.print(f"  [yellow]分析 {sector['name']} 失败: {e}[/]")

    results.sort(key=lambda x: x["period_return"], reverse=True)
    for i, r in enumerate(results):
        if i < len(results) / 3:
            r["strength"] = "强势"
        elif i >= len(results) * 2 / 3:
            r["strength"] = "弱势"
        else:
            r["strength"] = "中性"
    return results


def get_rotation_summary(sectors: list[dict]) -> str:
    """生成板块轮动摘要"""
    if not sectors:
        return "无板块数据"
    strong = [s for s in sectors if s.get("strength") == "强势"]
    weak = [s for s in sectors if s.get("strength") == "弱势"]
    lines = []
    if strong:
        lines.append(f"强势板块: {', '.join(s['name'] for s in strong)}")
    if weak:
        lines.append(f"弱势板块: {', '.join(s['name'] for s in weak)}")
    return "\n".join(lines)


# ── 关键词搜索行业/概念板块 ──────────────────────────────


def search_sector_or_concept(keyword: str) -> dict | None:
    """按关键词搜索行业板块或概念板块

    匹配链 (6 步回退):
    1. 精确匹配 TRACKED_SECTORS
    2. 子串匹配 TRACKED_SECTORS
    3. 反向查找 SECTOR_FUND_KEYWORDS (如 "芯片" → "半导体")
    4. difflib 模糊匹配 TRACKED_SECTORS
    5. AKShare 全量行业板块名称子串搜索
    6. AKShare 概念板块名称子串搜索

    Returns:
        {"type": "industry"|"concept", "name": str, "match": str,
         "realtime_row": dict | None}
        或 None (未匹配)
    """
    kw = keyword.strip()
    if not kw:
        return None

    # ── 1. 精确匹配 ──
    if kw in TRACKED_SECTORS:
        return {"type": "industry", "name": kw, "match": "exact"}

    # ── 2. 子串匹配 ──
    for sector in TRACKED_SECTORS:
        clean = sector.replace("Ⅱ", "").replace("Ⅲ", "")
        if kw in sector or kw in clean or sector in kw or clean in kw:
            return {"type": "industry", "name": sector, "match": "substring"}

    # ── 3. 反向查找 SECTOR_FUND_KEYWORDS ──
    try:
        from src.data.fund_discovery import SECTOR_FUND_KEYWORDS
        for sector, kw_list in SECTOR_FUND_KEYWORDS.items():
            if any(kw in k or k in kw for k in kw_list):
                return {"type": "industry", "name": sector, "match": "keyword_reverse"}
    except ImportError:
        pass

    # ── 4. difflib 模糊匹配 ──
    clean_sectors = {s.replace("Ⅱ", "").replace("Ⅲ", ""): s for s in TRACKED_SECTORS}
    matches = difflib.get_close_matches(kw, clean_sectors.keys(), n=1, cutoff=0.5)
    if matches:
        return {"type": "industry", "name": clean_sectors[matches[0]], "match": "fuzzy"}

    # ── 5. AKShare 全量行业板块 ──
    industry_df = _fetch_all_industry_boards()
    if not industry_df.empty:
        col = "板块名称"
        hit = industry_df[industry_df[col].str.contains(kw, na=False, case=False)]
        if not hit.empty:
            # 按成交额降序取第一个
            if "成交额" in hit.columns:
                hit = hit.sort_values("成交额", ascending=False)
            row = hit.iloc[0]
            return {
                "type": "industry",
                "name": row[col],
                "match": "akshare_industry",
                "realtime_row": _row_to_dict(row),
            }

    # ── 6. AKShare 概念板块 ──
    concept_df = _fetch_all_concept_boards()
    if not concept_df.empty:
        col = "板块名称"
        hit = concept_df[concept_df[col].str.contains(kw, na=False, case=False)]
        if not hit.empty:
            if "成交额" in hit.columns:
                hit = hit.sort_values("成交额", ascending=False)
            row = hit.iloc[0]
            return {
                "type": "concept",
                "name": row[col],
                "match": "akshare_concept",
                "realtime_row": _row_to_dict(row),
            }

    return None


def get_board_detail(board_name: str, board_type: str = "industry",
                     cached_realtime: dict | None = None) -> dict | None:
    """获取板块/概念的详细行情数据

    Args:
        board_name: 板块名称
        board_type: "industry" 或 "concept"
        cached_realtime: 搜索阶段已获取的实时数据行 (避免重复请求)

    Returns:
        {
            "name": str,
            "type": str,
            "today": {"close", "change_pct", "amount", "turnover", "volume"},
            "trend_5d": [{"date", "change_pct", "amount"}],
            "related_fund_count": int,
        }
    """
    result = {"name": board_name, "type": board_type}

    # ── 今日数据 ──
    today_data = cached_realtime
    if not today_data:
        today_data = _get_board_realtime(board_name, board_type)
    if not today_data:
        return None

    result["today"] = {
        "close": today_data.get("最新价", 0),
        "change_pct": today_data.get("涨跌幅", 0),
        "amount": today_data.get("成交额", 0),
        "turnover": today_data.get("换手率", 0),
        "volume": today_data.get("成交量", 0),
    }

    # ── 近 5 日趋势 ──
    try:
        if board_type == "industry":
            hist = fetch_sector_history(board_name, days=10)
        else:
            hist = _fetch_concept_history(board_name, days=10)

        if hist is not None and not hist.empty:
            recent = hist.tail(5)
            trend = []
            for _, row in recent.iterrows():
                trend.append({
                    "date": str(row.get("date", "")),
                    "change_pct": float(row.get("change_pct", 0)),
                    "amount": float(row.get("amount", 0)),
                })
            result["trend_5d"] = trend
    except Exception as e:
        logger.debug("获取 %s 历史失败: %s", board_name, e)

    # ── 相关基金数 ──
    result["related_fund_count"] = _count_related_funds(board_name, board_type)

    return result


# ── 内部工具函数 ──────────────────────────────────────────


def _fetch_all_industry_boards() -> pd.DataFrame:
    """获取全量行业板块实时行情 (带缓存)"""
    def _fetch():
        return ak.stock_board_industry_name_em()
    return fetch_with_cache("industry_board_list", {}, _fetch)


def _fetch_all_concept_boards() -> pd.DataFrame:
    """获取全量概念板块实时行情 (带缓存)"""
    def _fetch():
        return ak.stock_board_concept_name_em()
    return fetch_with_cache("concept_board_list", {}, _fetch)


def _fetch_concept_history(concept_name: str, days: int = 10) -> pd.DataFrame:
    """获取概念板块历史行情"""
    try:
        from datetime import timedelta
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")
        df = ak.stock_board_concept_hist_em(
            symbol=concept_name, period="日k",
            start_date=start, end_date=end, adjust=""
        )
        if df is not None and not df.empty:
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "涨跌幅": "change_pct",
                "成交量": "volume", "成交额": "amount", "换手率": "turnover",
            })
            for col in ["open", "close", "high", "low", "change_pct", "volume", "amount", "turnover"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        logger.debug("获取概念板块 %s 历史失败: %s", concept_name, e)
        return pd.DataFrame()


def _get_board_realtime(board_name: str, board_type: str) -> dict | None:
    """从实时行情中提取单个板块的数据"""
    if board_type == "industry":
        df = _fetch_all_industry_boards()
    else:
        df = _fetch_all_concept_boards()

    if df.empty:
        return None

    col = "板块名称"
    row = df[df[col] == board_name]
    if row.empty:
        return None
    return _row_to_dict(row.iloc[0])


def _row_to_dict(row) -> dict:
    """将 DataFrame 行转为 dict，处理 numpy 类型"""
    d = {}
    for k, v in row.items():
        try:
            d[k] = float(v) if isinstance(v, (int, float)) or (hasattr(v, 'item') and not isinstance(v, str)) else v
        except (ValueError, TypeError):
            d[k] = v
    return d


def _count_related_funds(board_name: str, board_type: str) -> int:
    """统计观察池中与该板块相关的基金数量"""
    count = 0
    try:
        from src.data.fund_discovery import SECTOR_FUND_KEYWORDS
        keywords = SECTOR_FUND_KEYWORDS.get(board_name, [])
        if not keywords:
            # 概念板块或未映射的行业: 用板块名本身作为关键词
            clean = board_name.replace("Ⅱ", "").replace("Ⅲ", "").replace("概念", "")
            keywords = [clean]

        watchlist = execute_query(
            "SELECT w.fund_code, f.fund_name FROM watchlist w "
            "LEFT JOIN funds f ON w.fund_code = f.fund_code"
        )
        for w in watchlist:
            fname = w.get("fund_name") or ""
            if any(kw in fname for kw in keywords):
                count += 1
    except Exception:
        pass
    return count
