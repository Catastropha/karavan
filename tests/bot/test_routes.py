"""Tests for bot app routes — Telegram webhook handler."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.apps.bot.model.output import HookTelegramPostOut
from app.apps.bot.route import set_orchestrator_queue, telegram_webhook


# --- Helpers ---


VALID_UPDATE = {
    "update_id": 100,
    "message": {
        "message_id": 1,
        "from": {"id": 123456789, "first_name": "Alice"},
        "chat": {"id": 999},
        "text": "Add appointment reminders",
        "date": 1700000000,
    },
}


def _make_request(body: dict | bytes) -> MagicMock:
    """Build a mock FastAPI Request with JSON body."""
    request = MagicMock()
    if isinstance(body, dict):
        data = body
    else:
        data = json.loads(body)

    async def async_json():
        return data

    request.json = async_json
    return request


# --- telegram_webhook ---


class TestTelegramWebhook:
    async def test_queues_valid_message(self, orchestrator_queue):
        """Valid update from allowed user queues a BotMessage."""
        request = _make_request(VALID_UPDATE)

        with patch("app.apps.bot.route.settings") as mock_settings:
            mock_settings.telegram_secret = "test_secret"
            mock_settings.telegram_allowed_user_ids = [123456789]
            result = await telegram_webhook("test_secret", request)

        assert isinstance(result, HookTelegramPostOut)
        assert result.ok is True
        assert not orchestrator_queue.empty()
        msg = orchestrator_queue.get_nowait()
        assert msg.chat_id == 999
        assert msg.user_id == 123456789
        assert msg.username == "Alice"
        assert msg.text == "Add appointment reminders"
        assert msg.message_id == 1

    async def test_invalid_secret_returns_ok(self, orchestrator_queue):
        """Invalid secret returns ok without processing."""
        request = _make_request(VALID_UPDATE)

        with patch("app.apps.bot.route.settings") as mock_settings:
            mock_settings.telegram_secret = "real_secret"
            result = await telegram_webhook("wrong_secret", request)

        assert result.ok is True
        assert orchestrator_queue.empty()

    async def test_malformed_payload_returns_ok(self, orchestrator_queue):
        """Malformed payload returns ok without crashing."""
        request = MagicMock()

        async def async_json():
            raise ValueError("bad json")

        request.json = async_json

        with patch("app.apps.bot.route.settings") as mock_settings:
            mock_settings.telegram_secret = "test_secret"
            result = await telegram_webhook("test_secret", request)

        assert result.ok is True
        assert orchestrator_queue.empty()

    async def test_missing_message_returns_ok(self, orchestrator_queue):
        """Update without message returns ok without queuing."""
        update = {"update_id": 200}
        request = _make_request(update)

        with patch("app.apps.bot.route.settings") as mock_settings:
            mock_settings.telegram_secret = "test_secret"
            result = await telegram_webhook("test_secret", request)

        assert result.ok is True
        assert orchestrator_queue.empty()

    async def test_empty_text_returns_ok(self, orchestrator_queue):
        """Message with empty text returns ok without queuing."""
        update = {
            "update_id": 300,
            "message": {
                "message_id": 1,
                "from": {"id": 123456789},
                "chat": {"id": 999},
                "text": "",
            },
        }
        request = _make_request(update)

        with patch("app.apps.bot.route.settings") as mock_settings:
            mock_settings.telegram_secret = "test_secret"
            mock_settings.telegram_allowed_user_ids = [123456789]
            result = await telegram_webhook("test_secret", request)

        assert result.ok is True
        assert orchestrator_queue.empty()

    async def test_missing_from_returns_ok(self, orchestrator_queue):
        """Message without 'from' field returns ok without queuing."""
        update = {
            "update_id": 400,
            "message": {
                "message_id": 1,
                "chat": {"id": 999},
                "text": "Hello",
            },
        }
        request = _make_request(update)

        with patch("app.apps.bot.route.settings") as mock_settings:
            mock_settings.telegram_secret = "test_secret"
            result = await telegram_webhook("test_secret", request)

        assert result.ok is True
        assert orchestrator_queue.empty()

    async def test_unauthorized_user_returns_ok(self, orchestrator_queue):
        """Message from unauthorized user returns ok without queuing."""
        update = {
            "update_id": 500,
            "message": {
                "message_id": 1,
                "from": {"id": 999999999, "first_name": "Stranger"},
                "chat": {"id": 100},
                "text": "Hello",
            },
        }
        request = _make_request(update)

        with patch("app.apps.bot.route.settings") as mock_settings:
            mock_settings.telegram_secret = "test_secret"
            mock_settings.telegram_allowed_user_ids = [123456789]
            result = await telegram_webhook("test_secret", request)

        assert result.ok is True
        assert orchestrator_queue.empty()

    async def test_no_orchestrator_queue_returns_ok(self):
        """No orchestrator queue set — message is dropped but returns ok."""
        set_orchestrator_queue(None)
        request = _make_request(VALID_UPDATE)

        with patch("app.apps.bot.route.settings") as mock_settings:
            mock_settings.telegram_secret = "test_secret"
            mock_settings.telegram_allowed_user_ids = [123456789]
            result = await telegram_webhook("test_secret", request)

        assert result.ok is True

    async def test_always_returns_hook_telegram_post_out(self, orchestrator_queue):
        """Every code path returns HookTelegramPostOut."""
        request = _make_request(VALID_UPDATE)

        with patch("app.apps.bot.route.settings") as mock_settings:
            mock_settings.telegram_secret = "test_secret"
            mock_settings.telegram_allowed_user_ids = [123456789]
            result = await telegram_webhook("test_secret", request)

        assert isinstance(result, HookTelegramPostOut)

    async def test_group_chat_message(self, orchestrator_queue):
        """Message from a group chat uses the chat ID, not user ID."""
        update = {
            "update_id": 600,
            "message": {
                "message_id": 10,
                "from": {"id": 123456789, "first_name": "Alice"},
                "chat": {"id": -1001234567890, "type": "supergroup"},
                "text": "Deploy the app",
            },
        }
        request = _make_request(update)

        with patch("app.apps.bot.route.settings") as mock_settings:
            mock_settings.telegram_secret = "test_secret"
            mock_settings.telegram_allowed_user_ids = [123456789]
            result = await telegram_webhook("test_secret", request)

        assert result.ok is True
        msg = orchestrator_queue.get_nowait()
        assert msg.chat_id == -1001234567890
        assert msg.user_id == 123456789

    async def test_bot_message_tp_field(self, orchestrator_queue):
        """Queued BotMessage has tp='telegram'."""
        request = _make_request(VALID_UPDATE)

        with patch("app.apps.bot.route.settings") as mock_settings:
            mock_settings.telegram_secret = "test_secret"
            mock_settings.telegram_allowed_user_ids = [123456789]
            await telegram_webhook("test_secret", request)

        msg = orchestrator_queue.get_nowait()
        assert msg.tp == "telegram"


# --- set_orchestrator_queue ---


class TestSetOrchestratorQueue:
    def test_set_and_clear(self):
        """Can set and clear the orchestrator queue."""
        import asyncio

        queue = asyncio.Queue()
        set_orchestrator_queue(queue)
        # Verify it was set by checking the module-level variable
        from app.apps.bot import route

        assert route._orchestrator_queue is queue
        set_orchestrator_queue(None)
        assert route._orchestrator_queue is None
