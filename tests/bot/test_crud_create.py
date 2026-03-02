"""Tests for bot app CRUD create — send_message, send_typing_action, register_telegram_webhook."""

from unittest.mock import MagicMock, patch

import pytest

from app.apps.bot.crud.create import register_telegram_webhook, send_message, send_typing_action


# --- send_message ---


class TestSendMessage:
    async def test_sends_with_markdown(self, telegram_client, make_response):
        """Sends message with MarkdownV2 parse mode by default."""
        telegram_client.post.return_value = make_response({"ok": True, "result": {"message_id": 1}})

        result = await send_message(123, "Hello\\!")

        assert result["ok"] is True
        telegram_client.post.assert_called_once()
        call_args = telegram_client.post.call_args
        assert call_args.args[0] == "sendMessage"
        payload = call_args.kwargs["json"]
        assert payload["chat_id"] == 123
        assert payload["text"] == "Hello\\!"
        assert payload["parse_mode"] == "MarkdownV2"

    async def test_sends_without_parse_mode(self, telegram_client, make_response):
        """Sends message without parse mode when None is passed."""
        telegram_client.post.return_value = make_response({"ok": True, "result": {"message_id": 2}})

        await send_message(123, "Plain text", parse_mode=None)

        payload = telegram_client.post.call_args.kwargs["json"]
        assert "parse_mode" not in payload

    async def test_fallback_on_400(self, telegram_client, make_response):
        """Falls back to plain text when Telegram returns 400 for MarkdownV2."""
        bad_resp = make_response({"ok": False}, status_code=400)
        good_resp = make_response({"ok": True, "result": {"message_id": 3}})
        telegram_client.post.side_effect = [bad_resp, good_resp]

        result = await send_message(123, "Bad\\!markdown")

        assert telegram_client.post.call_count == 2
        # Second call should be plain text without parse_mode
        second_payload = telegram_client.post.call_args_list[1].kwargs["json"]
        assert "parse_mode" not in second_payload
        assert result["ok"] is True

    async def test_no_fallback_on_400_without_parse_mode(self, telegram_client, make_response):
        """No fallback when parse_mode is already None and 400 is returned."""
        bad_resp = make_response({"ok": False}, status_code=400)
        bad_resp.raise_for_status.side_effect = Exception("400 Bad Request")
        telegram_client.post.return_value = bad_resp

        with pytest.raises(Exception, match="400"):
            await send_message(123, "text", parse_mode=None)

        # Only one call — no fallback
        telegram_client.post.assert_called_once()

    async def test_raises_on_non_400_error(self, telegram_client, make_response):
        """Raises on non-400 HTTP errors."""
        error_resp = make_response({"ok": False}, status_code=500)
        error_resp.raise_for_status.side_effect = Exception("500 Internal Server Error")
        telegram_client.post.return_value = error_resp

        with pytest.raises(Exception, match="500"):
            await send_message(123, "text")

    async def test_fallback_strips_markdown(self, telegram_client, make_response):
        """Fallback text has MarkdownV2 escaping stripped."""
        bad_resp = make_response({"ok": False}, status_code=400)
        good_resp = make_response({"ok": True, "result": {"message_id": 4}})
        telegram_client.post.side_effect = [bad_resp, good_resp]

        await send_message(123, "Hello\\! World\\.")

        second_payload = telegram_client.post.call_args_list[1].kwargs["json"]
        assert second_payload["text"] == "Hello! World."


# --- send_typing_action ---


class TestSendTypingAction:
    async def test_sends_typing(self, telegram_client, make_response):
        """Sends typing action to the chat."""
        telegram_client.post.return_value = make_response({"ok": True})

        await send_typing_action(123)

        telegram_client.post.assert_called_once()
        call_args = telegram_client.post.call_args
        assert call_args.args[0] == "sendChatAction"
        payload = call_args.kwargs["json"]
        assert payload["chat_id"] == 123
        assert payload["action"] == "typing"

    async def test_ignores_failure(self, telegram_client):
        """Typing action failures are silently ignored."""
        telegram_client.post.side_effect = Exception("Network error")

        # Should not raise
        await send_typing_action(123)


# --- register_telegram_webhook ---


class TestRegisterTelegramWebhook:
    async def test_registers_webhook(self, telegram_client, make_response):
        """Registers webhook with correct URL and allowed updates."""
        telegram_client.post.return_value = make_response({"ok": True, "result": True})

        with patch("app.apps.bot.crud.create.settings") as mock_settings:
            mock_settings.webhook_base_url = "https://agents.example.com"
            mock_settings.telegram_secret = "my_secret"
            result = await register_telegram_webhook()

        assert result["ok"] is True
        call_args = telegram_client.post.call_args
        assert call_args.args[0] == "setWebhook"
        payload = call_args.kwargs["json"]
        assert payload["url"] == "https://agents.example.com/telegram/my_secret"
        assert payload["allowed_updates"] == ["message"]

    async def test_raises_on_failure(self, telegram_client, make_response):
        """Raises when Telegram API returns an error."""
        error_resp = make_response({"ok": False}, status_code=401)
        error_resp.raise_for_status.side_effect = Exception("401 Unauthorized")
        telegram_client.post.return_value = error_resp

        with patch("app.apps.bot.crud.create.settings") as mock_settings:
            mock_settings.webhook_base_url = "https://agents.example.com"
            mock_settings.telegram_secret = "my_secret"
            with pytest.raises(Exception, match="401"):
                await register_telegram_webhook()
