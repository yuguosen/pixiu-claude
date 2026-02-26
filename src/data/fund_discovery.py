"""基金发现引擎 — 从全市场动态筛选最优基金

核心能力:
1. 热点驱动: 板块热点 → 自动匹配行业主题基金
2. 全市场筛选: 按业绩排名 + 评分筛选 top N
3. 动态候选池: 定期更新, 替代静态 5 只基金
"""

import json
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
from rich.console import Console
from rich.table import Table

from src.config import CONFIG
from src.data.fetcher import fetch_with_cache
from src.memory.database import execute_query, execute_write

console = Console()

# ── 板块 → 基金关键词映射 ──────────────────────────────────
# 每个热点板块对应的基金名称搜索关键词
# 优先匹配指数基金/ETF联接 (费率低, 跟踪紧密), 其次主题混合基金

SECTOR_FUND_KEYWORDS = {
    # 大科技
    "半导体": ["半导体", "芯片", "集成电路"],
    "消费电子": ["消费电子", "电子信息", "信息技术"],
    "软件开发": ["软件", "信息技术", "计算机", "数字经济"],
    "计算机设备": ["计算机", "信息技术", "数字经济"],
    "通信设备": ["通信", "5G"],
    "游戏Ⅱ": ["传媒", "游戏", "文化"],
    "互联网电商": ["互联网", "电商", "数字经济"],
    # 新能源
    "电池": ["新能源", "电池", "锂电"],
    "光伏设备": ["光伏", "太阳能", "新能源"],
    "风电设备": ["风电", "新能源", "清洁能源"],
    "电力": ["电力", "公用事业", "能源"],
    # 大消费
    "白酒Ⅱ": ["白酒", "酒"],
    "食品饮料": ["食品", "饮料", "消费"],
    "医疗器械": ["医疗", "医药", "健康"],
    "化学制药": ["医药", "创新药", "生物医药"],
    "中药Ⅱ": ["中药", "医药"],
    "乘用车": ["汽车", "新能源车", "智能汽车"],
    "家用电器": ["家电", "消费"],
    # 金融周期
    "银行": ["银行", "金融"],
    "证券Ⅱ": ["证券", "券商", "非银金融"],
    "保险Ⅱ": ["保险", "金融"],
    "房地产开发": ["房地产", "地产"],
    # 制造
    "航天装备Ⅱ": ["军工", "国防", "航天"],
    "航海装备Ⅱ": ["军工", "船舶", "国防"],
    "工程机械": ["机械", "高端装备", "制造"],
    "专用设备": ["装备", "制造", "机械"],
    # 资源
    "贵金属": ["黄金", "贵金属", "有色"],
    "煤炭开采": ["煤炭", "能源", "资源"],
    "石油石化": ["石油", "石化", "能源"],
}


def _get_fund_directory() -> pd.DataFrame:
    """获取全市场基金目录 (带缓存)"""
    def _fetch():
        return ak.fund_name_em()
    return fetch_with_cache("fund_name_em", {}, _fetch)


def _get_fund_rankings() -> pd.DataFrame:
    """获取开放式基金业绩排名 (带缓存)"""
    def _fetch():
        return ak.fund_open_fund_rank_em(symbol="全部")
    return fetch_with_cache("fund_rank_em_all", {}, _fetch)


def discover_sector_funds(
    sector_name: str, top_n: int = 5
) -> list[dict]:
    """根据板块名称发现对应的主题基金

    Args:
        sector_name: 板块名称 (如 "半导体", "光伏设备")
        top_n: 返回最优的 N 只

    Returns:
        [{"fund_code": "xxx", "fund_name": "xxx", "fund_type": "xxx",
          "return_1y": float, "return_3m": float, "match_keyword": "xxx"}]
    """
    keywords = SECTOR_FUND_KEYWORDS.get(sector_name, [])
    if not keywords:
        # 尝试用板块名本身作为关键词 (去掉后缀)
        clean_name = sector_name.replace("Ⅱ", "").replace("Ⅲ", "")
        keywords = [clean_name]

    # 获取基金目录
    directory = _get_fund_directory()
    if directory.empty:
        return []

    # 获取排名数据
    rankings = _get_fund_rankings()
    if rankings.empty:
        return []

    # 搜索匹配的基金
    name_col = "基金简称"
    type_col = "基金类型"
    all_matches = []

    for keyword in keywords:
        matches = directory[directory[name_col].str.contains(keyword, na=False)]
        # 过滤: 去掉场内基金和不可购买的类型，但保留 ETF联接/QDII (支付宝可买)
        matches = matches[
            ~matches[type_col].str.contains("LOF|FOF|货币|理财|定开", na=False)
        ]
        for _, row in matches.iterrows():
            all_matches.append({
                "fund_code": row["基金代码"],
                "fund_name": row[name_col],
                "fund_type": row[type_col],
                "match_keyword": keyword,
            })

    if not all_matches:
        return []

    # 去重 (同一基金可能被多个关键词匹配)
    seen_codes = set()
    unique_matches = []
    for m in all_matches:
        if m["fund_code"] not in seen_codes:
            seen_codes.add(m["fund_code"])
            unique_matches.append(m)

    # 用排名数据补充业绩
    rank_map = {}
    for _, row in rankings.iterrows():
        code = str(row.get("基金代码", ""))
        rank_map[code] = row

    results = []
    for m in unique_matches:
        rank = rank_map.get(m["fund_code"])
        if rank is None:
            continue

        # 解析业绩数据
        try:
            return_3m = _parse_pct(rank.get("近3月"))
            return_6m = _parse_pct(rank.get("近6月"))
            return_1y = _parse_pct(rank.get("近1年"))
        except Exception:
            continue

        # 基本过滤: 至少有3个月数据
        if return_3m is None:
            continue

        m["return_3m"] = return_3m
        m["return_6m"] = return_6m
        m["return_1y"] = return_1y
        m["return_1w"] = _parse_pct(rank.get("近1周"))
        m["return_1m"] = _parse_pct(rank.get("近1月"))
        m["fee"] = rank.get("手续费", "")
        results.append(m)

    # 排序: 优先近3月收益, 其次近1年
    results.sort(
        key=lambda x: (x.get("return_3m") or -999, x.get("return_1y") or -999),
        reverse=True,
    )

    # 去掉同质化基金 (A/C份额只保留一个)
    final = _dedupe_share_classes(results)

    return final[:top_n]


def discover_by_theme(keywords: list[str], top_n: int = 10) -> list[dict]:
    """按主题关键词搜索全市场基金

    Args:
        keywords: 搜索关键词列表, 如 ["养老", "适老"]
        top_n: 返回最优的 N 只

    Returns:
        [{"fund_code", "fund_name", "fund_type", "match_keyword",
          "return_3m", "return_1y", "composite_score"}]
    """
    directory = _get_fund_directory()
    if directory.empty:
        return []

    rankings = _get_fund_rankings()
    if rankings.empty:
        return []

    # 关键词匹配基金名称
    name_col = "基金简称"
    type_col = "基金类型"
    all_matches = []

    for keyword in keywords:
        matched = directory[directory[name_col].str.contains(keyword, na=False)]
        # 仅过滤: 货币基金、理财型、定开型、LOF (场内不可支付宝购买)
        # 不过滤 FOF (养老基金大多是 FOF) 和 QDII (搜索"标普"等需要)
        matched = matched[
            ~matched[type_col].str.contains("LOF|货币|理财|定开", na=False)
        ]
        for _, row in matched.iterrows():
            all_matches.append({
                "fund_code": row["基金代码"],
                "fund_name": row[name_col],
                "fund_type": row[type_col],
                "match_keyword": keyword,
            })

    if not all_matches:
        return []

    # 去重 (同一基金可能被多个关键词匹配)
    seen_codes = set()
    unique_matches = []
    for m in all_matches:
        if m["fund_code"] not in seen_codes:
            seen_codes.add(m["fund_code"])
            unique_matches.append(m)

    # 用排名数据补充业绩
    rank_map = {}
    for _, row in rankings.iterrows():
        code = str(row.get("基金代码", ""))
        rank_map[code] = row

    results = []
    for m in unique_matches:
        rank = rank_map.get(m["fund_code"])
        if rank is None:
            continue

        try:
            return_1m = _parse_pct(rank.get("近1月"))
            return_3m = _parse_pct(rank.get("近3月"))
            return_6m = _parse_pct(rank.get("近6月"))
            return_1y = _parse_pct(rank.get("近1年"))
        except Exception:
            continue

        # 至少有3个月数据
        if return_3m is None:
            continue

        # 综合评分: 近1月(10%) + 近3月(30%) + 近6月(30%) + 近1年(30%)
        score = (
            (return_1m or 0) * 0.1
            + return_3m * 0.3
            + (return_6m or 0) * 0.3
            + (return_1y or 0) * 0.3
        )

        m["return_1m"] = return_1m
        m["return_3m"] = return_3m
        m["return_6m"] = return_6m
        m["return_1y"] = return_1y
        m["return_1w"] = _parse_pct(rank.get("近1周"))
        m["composite_score"] = round(score, 2)
        m["fee"] = rank.get("手续费", "")
        results.append(m)

    # 按综合评分排序
    results.sort(key=lambda x: x.get("composite_score", -999), reverse=True)

    # 去掉 A/C 重复
    final = _dedupe_share_classes(results)

    # 自动加入观察池
    today = datetime.now().strftime("%Y-%m-%d")
    keyword_str = "+".join(keywords)
    added = 0
    for c in final[:top_n]:
        existing = execute_query(
            "SELECT fund_code FROM watchlist WHERE fund_code = ?",
            (c["fund_code"],),
        )
        if not existing:
            execute_write(
                """INSERT INTO watchlist (fund_code, added_date, reason, target_action, notes)
                   VALUES (?, ?, ?, 'watch', ?)""",
                (
                    c["fund_code"],
                    today,
                    f"主题搜索: {keyword_str}",
                    json.dumps({
                        "name": c["fund_name"],
                        "return_3m": c.get("return_3m"),
                        "return_1y": c.get("return_1y"),
                    }, ensure_ascii=False),
                ),
            )
            added += 1

    console.print(f"  [green]搜索 \"{keyword_str}\": 匹配 {len(unique_matches)} 只, 有效 {len(final)} 只, 新增 {added} 只到观察池[/]")

    return final[:top_n]


def discover_top_funds(top_n: int = 20) -> list[dict]:
    """从全市场筛选综合排名最优的基金

    筛选维度:
    - 近3月业绩 top 30%
    - 近1年业绩 > 0
    - 过滤掉货币基金、理财型、定开型

    Returns:
        [{"fund_code", "fund_name", "fund_type", "return_3m", "return_1y", "composite_score"}]
    """
    rankings = _get_fund_rankings()
    if rankings.empty:
        return []

    # 过滤
    df = rankings.copy()
    df = df[~df["基金简称"].str.contains("货币|理财|定开|FOF|QDII", na=False)]

    # 解析数值列
    for col in ["近1周", "近1月", "近3月", "近6月", "近1年"]:
        df[col] = df[col].apply(_parse_pct)

    # 要求有3个月和1年数据
    df = df.dropna(subset=["近3月", "近1年"])

    # 综合评分: 近1月(10%) + 近3月(30%) + 近6月(30%) + 近1年(30%)
    df["composite_score"] = (
        df["近1月"].fillna(0) * 0.1
        + df["近3月"] * 0.3
        + df["近6月"].fillna(0) * 0.3
        + df["近1年"] * 0.3
    )

    # 排序
    df = df.sort_values("composite_score", ascending=False)

    results = []
    for _, row in df.head(top_n * 3).iterrows():
        results.append({
            "fund_code": str(row["基金代码"]),
            "fund_name": row["基金简称"],
            "fund_type": "",
            "return_1w": row.get("近1周"),
            "return_1m": row.get("近1月"),
            "return_3m": row["近3月"],
            "return_6m": row.get("近6月"),
            "return_1y": row["近1年"],
            "composite_score": round(row["composite_score"], 2),
        })

    # 去掉 A/C 重复
    final = _dedupe_share_classes(results)
    return final[:top_n]


def update_dynamic_pool(hotspots: list[dict] = None) -> list[dict]:
    """更新动态基金候选池

    组合三个来源:
    1. 热点板块对应的主题基金 (每个热点取 top 3)
    2. 全市场综合排名 top 10
    3. 现有观察池

    Args:
        hotspots: 热点列表 (来自 detect_hotspots), 如果为 None 则从数据库获取

    Returns:
        完整的候选基金列表
    """
    candidates = []
    seen_codes = set()

    # 1. 热点驱动
    if hotspots is None:
        hotspots_db = execute_query(
            """SELECT sector_name, score FROM hotspots
               WHERE status = 'active' AND score >= 40
               ORDER BY score DESC LIMIT 5"""
        )
        hotspot_sectors = [h["sector_name"] for h in hotspots_db]
    else:
        hotspot_sectors = [h["sector_name"] for h in hotspots if h["score"] >= 40]

    for sector in hotspot_sectors:
        console.print(f"  [dim]搜索 {sector} 相关基金...[/]")
        funds = discover_sector_funds(sector, top_n=3)
        for f in funds:
            if f["fund_code"] not in seen_codes:
                f["source"] = f"hotspot:{sector}"
                candidates.append(f)
                seen_codes.add(f["fund_code"])

    # 2. 全市场 top
    console.print("  [dim]全市场筛选...[/]")
    top_funds = discover_top_funds(top_n=10)
    for f in top_funds:
        if f["fund_code"] not in seen_codes:
            f["source"] = "top_rank"
            candidates.append(f)
            seen_codes.add(f["fund_code"])

    # 3. 现有观察池
    watchlist = execute_query("SELECT fund_code FROM watchlist")
    for w in watchlist:
        if w["fund_code"] not in seen_codes:
            seen_codes.add(w["fund_code"])

    # 自动加入观察池 (标记为自动发现)
    today = datetime.now().strftime("%Y-%m-%d")
    added = 0
    for c in candidates:
        existing = execute_query(
            "SELECT fund_code FROM watchlist WHERE fund_code = ?",
            (c["fund_code"],),
        )
        if not existing:
            execute_write(
                """INSERT INTO watchlist (fund_code, added_date, reason, target_action, notes)
                   VALUES (?, ?, ?, 'watch', ?)""",
                (
                    c["fund_code"],
                    today,
                    f"自动发现: {c.get('source', 'unknown')}",
                    json.dumps({
                        "name": c["fund_name"],
                        "return_3m": c.get("return_3m"),
                        "return_1y": c.get("return_1y"),
                    }, ensure_ascii=False),
                ),
            )
            added += 1

    console.print(f"  [green]候选池: {len(candidates)} 只基金 (新增 {added} 只到观察池)[/]")

    return candidates


def print_discovery_report(candidates: list[dict]):
    """输出基金发现报告"""
    if not candidates:
        console.print("[yellow]未发现新基金[/]")
        return

    table = Table(title="基金发现报告")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("来源", style="dim")
    table.add_column("近3月")
    table.add_column("近1年")

    for c in candidates[:20]:
        ret_3m = c.get("return_3m")
        ret_1y = c.get("return_1y")
        table.add_row(
            c["fund_code"],
            c["fund_name"][:16],
            c.get("source", "-")[:20],
            f"{ret_3m:+.1f}%" if ret_3m is not None else "-",
            f"{ret_1y:+.1f}%" if ret_1y is not None else "-",
        )

    console.print(table)


def seed_fund_universe():
    """从 config.fund_universe 导入种子基金到观察池

    幂等操作: 已存在的基金不会重复插入。
    """
    universe = CONFIG.get("fund_universe", {})
    if not universe:
        return

    today = datetime.now().strftime("%Y-%m-%d")
    added = 0

    for category, funds in universe.items():
        for fund in funds:
            code = fund["code"]
            name = fund["name"]
            existing = execute_query(
                "SELECT fund_code FROM watchlist WHERE fund_code = ?", (code,)
            )
            if not existing:
                execute_write(
                    """INSERT INTO watchlist
                       (fund_code, added_date, reason, target_action, notes, category)
                       VALUES (?, ?, ?, 'watch', ?, ?)""",
                    (code, today, f"seed:{category}", name, category),
                )
                added += 1
            else:
                # 确保已有条目的 category 正确
                execute_write(
                    "UPDATE watchlist SET category = ? WHERE fund_code = ? AND (category IS NULL OR category = 'equity')",
                    (category, code),
                )

    if added > 0:
        console.print(f"  [green]种子基金池: 新增 {added} 只到观察池[/]")

        # 下载新增基金的净值数据
        from src.data.fund_data import batch_update_funds
        new_codes = []
        for category, funds in universe.items():
            for fund in funds:
                nav_count = execute_query(
                    "SELECT COUNT(*) as cnt FROM fund_nav WHERE fund_code = ?",
                    (fund["code"],),
                )
                if not nav_count or nav_count[0]["cnt"] < 30:
                    new_codes.append(fund["code"])

        if new_codes:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            console.print(f"  [dim]下载种子基金净值 ({len(new_codes)} 只)...[/]")
            batch_update_funds(new_codes, start_date=start_date)
    else:
        console.print("  [dim]种子基金池已就绪[/]")


# ── 工具函数 ──────────────────────────────────────────────


def _parse_pct(value) -> float | None:
    """解析百分比字符串"""
    if value is None or value == "" or value == "---":
        return None
    try:
        if isinstance(value, str):
            return float(value.replace("%", "").strip())
        return float(value)
    except (ValueError, TypeError):
        return None


def _dedupe_share_classes(funds: list[dict]) -> list[dict]:
    """去除 A/C 份额重复, 优先保留 A 份额 (费率通常更优长期持有)"""
    seen_names = {}
    result = []
    for f in funds:
        # 去掉尾部的 A/B/C/E 标记来比较
        base_name = f["fund_name"].rstrip("ABCDE ").strip()
        if base_name not in seen_names:
            seen_names[base_name] = True
            result.append(f)
    return result
