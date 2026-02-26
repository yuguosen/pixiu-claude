"""命令解析 + 分发"""

import json
import logging
import threading
import time

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from src.bot import cards, handlers
from src.bot.sender import reply_card
from src.bot.session import SessionManager

logger = logging.getLogger(__name__)

# ── 消息去重 (防止 SDK 重复投递) ──
_seen_messages: dict[str, float] = {}
_DEDUP_TTL = 60  # 60 秒内同一 message_id 只处理一次


def _is_duplicate(message_id: str) -> bool:
    """检查消息是否已处理过"""
    now = time.time()
    # 清理过期条目
    expired = [k for k, t in _seen_messages.items() if now - t > _DEDUP_TTL]
    for k in expired:
        del _seen_messages[k]
    if message_id in _seen_messages:
        return True
    _seen_messages[message_id] = now
    return False


# 命令映射: 用户输入 → 内部命令名
COMMAND_MAP = {
    "帮助": "help",
    "/help": "help",
    "help": "help",
    "行情": "market",
    "/market": "market",
    "市场": "market",
    "建议": "recommend",
    "/recommend": "recommend",
    "推荐": "recommend",
    "日报": "daily",
    "/daily": "daily",
    "持仓": "portfolio",
    "/portfolio": "portfolio",
    "组合": "portfolio",
    "历史": "history",
    "/history": "history",
    "交易": "history",
    "记录": "trade",
    "/trade": "trade",
    "配置": "allocation",
    "/allocation": "allocation",
    "资产配置": "allocation",
    "搜索": "search",
    "/search": "search",
}

# 耗时命令 — 需要在独立线程中执行
LONG_RUNNING_COMMANDS = {"recommend", "daily", "search"}

session_manager = SessionManager()


def _extract_text(event: P2ImMessageReceiveV1) -> str:
    """从飞书消息事件中提取纯文本"""
    msg = event.event.message
    if msg.message_type != "text":
        return ""
    try:
        content = json.loads(msg.content)
        text = content.get("text", "").strip()
        # 去掉 @机器人 的 mention 标记
        # 飞书 mention 格式: @_user_1 或类似
        if text.startswith("@"):
            parts = text.split(maxsplit=1)
            text = parts[1] if len(parts) > 1 else ""
        return text.strip()
    except (json.JSONDecodeError, AttributeError):
        return ""


def _get_user_id(event: P2ImMessageReceiveV1) -> str:
    """获取发送者用户 ID"""
    return event.event.sender.sender_id.open_id or ""


def _get_message_id(event: P2ImMessageReceiveV1) -> str:
    return event.event.message.message_id


def _parse_command(text: str) -> tuple[str, list[str]]:
    """解析命令和参数"""
    parts = text.split()
    if not parts:
        return "", []
    cmd_text = parts[0]
    args = parts[1:]
    cmd = COMMAND_MAP.get(cmd_text, "")
    return cmd, args


def _run_long_command(client: lark.Client, message_id: str, cmd: str, args: list[str] | None = None):
    """在独立线程中执行耗时命令"""
    try:
        if cmd == "recommend":
            result_card = handlers.handle_recommend()
        elif cmd == "daily":
            result_card = handlers.handle_daily()
        elif cmd == "search":
            keyword = " ".join(args) if args else ""
            result_card = handlers.handle_search(keyword)
        elif cmd == "market_sector":
            keyword = " ".join(args) if args else ""
            result_card = handlers.handle_market_sector(keyword)
        else:
            return
        reply_card(client, message_id, result_card)
    except Exception as e:
        logger.exception("长耗时命令 %s 执行失败", cmd)
        reply_card(client, message_id, cards.error_card(f"执行失败: {e}"))


def build_event_handler(client: lark.Client):
    """构建飞书消息事件处理函数"""

    def handle_message(data: P2ImMessageReceiveV1):
        text = _extract_text(data)
        if not text:
            return
        user_id = _get_user_id(data)
        message_id = _get_message_id(data)

        # 消息去重
        if _is_duplicate(message_id):
            logger.debug("跳过重复消息: %s", message_id)
            return

        logger.info("收到消息: user=%s text=%s", user_id, text)

        # 1. 检查是否有活跃的多步会话
        if session_manager.has_active_session(user_id):
            _handle_session(client, message_id, user_id, text)
            return

        # 2. 解析命令
        cmd, args = _parse_command(text)
        if not cmd:
            reply_card(client, message_id, cards.help_card())
            return

        # 3. 处理命令
        if cmd == "help":
            reply_card(client, message_id, handlers.handle_help())

        elif cmd == "portfolio":
            reply_card(client, message_id, handlers.handle_portfolio())

        elif cmd == "history":
            limit = int(args[0]) if args and args[0].isdigit() else 20
            reply_card(client, message_id, handlers.handle_history(limit))

        elif cmd == "market":
            if args:
                keyword = " ".join(args)
                reply_card(client, message_id, cards.processing_card(f"查询 \"{keyword}\" 板块行情"))
                thread = threading.Thread(
                    target=_run_long_command,
                    args=(client, message_id, "market_sector", args),
                    daemon=True,
                )
                thread.start()
            else:
                reply_card(client, message_id, handlers.handle_market())

        elif cmd == "allocation":
            reply_card(client, message_id, handlers.handle_allocation())

        elif cmd == "trade":
            prompt = session_manager.start_trade_session(user_id)
            reply_card(client, message_id, cards.trade_prompt_card("第1步", prompt))

        elif cmd == "search":
            keyword = " ".join(args)
            if not keyword:
                reply_card(client, message_id, cards.error_card("请输入搜索关键词，如: 搜索 养老"))
                return
            reply_card(client, message_id, cards.processing_card(f"搜索 \"{keyword}\""))
            thread = threading.Thread(
                target=_run_long_command,
                args=(client, message_id, cmd, args),
                daemon=True,
            )
            thread.start()

        elif cmd in LONG_RUNNING_COMMANDS:
            # 先回复 "处理中", 再在后台线程执行
            task_name = "生成交易建议" if cmd == "recommend" else "日常分析流程"
            reply_card(client, message_id, cards.processing_card(task_name))
            thread = threading.Thread(
                target=_run_long_command,
                args=(client, message_id, cmd),
                daemon=True,
            )
            thread.start()

        else:
            reply_card(client, message_id, cards.help_card())

    return handle_message


def _handle_session(client: lark.Client, message_id: str, user_id: str, text: str):
    """处理多步会话输入"""
    result, data = session_manager.process(user_id, text)

    if result == "cancelled":
        reply_card(client, message_id, cards.error_card("已取消交易录入"))

    elif result == "expired":
        reply_card(client, message_id, cards.error_card("会话已超时, 请重新开始"))

    elif result == "confirm":
        reply_card(client, message_id, cards.trade_confirm_card(data))

    elif result == "success":
        result_card = handlers.handle_trade_record(data)
        reply_card(client, message_id, result_card)

    elif result.startswith("error:"):
        error_msg = result[6:]
        reply_card(client, message_id, cards.error_card(error_msg))

    else:
        # 正常的下一步提示
        step_num = len([k for k in ("fund_code", "action", "amount", "nav", "trade_date", "reason") if k in (data or {})]) + 1
        # 简单推算步骤号
        session = session_manager._sessions.get(user_id)
        step = session.step + 1 if session else 1
        reply_card(client, message_id, cards.trade_prompt_card(f"第{step}步", result))
