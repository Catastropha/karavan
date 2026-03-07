"""Telegram send operations — send messages, typing actions, register webhook."""

import logging
from typing import Any

from app.apps.bot.markdown import strip_markdown_v2
from app.core.config import settings
from app.core.resource import res

logger = logging.getLogger(__name__)


async def send_message(chat_id: int, text: str, parse_mode: str | None = "MarkdownV2") -> dict:
    """Send a message to a Telegram chat.

    Falls back to plain text if Telegram rejects the MarkdownV2 formatting.
    """
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    resp = await res.telegram_client.post("sendMessage", json=payload)
    if resp.status_code == 400 and parse_mode:
        logger.warning("MarkdownV2 send failed for chat %d, retrying as plain text", chat_id)
        payload.pop("parse_mode", None)
        payload["text"] = strip_markdown_v2(text)
        resp = await res.telegram_client.post("sendMessage", json=payload)
    resp.raise_for_status()
    logger.info("Sent message to chat %d", chat_id)
    return resp.json()


async def send_typing_action(chat_id: int) -> None:
    """Send a typing indicator to a Telegram chat. Best-effort — failures are ignored."""
    try:
        await res.telegram_client.post(
            "sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
        )
    except Exception:
        logger.debug("Failed to send typing action to chat %d", chat_id, exc_info=True)


async def register_telegram_webhook() -> dict:
    """Register the Telegram webhook via setWebhook API."""
    url = f"{settings.webhook_base_url}/telegram"
    resp = await res.telegram_client.post(
        "setWebhook",
        json={
            "url": url,
            "allowed_updates": ["message"],
            "secret_token": settings.telegram_secret,
        },
    )
    resp.raise_for_status()
    logger.info("Registered Telegram webhook at %s/telegram", settings.webhook_base_url)
    return resp.json()
