"""飞书消息发送工具"""

import json
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    PatchMessageRequest,
    PatchMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

logger = logging.getLogger(__name__)


def reply_text(client: lark.Client, message_id: str, text: str) -> bool:
    """回复纯文本消息"""
    body = ReplyMessageRequestBody.builder() \
        .content(json.dumps({"text": text})) \
        .msg_type("text") \
        .build()
    req = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(body) \
        .build()
    resp = client.im.v1.message.reply(req)
    if not resp.success():
        logger.error("reply_text failed: %s %s", resp.code, resp.msg)
    return resp.success()


def reply_card(client: lark.Client, message_id: str, card: dict) -> str | None:
    """回复卡片消息, 返回消息 ID (用于后续更新)"""
    body = ReplyMessageRequestBody.builder() \
        .content(json.dumps(card)) \
        .msg_type("interactive") \
        .build()
    req = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(body) \
        .build()
    resp = client.im.v1.message.reply(req)
    if not resp.success():
        logger.error("reply_card failed: %s %s", resp.code, resp.msg)
        return None
    return resp.data.message_id if resp.data else None


def send_card(client: lark.Client, chat_id: str, card: dict) -> str | None:
    """主动发送卡片到群/用户"""
    body = CreateMessageRequestBody.builder() \
        .receive_id(chat_id) \
        .content(json.dumps(card)) \
        .msg_type("interactive") \
        .build()
    req = CreateMessageRequest.builder() \
        .receive_id_type("chat_id") \
        .request_body(body) \
        .build()
    resp = client.im.v1.message.create(req)
    if not resp.success():
        logger.error("send_card failed: %s %s", resp.code, resp.msg)
        return None
    return resp.data.message_id if resp.data else None


def update_card(client: lark.Client, message_id: str, card: dict) -> bool:
    """更新已发送的卡片"""
    body = PatchMessageRequestBody.builder() \
        .content(json.dumps(card)) \
        .build()
    req = PatchMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(body) \
        .build()
    resp = client.im.v1.message.patch(req)
    if not resp.success():
        logger.error("update_card failed: %s %s", resp.code, resp.msg)
    return resp.success()
