"""Tests for bot app CRUD update — edit_message."""

from unittest.mock import MagicMock

import pytest

from app.apps.bot.crud.update import edit_message


# --- edit_message ---


class TestEditMessage:
    async def test_edits_with_markdown(self, telegram_client, make_response):
        """Edits message with MarkdownV2 parse mode by default."""
        telegram_client.post.return_value = make_response({"ok": True, "result": {"message_id": 1}})

        result = await edit_message(123, 1, "Updated\\!")

        assert result["ok"] is True
        call_args = telegram_client.post.call_args
        assert call_args.args[0] == "editMessageText"
        payload = call_args.kwargs["json"]
        assert payload["chat_id"] == 123
        assert payload["message_id"] == 1
        assert payload["text"] == "Updated\\!"
        assert payload["parse_mode"] == "MarkdownV2"

    async def test_edits_without_parse_mode(self, telegram_client, make_response):
        """Edits message without parse mode when None is passed."""
        telegram_client.post.return_value = make_response({"ok": True, "result": {"message_id": 2}})

        await edit_message(123, 2, "Plain text", parse_mode=None)

        payload = telegram_client.post.call_args.kwargs["json"]
        assert "parse_mode" not in payload

    async def test_returns_none_on_not_modified(self, telegram_client):
        """Returns None when message content is identical (not modified)."""
        resp = MagicMock()
        resp.status_code = 400
        resp.headers = {"content-type": "application/json"}
        resp.json.return_value = {
            "ok": False,
            "description": "Bad Request: message is not modified",
        }
        telegram_client.post.return_value = resp

        result = await edit_message(123, 1, "Same text")

        assert result is None
        telegram_client.post.assert_called_once()

    async def test_fallback_on_400_markdown_error(self, telegram_client, make_response):
        """Falls back to plain text when Telegram rejects MarkdownV2."""
        bad_resp = MagicMock()
        bad_resp.status_code = 400
        bad_resp.headers = {"content-type": "application/json"}
        bad_resp.json.return_value = {
            "ok": False,
            "description": "Bad Request: can't parse entities",
        }
        good_resp = make_response({"ok": True, "result": {"message_id": 1}})
        telegram_client.post.side_effect = [bad_resp, good_resp]

        result = await edit_message(123, 1, "Bad\\!markdown")

        assert telegram_client.post.call_count == 2
        second_payload = telegram_client.post.call_args_list[1].kwargs["json"]
        assert "parse_mode" not in second_payload

    async def test_no_fallback_on_400_without_parse_mode(self, telegram_client):
        """No fallback when parse_mode is already None and 400 is returned."""
        resp = MagicMock()
        resp.status_code = 400
        resp.headers = {"content-type": "application/json"}
        resp.json.return_value = {
            "ok": False,
            "description": "Bad Request: some other error",
        }
        resp.raise_for_status.side_effect = Exception("400 Bad Request")
        telegram_client.post.return_value = resp

        with pytest.raises(Exception, match="400"):
            await edit_message(123, 1, "text", parse_mode=None)

        telegram_client.post.assert_called_once()

    async def test_raises_on_non_400_error(self, telegram_client, make_response):
        """Raises on non-400 HTTP errors."""
        error_resp = make_response({"ok": False}, status_code=500)
        error_resp.raise_for_status.side_effect = Exception("500 Internal Server Error")
        telegram_client.post.return_value = error_resp

        with pytest.raises(Exception, match="500"):
            await edit_message(123, 1, "text")

    async def test_not_modified_with_non_json_content_type(self, telegram_client):
        """Handles 400 with non-JSON content type gracefully."""
        resp = MagicMock()
        resp.status_code = 400
        resp.headers = {"content-type": "text/plain"}
        resp.raise_for_status.side_effect = Exception("400 Bad Request")
        telegram_client.post.return_value = resp

        # parse_mode is set, but response is not JSON, and description won't match
        # "not modified" — so it should attempt fallback, then raise on the second call
        good_resp = MagicMock()
        good_resp.status_code = 200
        good_resp.json.return_value = {"ok": True}
        good_resp.raise_for_status.return_value = None
        telegram_client.post.side_effect = [resp, good_resp]

        result = await edit_message(123, 1, "text")

        assert telegram_client.post.call_count == 2

    async def test_fallback_strips_markdown(self, telegram_client, make_response):
        """Fallback text has MarkdownV2 escaping stripped."""
        bad_resp = MagicMock()
        bad_resp.status_code = 400
        bad_resp.headers = {"content-type": "application/json"}
        bad_resp.json.return_value = {
            "ok": False,
            "description": "Bad Request: can't parse entities",
        }
        good_resp = make_response({"ok": True, "result": {"message_id": 1}})
        telegram_client.post.side_effect = [bad_resp, good_resp]

        await edit_message(123, 1, "Hello\\! World\\.")

        second_payload = telegram_client.post.call_args_list[1].kwargs["json"]
        assert second_payload["text"] == "Hello! World."
