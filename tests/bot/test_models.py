"""Tests for bot app models — Telegram payload models and output model."""

import pytest
from pydantic import ValidationError

from app.apps.bot.model.input import TelegramChat, TelegramMessage, TelegramUpdate, TelegramUser
from app.apps.bot.model.output import HookTelegramPostOut


# --- TelegramUser ---


class TestTelegramUser:
    def test_basic(self):
        data = {"id": 123, "is_bot": False, "first_name": "Alice"}
        model = TelegramUser.model_validate(data)
        assert model.id == 123
        assert model.is_bot is False
        assert model.first_name == "Alice"

    def test_defaults(self):
        data = {"id": 456}
        model = TelegramUser.model_validate(data)
        assert model.is_bot is False
        assert model.first_name == ""

    def test_bot_user(self):
        data = {"id": 789, "is_bot": True, "first_name": "BotName"}
        model = TelegramUser.model_validate(data)
        assert model.is_bot is True

    def test_missing_id_raises(self):
        with pytest.raises(ValidationError):
            TelegramUser.model_validate({"first_name": "Alice"})

    def test_extra_fields_ignored(self):
        data = {"id": 1, "last_name": "Smith", "language_code": "en"}
        model = TelegramUser.model_validate(data)
        assert model.id == 1
        assert not hasattr(model, "last_name")


# --- TelegramChat ---


class TestTelegramChat:
    def test_basic(self):
        data = {"id": 100, "type": "group"}
        model = TelegramChat.model_validate(data)
        assert model.id == 100
        assert model.type == "group"

    def test_default_type(self):
        data = {"id": 200}
        model = TelegramChat.model_validate(data)
        assert model.type == "private"

    def test_missing_id_raises(self):
        with pytest.raises(ValidationError):
            TelegramChat.model_validate({"type": "private"})

    def test_extra_fields_ignored(self):
        data = {"id": 300, "title": "My Group", "all_members_are_administrators": True}
        model = TelegramChat.model_validate(data)
        assert model.id == 300
        assert not hasattr(model, "title")


# --- TelegramMessage ---


class TestTelegramMessage:
    def test_basic(self):
        data = {
            "message_id": 1,
            "from": {"id": 10, "first_name": "Bob"},
            "chat": {"id": 20},
            "text": "Hello",
            "date": 1700000000,
        }
        model = TelegramMessage.model_validate(data)
        assert model.message_id == 1
        assert model.from_.id == 10
        assert model.chat.id == 20
        assert model.text == "Hello"
        assert model.date == 1700000000

    def test_from_alias(self):
        """The 'from' field uses alias since 'from' is a Python reserved word."""
        data = {
            "message_id": 2,
            "from": {"id": 99},
            "chat": {"id": 1},
        }
        model = TelegramMessage.model_validate(data)
        assert model.from_.id == 99

    def test_populate_by_name(self):
        """Can also use snake_case 'from_' thanks to populate_by_name."""
        data = {
            "message_id": 3,
            "from_": {"id": 55},
            "chat": {"id": 1},
        }
        model = TelegramMessage.model_validate(data)
        assert model.from_.id == 55

    def test_defaults(self):
        data = {
            "message_id": 4,
            "chat": {"id": 1},
        }
        model = TelegramMessage.model_validate(data)
        assert model.from_ is None
        assert model.text == ""
        assert model.date == 0

    def test_missing_message_id_raises(self):
        with pytest.raises(ValidationError):
            TelegramMessage.model_validate({"chat": {"id": 1}})

    def test_missing_chat_raises(self):
        with pytest.raises(ValidationError):
            TelegramMessage.model_validate({"message_id": 1})

    def test_text_max_length(self):
        data = {
            "message_id": 5,
            "chat": {"id": 1},
            "text": "x" * 4096,
        }
        model = TelegramMessage.model_validate(data)
        assert len(model.text) == 4096

    def test_text_exceeds_max_length_raises(self):
        with pytest.raises(ValidationError):
            TelegramMessage.model_validate({
                "message_id": 6,
                "chat": {"id": 1},
                "text": "x" * 4097,
            })

    def test_extra_fields_ignored(self):
        data = {
            "message_id": 7,
            "chat": {"id": 1},
            "entities": [{"type": "bot_command"}],
            "reply_to_message": {"message_id": 0, "chat": {"id": 1}},
        }
        model = TelegramMessage.model_validate(data)
        assert model.message_id == 7
        assert not hasattr(model, "entities")


# --- TelegramUpdate ---


class TestTelegramUpdate:
    def test_basic(self):
        data = {
            "update_id": 100,
            "message": {
                "message_id": 1,
                "from": {"id": 10, "first_name": "Alice"},
                "chat": {"id": 20},
                "text": "Hi",
            },
        }
        model = TelegramUpdate.model_validate(data)
        assert model.update_id == 100
        assert model.message.text == "Hi"
        assert model.message.from_.first_name == "Alice"

    def test_no_message(self):
        data = {"update_id": 200}
        model = TelegramUpdate.model_validate(data)
        assert model.update_id == 200
        assert model.message is None

    def test_missing_update_id_raises(self):
        with pytest.raises(ValidationError):
            TelegramUpdate.model_validate({"message": {"message_id": 1, "chat": {"id": 1}}})

    def test_extra_fields_ignored(self):
        data = {
            "update_id": 300,
            "edited_message": {"message_id": 1, "chat": {"id": 1}},
            "callback_query": {"id": "q1"},
        }
        model = TelegramUpdate.model_validate(data)
        assert model.update_id == 300
        assert model.message is None

    def test_realistic_payload(self):
        """Full realistic Telegram webhook payload with extra fields."""
        data = {
            "update_id": 123456789,
            "message": {
                "message_id": 42,
                "from": {
                    "id": 987654321,
                    "is_bot": False,
                    "first_name": "John",
                    "last_name": "Doe",
                    "username": "johndoe",
                    "language_code": "en",
                },
                "chat": {
                    "id": 987654321,
                    "first_name": "John",
                    "last_name": "Doe",
                    "username": "johndoe",
                    "type": "private",
                },
                "date": 1700000000,
                "text": "Add appointment reminders",
                "entities": [{"offset": 0, "length": 26, "type": "bot_command"}],
            },
        }
        model = TelegramUpdate.model_validate(data)
        assert model.update_id == 123456789
        assert model.message.message_id == 42
        assert model.message.from_.id == 987654321
        assert model.message.from_.first_name == "John"
        assert model.message.chat.type == "private"
        assert model.message.text == "Add appointment reminders"


# --- HookTelegramPostOut ---


class TestHookTelegramPostOut:
    def test_default_ok(self):
        model = HookTelegramPostOut()
        assert model.ok is True

    def test_explicit_true(self):
        model = HookTelegramPostOut.model_validate({"ok": True})
        assert model.ok is True

    def test_explicit_false(self):
        model = HookTelegramPostOut.model_validate({"ok": False})
        assert model.ok is False
