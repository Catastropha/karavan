"""Telegram bot webhook route."""

import logging

from fastapi import APIRouter, Request, Response

from app.apps.bot.model.input import TelegramUpdate
from app.apps.bot.model.output import HookTelegramPostOut
from app.common.model.input import BotMessage
from app.core.config import settings
from app.core.security import verify_secret

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bot"])

# Reference to orchestrator agent's queue — set during app startup
_orchestrator_queue = None


def set_orchestrator_queue(queue: object) -> None:
    """Set the orchestrator agent's asyncio.Queue for message routing."""
    global _orchestrator_queue
    _orchestrator_queue = queue


@router.post(
    "/telegram/{secret}",
    response_model=HookTelegramPostOut,
    include_in_schema=False,
)
async def telegram_webhook(secret: str, request: Request) -> HookTelegramPostOut:
    """Receive Telegram webhook updates. Always returns 200 to prevent retries."""
    if not verify_secret(secret, settings.telegram_secret):
        logger.warning("Invalid Telegram webhook secret")
        return HookTelegramPostOut()

    body = await request.json()
    update = TelegramUpdate(**body)

    if update.message and update.message.text and update.message.from_:
        user_id = update.message.from_.id
        if user_id not in settings.telegram_allowed_user_ids:
            logger.warning("Ignoring message from unauthorized user %d", user_id)
            return HookTelegramPostOut()

        bot_msg = BotMessage(
            chat_id=update.message.chat.id,
            user_id=user_id,
            username=update.message.from_.first_name,
            text=update.message.text,
            message_id=update.message.message_id,
        )

        if _orchestrator_queue is not None:
            await _orchestrator_queue.put(bot_msg)
            logger.info("Queued message from user %d: %s", user_id, bot_msg.text[:50])
        else:
            logger.error("Orchestrator queue not set — dropping message")

    elif update.callback_query:
        user_id = update.callback_query.from_.id
        if user_id not in settings.telegram_allowed_user_ids:
            return HookTelegramPostOut()

        msg = update.callback_query.message
        bot_msg = BotMessage(
            chat_id=msg.chat.id if msg else 0,
            user_id=user_id,
            username=update.callback_query.from_.first_name,
            text=update.callback_query.data,
            message_id=msg.message_id if msg else 0,
        )

        if _orchestrator_queue is not None:
            await _orchestrator_queue.put(bot_msg)
            logger.info("Queued callback from user %d: %s", user_id, bot_msg.text[:50])

    return HookTelegramPostOut()
