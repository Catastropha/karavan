"""Tests for Trello update operations — update_card and add_comment."""

from unittest.mock import MagicMock

import httpx
import pytest

from app.apps.trello.crud.update import add_comment, update_card


class TestUpdateCard:
    async def test_update_list(self, trello_client, make_response):
        card_data = {"id": "card1", "name": "Card", "idList": "new_list"}
        trello_client.put.return_value = make_response(card_data)

        result = await update_card("card1", id_list="new_list")

        assert result.id == "card1"
        assert result.id_list == "new_list"

    async def test_update_description(self, trello_client, make_response):
        card_data = {"id": "card1", "name": "Card", "desc": "Updated desc"}
        trello_client.put.return_value = make_response(card_data)

        result = await update_card("card1", desc="Updated desc")

        assert result.desc == "Updated desc"

    async def test_update_both(self, trello_client, make_response):
        card_data = {"id": "card1", "name": "Card", "desc": "New desc", "idList": "new_list"}
        trello_client.put.return_value = make_response(card_data)

        result = await update_card("card1", id_list="new_list", desc="New desc")

        assert result.id_list == "new_list"
        assert result.desc == "New desc"

    async def test_sends_correct_endpoint(self, trello_client, make_response):
        trello_client.put.return_value = make_response({"id": "card_abc", "name": "Card"})

        await update_card("card_abc", id_list="list1")

        args = trello_client.put.call_args.args
        assert args == ("cards/card_abc",)

    async def test_id_list_included_when_set(self, trello_client, make_response):
        trello_client.put.return_value = make_response({"id": "c1", "name": "Card"})

        await update_card("c1", id_list="target_list")

        params = trello_client.put.call_args.kwargs["params"]
        assert params["idList"] == "target_list"

    async def test_id_list_omitted_when_empty(self, trello_client, make_response):
        trello_client.put.return_value = make_response({"id": "c1", "name": "Card"})

        await update_card("c1", desc="Some desc")

        params = trello_client.put.call_args.kwargs["params"]
        assert "idList" not in params

    async def test_desc_included_when_not_none(self, trello_client, make_response):
        trello_client.put.return_value = make_response({"id": "c1", "name": "Card"})

        await update_card("c1", desc="New description")

        data = trello_client.put.call_args.kwargs["data"]
        assert data["desc"] == "New description"

    async def test_desc_included_when_empty_string(self, trello_client, make_response):
        """Empty string desc is intentional (clear description) and should be sent."""
        trello_client.put.return_value = make_response({"id": "c1", "name": "Card"})

        await update_card("c1", desc="")

        data = trello_client.put.call_args.kwargs["data"]
        assert data["desc"] == ""

    async def test_desc_omitted_when_none(self, trello_client, make_response):
        trello_client.put.return_value = make_response({"id": "c1", "name": "Card"})

        await update_card("c1")

        data = trello_client.put.call_args.kwargs["data"]
        assert "desc" not in data

    async def test_auth_params_included(self, trello_client, make_response):
        trello_client.put.return_value = make_response({"id": "c1", "name": "Card"})

        await update_card("c1", id_list="list1")

        params = trello_client.put.call_args.kwargs["params"]
        assert params["key"] == "test_key"
        assert params["token"] == "test_token"

    async def test_http_error_propagates(self, trello_client):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=resp,
        )
        trello_client.put.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            await update_card("nonexistent", id_list="list1")


class TestAddComment:
    async def test_adds_comment(self, trello_client, make_response):
        comment_resp = {"id": "comment1", "data": {"text": "LGTM"}}
        trello_client.post.return_value = make_response(comment_resp)

        result = await add_comment("card1", "LGTM")

        assert result["id"] == "comment1"
        assert result["data"]["text"] == "LGTM"

    async def test_sends_correct_endpoint(self, trello_client, make_response):
        trello_client.post.return_value = make_response({})

        await add_comment("card_abc", "Test comment")

        args = trello_client.post.call_args.args
        assert args == ("cards/card_abc/actions/comments",)

    async def test_sends_text_in_body(self, trello_client, make_response):
        trello_client.post.return_value = make_response({})

        await add_comment("card1", "This is the comment text")

        data = trello_client.post.call_args.kwargs["data"]
        assert data["text"] == "This is the comment text"
        params = trello_client.post.call_args.kwargs["params"]
        assert params["key"] == "test_key"
        assert params["token"] == "test_token"

    async def test_http_error_propagates(self, trello_client):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=resp,
        )
        trello_client.post.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            await add_comment("card1", "text")
