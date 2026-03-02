"""Tests for Trello read operations — get_card, get_list_cards, get_card_actions, get_token_webhooks."""

from unittest.mock import MagicMock

import httpx
import pytest

from app.apps.trello.crud.read import (
    get_card,
    get_card_actions,
    get_list_cards,
    get_token_webhooks,
)


class TestGetCard:
    async def test_fetches_card(self, trello_client, make_response):
        card_data = {
            "id": "card_abc",
            "name": "Fix login bug",
            "desc": "Users can't log in",
            "url": "https://trello.com/c/abc",
            "idList": "doing_list",
        }
        trello_client.get.return_value = make_response(card_data)

        result = await get_card("card_abc")

        assert result.id == "card_abc"
        assert result.name == "Fix login bug"
        assert result.desc == "Users can't log in"
        assert result.id_list == "doing_list"

    async def test_sends_correct_request(self, trello_client, make_response):
        trello_client.get.return_value = make_response({"id": "c1", "name": "Card"})

        await get_card("card_xyz")

        args, kwargs = trello_client.get.call_args
        assert args == ("cards/card_xyz",)
        params = kwargs["params"]
        assert params["key"] == "test_key"
        assert params["token"] == "test_token"

    async def test_http_error_propagates(self, trello_client):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=resp,
        )
        trello_client.get.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            await get_card("nonexistent")


class TestGetListCards:
    async def test_fetches_multiple_cards(self, trello_client, make_response):
        cards_data = [
            {"id": "c1", "name": "Card 1", "idList": "list1"},
            {"id": "c2", "name": "Card 2", "idList": "list1"},
            {"id": "c3", "name": "Card 3", "idList": "list1"},
        ]
        trello_client.get.return_value = make_response(cards_data)

        result = await get_list_cards("list1")

        assert len(result) == 3
        assert result[0].id == "c1"
        assert result[1].name == "Card 2"
        assert result[2].id == "c3"

    async def test_empty_list(self, trello_client, make_response):
        trello_client.get.return_value = make_response([])

        result = await get_list_cards("empty_list")

        assert result == []

    async def test_sends_correct_request(self, trello_client, make_response):
        trello_client.get.return_value = make_response([])

        await get_list_cards("target_list")

        args, kwargs = trello_client.get.call_args
        assert args == ("lists/target_list/cards",)
        assert kwargs["params"]["key"] == "test_key"


class TestGetCardActions:
    async def test_default_filter(self, trello_client, make_response):
        actions = [
            {"id": "a1", "type": "commentCard", "data": {"text": "LGTM"}},
        ]
        trello_client.get.return_value = make_response(actions)

        result = await get_card_actions("card1")

        assert len(result) == 1
        assert result[0]["data"]["text"] == "LGTM"

        params = trello_client.get.call_args.kwargs["params"]
        assert params["filter"] == "commentCard"

    async def test_custom_filter(self, trello_client, make_response):
        trello_client.get.return_value = make_response([])

        await get_card_actions("card1", action_filter="updateCard")

        params = trello_client.get.call_args.kwargs["params"]
        assert params["filter"] == "updateCard"

    async def test_sends_correct_endpoint(self, trello_client, make_response):
        trello_client.get.return_value = make_response([])

        await get_card_actions("card_xyz")

        args = trello_client.get.call_args.args
        assert args == ("cards/card_xyz/actions",)

    async def test_returns_raw_dicts(self, trello_client, make_response):
        actions = [{"id": "a1", "custom_field": "value"}]
        trello_client.get.return_value = make_response(actions)

        result = await get_card_actions("card1")

        assert isinstance(result, list)
        assert isinstance(result[0], dict)
        assert result[0]["custom_field"] == "value"


class TestGetTokenWebhooks:
    async def test_fetches_webhooks(self, trello_client, make_response):
        webhooks_data = [
            {
                "id": "wh1",
                "description": "karavan-api",
                "callbackURL": "https://example.com/webhook/api",
                "idModel": "list1",
                "active": True,
            },
            {
                "id": "wh2",
                "description": "karavan-frontend",
                "callbackURL": "https://example.com/webhook/frontend",
                "idModel": "list2",
                "active": True,
            },
        ]
        trello_client.get.return_value = make_response(webhooks_data)

        result = await get_token_webhooks()

        assert len(result) == 2
        assert result[0].id == "wh1"
        assert result[0].callback_url == "https://example.com/webhook/api"
        assert result[1].id_model == "list2"

    async def test_empty_webhooks(self, trello_client, make_response):
        trello_client.get.return_value = make_response([])

        result = await get_token_webhooks()

        assert result == []

    async def test_sends_correct_endpoint(self, trello_client, make_response):
        trello_client.get.return_value = make_response([])

        await get_token_webhooks()

        args = trello_client.get.call_args.args
        assert args == ("tokens/test_token/webhooks",)
