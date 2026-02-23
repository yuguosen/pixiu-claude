"""貔貅飞书机器人入口 — WebSocket 长连接模式"""

import logging
import os
import threading
from datetime import datetime

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from src.memory.database import init_db

logger = logging.getLogger(__name__)


def _load_env():
    """从 .env 加载环境变量"""
    from pathlib import Path
    from src.config import CONFIG

    env_path = Path(CONFIG["project_root"]) / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _start_scheduler(client: lark.Client, chat_id: str | None):
    """启动定时调度器 (守护线程)

    工作日 15:50 自动执行日报并推送到配置的群。
    """
    import schedule
    import time

    from src.bot import cards
    from src.bot.handlers import handle_daily
    from src.bot.sender import send_card

    def daily_job():
        now = datetime.now()
        # 仅工作日执行 (周一=0 到 周五=4)
        if now.weekday() >= 5:
            logger.info("周末跳过定时日报")
            return

        logger.info("定时日报开始执行")
        if chat_id:
            send_card(client, chat_id, cards.processing_card("日常分析流程"))

        result_card = handle_daily()

        if chat_id:
            send_card(client, chat_id, result_card)
            logger.info("定时日报已推送到群 %s", chat_id)
        else:
            logger.info("定时日报完成, 但未配置推送群")

    schedule.every().day.at("15:50").do(daily_job)
    logger.info("定时调度已注册: 每工作日 15:50 执行日报")

    def run_schedule():
        while True:
            schedule.run_pending()
            time.sleep(30)

    thread = threading.Thread(target=run_schedule, daemon=True)
    thread.start()


def main():
    """飞书机器人主入口"""
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 加载环境变量
    _load_env()

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    push_chat_id = os.environ.get("FEISHU_PUSH_CHAT_ID", "")

    if not app_id or not app_secret:
        logger.error(
            "缺少飞书配置: 请在 .env 中设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
        )
        return

    # 初始化数据库
    init_db()

    # 创建飞书 API 客户端 (用于发消息)
    client = lark.Client.builder() \
        .app_id(app_id) \
        .app_secret(app_secret) \
        .log_level(lark.LogLevel.INFO) \
        .build()

    # 注册消息事件处理器
    from src.bot.router import build_event_handler
    message_handler = build_event_handler(client)

    event_handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(message_handler) \
        .build()

    # 启动定时调度器
    if push_chat_id:
        _start_scheduler(client, push_chat_id)
        logger.info("定时推送已配置, 目标群: %s", push_chat_id)
    else:
        logger.info("未配置 FEISHU_PUSH_CHAT_ID, 跳过定时推送")

    # WebSocket 长连接启动 (阻塞主线程)
    logger.info("貔貅飞书机器人启动中... (WebSocket 长连接)")
    ws_client = lark.ws.Client(
        app_id=app_id,
        app_secret=app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    ws_client.start()


if __name__ == "__main__":
    main()
