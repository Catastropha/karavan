"""Tests for Trello create operations — create_card and register_webhook."""

from unittest.mock import MagicMock

import httpx
import pytest

from app.apps.trello.crud.create import create_card, register_webhook
from app.apps.trello.model.input import CardCreateIn


class TestCreateCard:
    async def test_creates_card(self, trello_client, make_response):
        card_data = {
            "id": "new_card_id",
            "name": "New Feature",
            "desc": "Build it",
            "url": "https://trello.com/c/xyz",
            "idList": "list1",
        }
        trello_client.post.return_value = make_response(card_data)

        card_in = CardCreateIn.model_validate({
            "name": "New Feature",
            "desc": "Build it",
            "id_list": "list1",
        })
        result = await create_card(card_in)

        assert result.id == "new_card_id"
        assert result.name == "New Feature"
        assert result.desc == "Build it"
        assert result.id_list == "list1"

    async def test_sends_correct_params(self, trello_client, make_response):
        trello_client.post.return_value = make_response({"id": "c1", "name": "Card"})

        card_in = CardCreateIn.model_validate({
            "name": "Card",
            "desc": "Description",
            "id_list": "target_list",
        })
        await create_card(card_in)

        trello_client.post.assert_called_once()
        args, kwargs = trello_client.post.call_args
        assert args == ("cards",)
        params = kwargs["params"]
        assert params["name"] == "Card"
        assert params["desc"] == "Description"
        assert params["idList"] == "target_list"
        assert params["key"] == "test_key"
        assert params["token"] == "test_token"
        assert "idLabels" not in params

    async def test_joins_label_ids(self, trello_client, make_response):
        trello_client.post.return_value = make_response({"id": "c1", "name": "Card"})

        card_in = CardCreateIn.model_validate({
            "name": "Card",
            "id_list": "list1",
            "id_labels": ["label_a", "label_b", "label_c"],
        })
        await create_card(card_in)

        params = trello_client.post.call_args.kwargs["params"]
        assert params["idLabels"] == "label_a,label_b,label_c"

    async def test_empty_labels_omitted(self, trello_client, make_response):
        trello_client.post.return_value = make_response({"id": "c1", "name": "Card"})

        card_in = CardCreateIn.model_validate({"name": "Card", "id_list": "list1"})
        await create_card(card_in)

        params = trello_client.post.call_args.kwargs["params"]
        assert "idLabels" not in params

    async def test_calls_raise_for_status(self, trello_client, make_response):
        resp = make_response({"id": "c1", "name": "Card"})
        trello_client.post.return_value = resp

        card_in = CardCreateIn.model_validate({"name": "Card", "id_list": "list1"})
        await create_card(card_in)

        resp.raise_for_status.assert_called_once()

    async def test_http_error_propagates(self, trello_client):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=resp,
        )
        trello_client.post.return_value = resp

        card_in = CardCreateIn.model_validate({"name": "Card", "id_list": "list1"})
        with pytest.raises(httpx.HTTPStatusError):
            await create_card(card_in)


class TestRegisterWebhook:
    async def test_registers_webhook(self, trello_client, make_response):
        webhook_data = {
            "id": "wh_new",
            "description": "karavan-worker",
            "callbackURL": "https://example.com/webhook/worker",
            "idModel": "list123",
            "active": True,
        }
        trello_client.post.return_value = make_response(webhook_data)

        result = await register_webhook(
            model_id="list123",
            callback_url="https://example.com/webhook/worker",
            description="karavan-worker",
        )

        assert result.id == "wh_new"
        assert result.callback_url == "https://example.com/webhook/worker"
        assert result.id_model == "list123"

    async def test_sends_correct_params(self, trello_client, make_response):
        trello_client.post.return_value = make_response({"id": "wh1"})

        await register_webhook(
            model_id="model_abc",
            callback_url="https://example.com/hook",
            description="test-hook",
        )

        args, kwargs = trello_client.post.call_args
        assert args == ("webhooks",)
        params = kwargs["params"]
        assert params["callbackURL"] == "https://example.com/hook"
        assert params["idModel"] == "model_abc"
        assert params["description"] == "test-hook"
        assert params["key"] == "test_key"
        assert params["token"] == "test_token"

    async def test_description_defaults_empty(self, trello_client, make_response):
        trello_client.post.return_value = make_response({"id": "wh1"})

        await register_webhook(model_id="m1", callback_url="https://example.com/hook")

        params = trello_client.post.call_args.kwargs["params"]
        assert params["description"] == ""

    async def test_http_error_propagates(self, trello_client):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=resp,
        )
        trello_client.post.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            await register_webhook(model_id="m1", callback_url="https://example.com/hook")
