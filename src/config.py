"""貔貅系统全局配置"""

from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

CONFIG = {
    # 账户
    "initial_capital": 10000,
    "current_cash": 10000,

    # 风险参数
    "max_single_position_pct": 0.30,
    "max_total_position_pct": 0.90,
    "min_cash_reserve_pct": 0.10,
    "max_drawdown_soft": 0.05,
    "max_drawdown_hard": 0.10,
    "single_fund_stop_loss": 0.08,
    "kelly_fraction": 0.5,

    # 交易费用（支付宝1折）
    "subscription_fee_discount": 0.1,
    "short_term_penalty_days": 7,
    "short_term_penalty_rate": 0.015,

    # 市场时间
    "market_timezone": "Asia/Shanghai",
    "trading_hours": {"open": "09:30", "close": "15:00"},

    # 关注的市场指数
    "benchmark_indices": [
        {"code": "000001", "name": "上证指数"},
        {"code": "399001", "name": "深证成指"},
        {"code": "399006", "name": "创业板指"},
        {"code": "000300", "name": "沪深300"},
        {"code": "000905", "name": "中证500"},
    ],

    # 数据库
    "db_path": str(PROJECT_ROOT / "db" / "pixiu.db"),

    # 缓存
    "cache_dir": str(PROJECT_ROOT / "data" / "cache"),
    "cache_ttl_hours": 12,

    # 报告
    "reports_dir": str(PROJECT_ROOT / "reports"),
    "docs_dir": str(PROJECT_ROOT / "docs"),

    # LLM 智能体 — 双后端支持 (通过 .env 中 LLM_PROVIDER 切换)
    "llm": {
        "provider": "gemini",  # "gemini" 或 "anthropic"，运行时从 .env 覆盖
        "max_tokens": 4096,
        "max_retries": 3,
        "retry_backoff_base": 2,
        "retry_backoff_max": 8,
        "enable_provider_fallback": True,
        "enable_thinking": True,
        "enable_reflection": True,
        "reflection_periods": [7, 30],  # 天
        # Gemini 配置
        "gemini": {
            "analysis_model": "gemini-2.0-flash",
            "decision_model": "gemini-2.5-pro",
            "critical_model": "gemini-2.5-pro",
            "thinking_budget": 4096,
            "critical_thinking_budget": 8192,
        },
        # Anthropic 配置
        "anthropic": {
            "analysis_model": "claude-haiku-4-5-20251001",
            "decision_model": "claude-sonnet-4-6",
            "critical_model": "claude-opus-4-6",
            "thinking_budget": 3000,
            "critical_thinking_budget": 5000,
        },
    },

    # 基金池 — 5 大资产类别种子
    "fund_universe": {
        # 偏股型 (已有的通过 watchlist 自动发现，不在此重复)
        "equity": [],

        # 债券型
        "bond": [
            {"code": "217022", "name": "招商产业债券A"},
            {"code": "110017", "name": "易方达增强回报债券A"},
            {"code": "003376", "name": "广发中债7-10年国开债指数A"},
            {"code": "070009", "name": "嘉实超短债C"},
            {"code": "006662", "name": "易方达安悦超短债A"},
        ],

        # 指数型
        "index": [
            {"code": "110020", "name": "易方达沪深300ETF联接A"},
            {"code": "000962", "name": "天弘中证500ETF联接A"},
            {"code": "001593", "name": "天弘创业板ETF联接C"},
        ],

        # 黄金
        "gold": [
            {"code": "000307", "name": "易方达黄金ETF联接A"},
            {"code": "002610", "name": "博时黄金ETF联接A"},
        ],

        # QDII (海外)
        "qdii": [
            {"code": "270042", "name": "广发纳斯达克100ETF联接A"},
            {"code": "050025", "name": "博时标普500ETF联接A"},
            {"code": "161125", "name": "易方达标普500指数A"},
        ],
    },

    # 分类别评分基准 (年化收益目标 / 波动率上限 / 回撤上限)
    "scoring_targets": {
        "equity": {"return_target": 0.20, "vol_cap": 0.40, "dd_cap": 0.30},
        "bond":   {"return_target": 0.05, "vol_cap": 0.08, "dd_cap": 0.05},
        "index":  {"return_target": 0.15, "vol_cap": 0.35, "dd_cap": 0.25},
        "gold":   {"return_target": 0.10, "vol_cap": 0.25, "dd_cap": 0.20},
        "qdii":   {"return_target": 0.15, "vol_cap": 0.35, "dd_cap": 0.25},
    },

    # 项目根目录（供 agent 加载 .env）
    "project_root": str(PROJECT_ROOT),
}
