"""SQLite 数据库操作封装"""

import json
import sqlite3
from pathlib import Path

from src.config import CONFIG

SCHEMA_SQL = """
-- 基金基本信息
CREATE TABLE IF NOT EXISTS funds (
    fund_code TEXT PRIMARY KEY,
    fund_name TEXT NOT NULL,
    fund_type TEXT,
    management_company TEXT,
    establishment_date TEXT,
    benchmark TEXT,
    subscription_fee_rate REAL,
    redemption_fee_rate TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 基金净值历史
CREATE TABLE IF NOT EXISTS fund_nav (
    fund_code TEXT NOT NULL,
    nav_date TEXT NOT NULL,
    nav REAL NOT NULL,
    acc_nav REAL,
    daily_return REAL,
    PRIMARY KEY (fund_code, nav_date)
);

-- 市场指数数据
CREATE TABLE IF NOT EXISTS market_indices (
    index_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    PRIMARY KEY (index_code, trade_date)
);

-- 持仓记录
CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_code TEXT NOT NULL,
    shares REAL NOT NULL,
    cost_price REAL NOT NULL,
    current_nav REAL,
    buy_date TEXT NOT NULL,
    status TEXT DEFAULT 'holding',
    sell_date TEXT,
    sell_nav REAL,
    profit_loss REAL,
    profit_loss_pct REAL,
    notes TEXT
);

-- 交易记录
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    fund_code TEXT NOT NULL,
    action TEXT NOT NULL,
    amount REAL NOT NULL,
    nav REAL NOT NULL,
    shares REAL,
    fee REAL DEFAULT 0,
    reason TEXT,
    confidence REAL,
    report_path TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 账户状态快照
CREATE TABLE IF NOT EXISTS account_snapshots (
    snapshot_date TEXT PRIMARY KEY,
    total_value REAL NOT NULL,
    cash REAL NOT NULL,
    invested REAL NOT NULL,
    total_profit_loss REAL,
    total_return_pct REAL,
    max_drawdown_pct REAL,
    holdings_json TEXT
);

-- 分析记录
CREATE TABLE IF NOT EXISTS analysis_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_date TEXT NOT NULL,
    analysis_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    details_json TEXT,
    doc_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 基金观察池
CREATE TABLE IF NOT EXISTS watchlist (
    fund_code TEXT PRIMARY KEY,
    added_date TEXT NOT NULL,
    reason TEXT,
    target_action TEXT,
    notes TEXT,
    category TEXT DEFAULT 'equity'
);

-- ========== 热点发现 ==========

-- 行业板块快照 (每日)
CREATE TABLE IF NOT EXISTS sector_snapshots (
    sector_name TEXT NOT NULL,
    sector_code TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    close REAL,
    change_pct REAL,                    -- 当日涨跌幅
    volume REAL,
    amount REAL,
    turnover_rate REAL,                 -- 换手率
    net_inflow REAL,                    -- 主力净流入
    rank_today INTEGER,                 -- 当日涨幅排名
    PRIMARY KEY (sector_code, snapshot_date)
);

-- 热点追踪
CREATE TABLE IF NOT EXISTS hotspots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_name TEXT NOT NULL,
    sector_code TEXT NOT NULL,
    detected_date TEXT NOT NULL,
    hotspot_type TEXT NOT NULL,         -- emerging / accelerating / peak / fading
    score REAL NOT NULL,                -- 热度评分 0-100
    evidence TEXT,                      -- 判断依据 (JSON)
    status TEXT DEFAULT 'active',       -- active / expired
    expired_date TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ========== 自动学习 ==========

-- 信号验证 (每个信号产生后, 30天回来验证)
CREATE TABLE IF NOT EXISTS signal_validation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date TEXT NOT NULL,           -- 信号产生日期
    fund_code TEXT NOT NULL,
    strategy_name TEXT NOT NULL,         -- trend_following / mean_reversion / momentum / composite
    signal_type TEXT NOT NULL,           -- strong_buy / buy / sell / strong_sell
    confidence REAL NOT NULL,            -- 预测置信度
    regime TEXT,                         -- 信号产生时的市场状态
    nav_at_signal REAL,                  -- 信号时净值
    nav_after_7d REAL,                   -- 7天后净值
    nav_after_30d REAL,                  -- 30天后净值
    return_7d REAL,                      -- 7天后收益率
    return_30d REAL,                     -- 30天后收益率
    is_correct_7d INTEGER,              -- 7天后方向是否正确 (1/0/NULL)
    is_correct_30d INTEGER,             -- 30天后方向是否正确
    validated_at TEXT,                   -- 验证时间
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ========== LLM 智能体 ==========

-- LLM 决策记录
CREATE TABLE IF NOT EXISTS agent_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_date TEXT NOT NULL,
    market_context TEXT NOT NULL,
    quant_signals TEXT NOT NULL,
    llm_analysis TEXT NOT NULL,
    llm_decision TEXT NOT NULL,
    confidence REAL,
    reasoning TEXT,
    challenge TEXT,
    model_used TEXT,
    tokens_used INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 反思日志
CREATE TABLE IF NOT EXISTS reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reflection_date TEXT NOT NULL,
    decision_id INTEGER REFERENCES agent_decisions(id),
    period TEXT NOT NULL,
    original_signal TEXT,
    actual_outcome TEXT,
    was_correct INTEGER,
    reflection_text TEXT NOT NULL,
    lessons_learned TEXT,
    cognitive_update TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 知识库 (教训积累)
CREATE TABLE IF NOT EXISTS knowledge_base (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    source_reflection_id INTEGER,
    times_validated INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ========== 增强数据 ==========

-- 指数估值数据
CREATE TABLE IF NOT EXISTS index_valuation (
    index_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    pe REAL,
    pb REAL,
    dividend_yield REAL,
    pe_percentile REAL,
    pb_percentile REAL,
    PRIMARY KEY (index_code, trade_date)
);

-- 宏观经济指标
CREATE TABLE IF NOT EXISTS macro_indicators (
    indicator_name TEXT NOT NULL,
    report_date TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (indicator_name, report_date)
);

-- 基金经理信息
CREATE TABLE IF NOT EXISTS fund_managers (
    manager_id TEXT PRIMARY KEY,
    manager_name TEXT NOT NULL,
    company TEXT,
    total_fund_size REAL,
    years_of_experience REAL,
    best_return REAL,
    annual_return REAL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 情绪指标
CREATE TABLE IF NOT EXISTS sentiment_indicators (
    indicator_name TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    value REAL,
    percentile REAL,
    PRIMARY KEY (indicator_name, trade_date)
);

-- LLM 场景分析
CREATE TABLE IF NOT EXISTS scenario_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_date TEXT NOT NULL,
    bullish_scenario TEXT,
    bullish_probability REAL,
    base_scenario TEXT,
    base_probability REAL,
    bearish_scenario TEXT,
    bearish_probability REAL,
    expected_return REAL,
    model_used TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 策略表现统计 (按策略×市场状态聚合)
CREATE TABLE IF NOT EXISTS strategy_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,          -- 统计周期开始
    period_end TEXT NOT NULL,            -- 统计周期结束
    strategy_name TEXT NOT NULL,
    regime TEXT NOT NULL,
    total_signals INTEGER DEFAULT 0,
    correct_signals INTEGER DEFAULT 0,
    win_rate REAL,                       -- 胜率
    avg_return REAL,                     -- 平均收益
    avg_confidence REAL,                 -- 平均置信度
    confidence_accuracy REAL,            -- 置信度校准 (高置信度是否真的更准)
    recommended_weight REAL,             -- 根据表现计算的建议权重
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(period_end, strategy_name, regime)
);
"""


def get_db_path() -> str:
    return CONFIG["db_path"]


def get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    db_path = get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库 schema"""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        # 兼容升级: 给已有 watchlist 表加 category 列
        _migrate_watchlist_category(conn)
        # 知识库全文检索
        _migrate_knowledge_fts(conn)
    finally:
        conn.close()


def _migrate_watchlist_category(conn: sqlite3.Connection):
    """为旧数据库的 watchlist 表补 category 列"""
    cursor = conn.execute("PRAGMA table_info(watchlist)")
    columns = {row[1] for row in cursor.fetchall()}
    if "category" not in columns:
        conn.execute("ALTER TABLE watchlist ADD COLUMN category TEXT DEFAULT 'equity'")
        conn.commit()


def _migrate_knowledge_fts(conn: sqlite3.Connection):
    """创建知识库 FTS5 全文检索虚拟表"""
    try:
        conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
               USING fts5(content, category, content='knowledge_base', content_rowid='id',
                          tokenize='unicode61')"""
        )
        # 同步已有数据 (幂等)
        conn.execute(
            """INSERT OR IGNORE INTO knowledge_fts(rowid, content, category)
               SELECT id, content, category FROM knowledge_base"""
        )
        conn.commit()
    except Exception:
        pass  # FTS5 不可用时静默降级 (部分 SQLite 编译不含 FTS5)


def execute_query(sql: str, params: tuple = ()) -> list[dict]:
    """执行查询，返回字典列表"""
    conn = get_connection()
    try:
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def execute_write(sql: str, params: tuple = ()) -> int:
    """执行写入操作，返回受影响行数"""
    conn = get_connection()
    try:
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def execute_many(sql: str, params_list: list[tuple]) -> int:
    """批量写入"""
    conn = get_connection()
    try:
        cursor = conn.executemany(sql, params_list)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def upsert_fund_nav(fund_code: str, nav_records: list[dict]):
    """批量插入或更新基金净值数据"""
    if not nav_records:
        return
    conn = get_connection()
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO fund_nav
               (fund_code, nav_date, nav, acc_nav, daily_return)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    fund_code,
                    r["nav_date"],
                    r["nav"],
                    r.get("acc_nav"),
                    r.get("daily_return"),
                )
                for r in nav_records
            ],
        )
        conn.commit()
    finally:
        conn.close()


def upsert_market_index(index_code: str, records: list[dict]):
    """批量插入或更新市场指数数据"""
    if not records:
        return
    conn = get_connection()
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO market_indices
               (index_code, trade_date, open, high, low, close, volume, amount)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    index_code,
                    r["trade_date"],
                    r.get("open"),
                    r.get("high"),
                    r.get("low"),
                    r.get("close"),
                    r.get("volume"),
                    r.get("amount"),
                )
                for r in records
            ],
        )
        conn.commit()
    finally:
        conn.close()


def upsert_fund_info(fund: dict):
    """插入或更新基金基本信息"""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO funds
               (fund_code, fund_name, fund_type, management_company,
                establishment_date, benchmark, subscription_fee_rate,
                redemption_fee_rate, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (
                fund["fund_code"],
                fund["fund_name"],
                fund.get("fund_type"),
                fund.get("management_company"),
                fund.get("establishment_date"),
                fund.get("benchmark"),
                fund.get("subscription_fee_rate"),
                json.dumps(fund.get("redemption_fee_rate"))
                if fund.get("redemption_fee_rate")
                else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_fund_nav_history(
    fund_code: str, start_date: str = None, end_date: str = None
) -> list[dict]:
    """获取基金净值历史"""
    sql = "SELECT * FROM fund_nav WHERE fund_code = ?"
    params = [fund_code]
    if start_date:
        sql += " AND nav_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND nav_date <= ?"
        params.append(end_date)
    sql += " ORDER BY nav_date"
    return execute_query(sql, tuple(params))


def get_index_history(
    index_code: str, start_date: str = None, end_date: str = None
) -> list[dict]:
    """获取指数历史数据"""
    sql = "SELECT * FROM market_indices WHERE index_code = ?"
    params = [index_code]
    if start_date:
        sql += " AND trade_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND trade_date <= ?"
        params.append(end_date)
    sql += " ORDER BY trade_date"
    return execute_query(sql, tuple(params))


import functools

@functools.lru_cache(maxsize=128)
def classify_fund(fund_code: str, fund_name: str | None = None) -> str:
    """基金分类: equity / bond / index / gold / qdii

    优先查 watchlist.category，无则关键词匹配，默认 equity。
    """
    # 1. 查 watchlist
    rows = execute_query(
        "SELECT category FROM watchlist WHERE fund_code = ?", (fund_code,)
    )
    if rows and rows[0].get("category"):
        return rows[0]["category"]

    # 2. 查基金名称
    if fund_name is None:
        info = execute_query(
            "SELECT fund_name FROM funds WHERE fund_code = ?", (fund_code,)
        )
        fund_name = info[0]["fund_name"] if info else ""

    name = fund_name or ""

    # 3. 关键词匹配
    bond_keywords = ["债", "纯债", "短债", "利率", "信用"]
    gold_keywords = ["黄金", "贵金属"]
    qdii_keywords = ["QDII", "标普", "纳斯达克", "恒生", "美国", "海外"]
    index_keywords = ["ETF联接", "指数"]

    for kw in gold_keywords:
        if kw in name:
            return "gold"
    for kw in qdii_keywords:
        if kw in name:
            return "qdii"
    for kw in bond_keywords:
        if kw in name:
            return "bond"
    for kw in index_keywords:
        if kw in name:
            return "index"

    return "equity"
