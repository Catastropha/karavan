"""Telegram edit operations — edit existing messages."""

import logging
from typing import Any

from app.apps.bot.markdown import strip_markdown_v2
from app.core.resource import res

logger = logging.getLogger(__name__)


async def edit_message(
    chat_id: int,
    message_id: int,
    text: str,
    parse_mode: str | None = "MarkdownV2",
) -> dict | None:
    """Edit an existing Telegram message.

    Falls back to plain text if Telegram rejects the MarkdownV2 formatting.
    Returns None silently if the message content is identical (not modified).
    """
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    resp = await res.telegram_client.post("editMessageText", json=payload)

    if resp.status_code == 400:
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        description = body.get("description", "")

        if "message is not modified" in description:
            logger.debug("Message %d in chat %d not modified (identical content)", message_id, chat_id)
            return None

        if parse_mode:
            logger.warning("MarkdownV2 edit failed for chat %d msg %d, retrying as plain text", chat_id, message_id)
            payload.pop("parse_mode", None)
            payload["text"] = strip_markdown_v2(text)
            resp = await res.telegram_client.post("editMessageText", json=payload)

    resp.raise_for_status()
    logger.debug("Edited message %d in chat %d", message_id, chat_id)
    return resp.json()
