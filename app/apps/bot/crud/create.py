"""Telegram send operations — send messages, typing actions, register webhook."""

import logging
from typing import Any

from app.core.config import settings
from app.core.resource import res

logger = logging.getLogger(__name__)


async def send_message(chat_id: int, text: str, parse_mode: str = "MarkdownV2", reply_markup: dict[str, Any] | None = None) -> dict:
    """Send a message to a Telegram chat."""
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    resp = await res.telegram_client.post("sendMessage", json=payload)
    resp.raise_for_status()
    logger.info("Sent message to chat %d", chat_id)
    return resp.json()


async def send_typing_action(chat_id: int) -> None:
    """Send a typing indicator to a Telegram chat."""
    resp = await res.telegram_client.post(
        "sendChatAction",
        json={"chat_id": chat_id, "action": "typing"},
    )
    resp.raise_for_status()


async def register_telegram_webhook() -> dict:
    """Register the Telegram webhook via setWebhook API."""
    url = f"{settings.webhook_base_url}/telegram/{settings.telegram_secret}"
    resp = await res.telegram_client.post(
        "setWebhook",
        json={"url": url, "allowed_updates": ["message", "callback_query"]},
    )
    resp.raise_for_status()
    logger.info("Registered Telegram webhook at %s", url)
    return resp.json()


async def answer_callback_query(callback_query_id: str, text: str = "") -> dict:
    """Answer a callback query from an inline keyboard."""
    payload: dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    resp = await res.telegram_client.post("answerCallbackQuery", json=payload)
    resp.raise_for_status()
    return resp.json()
