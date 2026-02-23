"""反思引擎 — 决策复盘 + 知识提炼 + 教训检索"""

import json
from datetime import datetime, timedelta

from rich.console import Console
from rich.table import Table

from src.config import CONFIG
from src.memory.database import execute_query, execute_write, get_connection

console = Console()


def get_pending_reflections(period_days: int = 7) -> list[dict]:
    """获取需要复盘的决策（到期且未复盘）

    Args:
        period_days: 复盘周期（7 或 30）

    Returns:
        待复盘的 agent_decisions 记录列表
    """
    period_label = f"{period_days}d"
    cutoff_date = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d")

    # 找出到期的决策，且没有对应周期的反思记录
    decisions = execute_query(
        """SELECT ad.*
           FROM agent_decisions ad
           WHERE ad.decision_date <= ?
             AND ad.id NOT IN (
                 SELECT COALESCE(decision_id, 0)
                 FROM reflections
                 WHERE period = ?
             )
           ORDER BY ad.decision_date""",
        (cutoff_date, period_label),
    )
    return decisions


def _build_actual_outcome(decision: dict, period_days: int) -> str:
    """构建决策的实际结果描述"""
    decision_date = decision["decision_date"]
    target_date = (
        datetime.strptime(decision_date, "%Y-%m-%d") + timedelta(days=period_days)
    ).strftime("%Y-%m-%d")

    # 从决策记录中提取推荐的基金代码
    try:
        llm_decision = json.loads(decision.get("llm_decision", "[]"))
    except (json.JSONDecodeError, TypeError):
        llm_decision = []

    outcome_lines = []
    for rec in llm_decision:
        fund_code = rec.get("fund_code", "")
        action = rec.get("action", "hold")
        if not fund_code or fund_code == "-":
            continue

        # 查询决策时和现在的净值
        nav_at_decision = execute_query(
            """SELECT nav FROM fund_nav
               WHERE fund_code = ? AND nav_date <= ?
               ORDER BY nav_date DESC LIMIT 1""",
            (fund_code, decision_date),
        )
        nav_after = execute_query(
            """SELECT nav FROM fund_nav
               WHERE fund_code = ? AND nav_date <= ?
               ORDER BY nav_date DESC LIMIT 1""",
            (fund_code, target_date),
        )

        if nav_at_decision and nav_after:
            nav_before = nav_at_decision[0]["nav"]
            nav_now = nav_after[0]["nav"]
            change_pct = (nav_now - nav_before) / nav_before * 100

            was_correct = (
                (action in ("buy", "watch") and change_pct > 0)
                or (action == "sell" and change_pct < 0)
            )
            result_label = "正确" if was_correct else "错误"

            fund_info = execute_query(
                "SELECT fund_name FROM funds WHERE fund_code = ?", (fund_code,)
            )
            fund_name = fund_info[0]["fund_name"] if fund_info else fund_code

            outcome_lines.append(
                f"- {fund_name} ({fund_code}): 建议{action}, "
                f"实际{period_days}天涨跌 {change_pct:+.2f}% "
                f"(净值 {nav_before:.4f} → {nav_now:.4f}) — {result_label}"
            )

    if not outcome_lines:
        return f"决策日 {decision_date} 后 {period_days} 天，缺少足够的净值数据进行评估。"

    return "\n".join(outcome_lines)


def run_reflection_cycle():
    """执行反思循环 — 检查所有到期决策并触发 LLM 复盘"""
    from src.agent.brain import reflect_on_decision

    reflection_periods = CONFIG.get("llm", {}).get("reflection_periods", [7, 30])
    total_reflections = 0
    total_tokens = 0

    for period_days in reflection_periods:
        pending = get_pending_reflections(period_days)
        if not pending:
            continue

        console.print(f"\n  [dim]发现 {len(pending)} 条待 {period_days}d 复盘的决策[/]")

        for decision in pending:
            # 构建实际结果
            actual_outcome = _build_actual_outcome(decision, period_days)

            # 调用 LLM 反思
            result, tokens = reflect_on_decision(
                decision_record=decision,
                actual_outcome=actual_outcome,
                period=f"{period_days}d",
            )
            total_tokens += tokens

            if result:
                # 保存反思记录
                _save_reflection(
                    decision_id=decision["id"],
                    period=f"{period_days}d",
                    original_signal=decision.get("quant_signals", ""),
                    actual_outcome=actual_outcome,
                    result=result,
                )

                # 提炼教训入知识库
                _update_knowledge_base(result, decision["id"])
                total_reflections += 1

    if total_reflections > 0:
        console.print(
            f"  [dim]完成 {total_reflections} 条反思 ({total_tokens} tokens)[/]"
        )
    else:
        console.print("  [dim]暂无待复盘的决策[/]")


def _save_reflection(
    decision_id: int,
    period: str,
    original_signal: str,
    actual_outcome: str,
    result,
):
    """保存反思记录到数据库"""
    execute_write(
        """INSERT INTO reflections
           (reflection_date, decision_id, period, original_signal,
            actual_outcome, was_correct, reflection_text,
            lessons_learned, cognitive_update)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().strftime("%Y-%m-%d"),
            decision_id,
            period,
            original_signal[:2000],
            actual_outcome,
            1 if result.was_correct else 0,
            result.accuracy_analysis,
            json.dumps(result.lessons, ensure_ascii=False),
            json.dumps(result.strategy_suggestions, ensure_ascii=False),
        ),
    )


def _sync_fts(content: str, category: str):
    """将新知识同步写入 FTS5 索引"""
    try:
        new_id = execute_query("SELECT last_insert_rowid() as id")[0]["id"]
        execute_write(
            "INSERT INTO knowledge_fts(rowid, content, category) VALUES (?, ?, ?)",
            (new_id, content, category),
        )
    except Exception:
        pass  # FTS5 不可用时静默降级


def _update_knowledge_base(result, source_reflection_id: int | None = None):
    """从反思结果中提炼教训存入知识库"""
    for lesson in result.lessons:
        # 检查是否已有类似教训
        existing = execute_query(
            "SELECT id FROM knowledge_base WHERE content = ? AND is_active = 1",
            (lesson,),
        )
        if existing:
            # 增加验证次数
            execute_write(
                "UPDATE knowledge_base SET times_validated = times_validated + 1 WHERE id = ?",
                (existing[0]["id"],),
            )
        else:
            execute_write(
                """INSERT INTO knowledge_base (category, content, source_reflection_id)
                   VALUES (?, ?, ?)""",
                ("strategy_lesson", lesson, source_reflection_id),
            )
            _sync_fts(lesson, "strategy_lesson")

    for suggestion in result.strategy_suggestions:
        existing = execute_query(
            "SELECT id FROM knowledge_base WHERE content = ? AND is_active = 1",
            (suggestion,),
        )
        if not existing:
            execute_write(
                """INSERT INTO knowledge_base (category, content, source_reflection_id)
                   VALUES (?, ?, ?)""",
                ("risk_insight", suggestion, source_reflection_id),
            )
            _sync_fts(suggestion, "risk_insight")


def get_relevant_knowledge(regime: str, limit: int = 10) -> list[str]:
    """从知识库检索与当前市场状态相关的教训

    优先使用 FTS5 语义匹配 + 权重混合排序，降级到原始查询。

    Args:
        regime: 当前市场状态
        limit: 最多返回条数

    Returns:
        教训内容列表
    """
    # 优先: FTS5 混合检索 (语义匹配 + 验证次数 + 时间衰减)
    try:
        rows = execute_query(
            """SELECT kb.content
               FROM knowledge_base kb
               JOIN knowledge_fts fts ON kb.id = fts.rowid
               WHERE knowledge_fts MATCH ?
                 AND kb.is_active = 1
               ORDER BY rank * -0.4
                   + MIN(kb.times_validated, 10) * 0.3
                   + (1.0 / (1 + julianday('now') - julianday(kb.created_at))) * 50 * 0.3
               DESC LIMIT ?""",
            (regime, limit),
        )
        if rows:
            return [r["content"] for r in rows]
    except Exception:
        pass  # FTS5 不可用时降级

    # 降级: 原始查询 + 时间衰减
    knowledge = execute_query(
        """SELECT content FROM knowledge_base
           WHERE is_active = 1
           ORDER BY times_validated DESC, created_at DESC
           LIMIT ?""",
        (limit,),
    )
    return [k["content"] for k in knowledge]


def print_reflection_report():
    """打印反思报告（最近的反思记录）"""
    reflections = execute_query(
        """SELECT r.*, ad.decision_date, ad.confidence as original_confidence
           FROM reflections r
           LEFT JOIN agent_decisions ad ON r.decision_id = ad.id
           ORDER BY r.created_at DESC LIMIT 10"""
    )

    if not reflections:
        console.print("\n[yellow]暂无反思记录[/]")
        console.print("反思会在决策 7/30 天后自动触发，或运行 'uv run pixiu reflect' 手动触发")
        return

    console.print("\n[bold]═══ 反思复盘记录 ═══[/]\n")

    for ref in reflections:
        correct = ref.get("was_correct")
        icon = "[green]✓[/]" if correct else "[red]✗[/]"

        console.print(
            f"  {icon} [{ref.get('period', '')}] "
            f"决策日 {ref.get('decision_date', '?')} → "
            f"反思日 {ref['reflection_date']}"
        )
        console.print(f"    {ref['reflection_text'][:200]}")

        # 教训
        try:
            lessons = json.loads(ref.get("lessons_learned", "[]"))
            if lessons:
                for lesson in lessons[:2]:
                    console.print(f"    [dim]→ {lesson}[/]")
        except (json.JSONDecodeError, TypeError):
            pass
        console.print()


def print_knowledge_report():
    """打印知识库报告"""
    knowledge = execute_query(
        """SELECT * FROM knowledge_base
           WHERE is_active = 1
           ORDER BY times_validated DESC, created_at DESC"""
    )

    if not knowledge:
        console.print("\n[yellow]知识库为空[/]")
        console.print("教训会在反思复盘后自动积累")
        return

    console.print(f"\n[bold]═══ 知识库 ({len(knowledge)} 条教训) ═══[/]\n")

    table = Table()
    table.add_column("类别", style="cyan", width=16)
    table.add_column("教训内容", width=60)
    table.add_column("验证次数", justify="center")
    table.add_column("创建日期", style="dim")

    category_names = {
        "strategy_lesson": "策略教训",
        "risk_insight": "风险洞察",
        "market_pattern": "市场规律",
    }

    for k in knowledge:
        table.add_row(
            category_names.get(k["category"], k["category"]),
            k["content"][:80],
            str(k["times_validated"]),
            k["created_at"][:10] if k["created_at"] else "",
        )

    console.print(table)
