"""Tests for Trello domain models — input (webhook payloads, card creation) and output."""

import pytest
from pydantic import ValidationError

from app.apps.trello.model.input import (
    CardCreateIn,
    TrelloAction,
    TrelloActionData,
    TrelloCardRef,
    TrelloList,
    TrelloWebhookPayload,
)
from app.apps.trello.model.output import CardOut, WebhookOut


# --- TrelloList ---


class TestTrelloList:
    def test_basic(self):
        model = TrelloList.model_validate({"id": "list123", "name": "To Do"})
        assert model.id == "list123"
        assert model.name == "To Do"

    def test_name_defaults_empty(self):
        model = TrelloList.model_validate({"id": "list123"})
        assert model.name == ""

    def test_extra_fields_ignored(self):
        data = {"id": "list123", "name": "To Do", "closed": False, "pos": 1}
        model = TrelloList.model_validate(data)
        assert model.id == "list123"
        assert not hasattr(model, "closed")

    def test_missing_id_raises(self):
        with pytest.raises(ValidationError):
            TrelloList.model_validate({"name": "To Do"})


# --- TrelloCardRef ---


class TestTrelloCardRef:
    def test_basic(self):
        model = TrelloCardRef.model_validate({"id": "card456", "name": "Fix bug"})
        assert model.id == "card456"
        assert model.name == "Fix bug"

    def test_name_defaults_empty(self):
        model = TrelloCardRef.model_validate({"id": "card456"})
        assert model.name == ""

    def test_extra_fields_ignored(self):
        data = {"id": "card456", "name": "Fix bug", "shortLink": "abc"}
        model = TrelloCardRef.model_validate(data)
        assert not hasattr(model, "shortLink")


# --- TrelloActionData ---


class TestTrelloActionData:
    def test_with_camel_case_alias(self):
        data = {
            "card": {"id": "card1", "name": "Task"},
            "listAfter": {"id": "list2", "name": "Doing"},
        }
        model = TrelloActionData.model_validate(data)
        assert model.card.id == "card1"
        assert model.list_after.id == "list2"

    def test_with_snake_case(self):
        data = {"card": {"id": "card1"}, "list_after": {"id": "list2"}}
        model = TrelloActionData.model_validate(data)
        assert model.list_after.id == "list2"

    def test_defaults_none(self):
        model = TrelloActionData.model_validate({})
        assert model.card is None
        assert model.list_after is None

    def test_extra_fields_ignored(self):
        data = {"card": {"id": "c1"}, "board": {"id": "b1"}}
        model = TrelloActionData.model_validate(data)
        assert not hasattr(model, "board")


# --- TrelloAction ---


class TestTrelloAction:
    def test_basic(self):
        data = {
            "type": "updateCard",
            "data": {"card": {"id": "c1"}, "listAfter": {"id": "l1"}},
        }
        model = TrelloAction.model_validate(data)
        assert model.type == "updateCard"
        assert model.data.card.id == "c1"

    def test_missing_type_raises(self):
        with pytest.raises(ValidationError):
            TrelloAction.model_validate({"data": {"card": {"id": "c1"}}})

    def test_missing_data_raises(self):
        with pytest.raises(ValidationError):
            TrelloAction.model_validate({"type": "updateCard"})


# --- TrelloWebhookPayload ---


class TestTrelloWebhookPayload:
    def test_full_payload(self):
        data = {
            "action": {
                "type": "updateCard",
                "data": {
                    "card": {"id": "card789", "name": "Deploy service"},
                    "listAfter": {"id": "done_list", "name": "Done"},
                },
            }
        }
        model = TrelloWebhookPayload.model_validate(data)
        assert model.action.type == "updateCard"
        assert model.action.data.card.name == "Deploy service"
        assert model.action.data.list_after.id == "done_list"

    def test_extra_top_level_ignored(self):
        data = {
            "action": {
                "type": "updateCard",
                "data": {"card": {"id": "c1"}},
            },
            "model": {"id": "board1"},
        }
        model = TrelloWebhookPayload.model_validate(data)
        assert not hasattr(model, "model")

    def test_missing_action_raises(self):
        with pytest.raises(ValidationError):
            TrelloWebhookPayload.model_validate({})

    def test_realistic_trello_payload(self):
        """Parse a payload resembling real Trello webhook data with many extra fields."""
        data = {
            "action": {
                "id": "action123",
                "idMemberCreator": "member1",
                "type": "updateCard",
                "date": "2026-01-15T10:30:00.000Z",
                "data": {
                    "card": {"id": "c1", "name": "Task", "idShort": 42, "shortLink": "abc"},
                    "listAfter": {"id": "done1", "name": "Done"},
                    "listBefore": {"id": "doing1", "name": "Doing"},
                    "board": {"id": "board1", "name": "Project"},
                    "old": {"idList": "doing1"},
                },
            },
            "model": {"id": "board1"},
        }
        model = TrelloWebhookPayload.model_validate(data)
        assert model.action.type == "updateCard"
        assert model.action.data.card.id == "c1"
        assert model.action.data.list_after.id == "done1"


# --- CardCreateIn ---


class TestCardCreateIn:
    def test_basic(self):
        data = {"name": "New card", "id_list": "list1"}
        model = CardCreateIn.model_validate(data)
        assert model.name == "New card"
        assert model.id_list == "list1"
        assert model.desc == ""
        assert model.id_labels == []

    def test_with_camel_case_aliases(self):
        data = {"name": "Card", "idList": "list1", "idLabels": ["l1", "l2"]}
        model = CardCreateIn.model_validate(data)
        assert model.id_list == "list1"
        assert model.id_labels == ["l1", "l2"]

    def test_full_fields(self):
        data = {
            "name": "Full card",
            "desc": "Some description",
            "id_list": "list1",
            "id_labels": ["label1"],
        }
        model = CardCreateIn.model_validate(data)
        assert model.desc == "Some description"
        assert model.id_labels == ["label1"]

    def test_name_too_short_raises(self):
        with pytest.raises(ValidationError):
            CardCreateIn.model_validate({"name": "", "id_list": "list1"})

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            CardCreateIn.model_validate({"name": "x" * 256, "id_list": "list1"})

    def test_desc_too_long_raises(self):
        with pytest.raises(ValidationError):
            CardCreateIn.model_validate({"name": "Card", "id_list": "list1", "desc": "x" * 16385})

    def test_missing_id_list_raises(self):
        with pytest.raises(ValidationError):
            CardCreateIn.model_validate({"name": "Card"})

    def test_empty_id_list_raises(self):
        with pytest.raises(ValidationError):
            CardCreateIn.model_validate({"name": "Card", "id_list": ""})

    def test_desc_at_max_length(self):
        data = {"name": "Card", "id_list": "list1", "desc": "x" * 16384}
        model = CardCreateIn.model_validate(data)
        assert len(model.desc) == 16384

    def test_name_at_max_length(self):
        data = {"name": "x" * 255, "id_list": "list1"}
        model = CardCreateIn.model_validate(data)
        assert len(model.name) == 255


# --- CardOut ---


class TestCardOut:
    def test_from_api_response(self):
        data = {
            "id": "card123",
            "name": "Test Card",
            "desc": "Description",
            "url": "https://trello.com/c/abc",
            "idList": "list456",
        }
        model = CardOut.model_validate(data)
        assert model.id == "card123"
        assert model.name == "Test Card"
        assert model.desc == "Description"
        assert model.url == "https://trello.com/c/abc"
        assert model.id_list == "list456"

    def test_defaults(self):
        model = CardOut.model_validate({"id": "c1", "name": "Card"})
        assert model.desc == ""
        assert model.url == ""
        assert model.id_list == ""

    def test_extra_fields_ignored(self):
        data = {"id": "c1", "name": "Card", "closed": False, "labels": []}
        model = CardOut.model_validate(data)
        assert not hasattr(model, "closed")

    def test_snake_case_field(self):
        data = {"id": "c1", "name": "Card", "id_list": "list1"}
        model = CardOut.model_validate(data)
        assert model.id_list == "list1"


# --- WebhookOut ---


class TestWebhookOut:
    def test_from_api_response(self):
        data = {
            "id": "wh1",
            "description": "karavan-worker",
            "callbackURL": "https://example.com/webhook/worker",
            "idModel": "list123",
            "active": True,
        }
        model = WebhookOut.model_validate(data)
        assert model.id == "wh1"
        assert model.description == "karavan-worker"
        assert model.callback_url == "https://example.com/webhook/worker"
        assert model.id_model == "list123"
        assert model.active is True

    def test_defaults(self):
        model = WebhookOut.model_validate({"id": "wh1"})
        assert model.description == ""
        assert model.callback_url == ""
        assert model.id_model == ""
        assert model.active is True

    def test_snake_case_fields(self):
        data = {"id": "wh1", "callback_url": "https://example.com", "id_model": "m1"}
        model = WebhookOut.model_validate(data)
        assert model.callback_url == "https://example.com"
        assert model.id_model == "m1"

    def test_inactive_webhook(self):
        data = {"id": "wh1", "active": False}
        model = WebhookOut.model_validate(data)
        assert model.active is False
