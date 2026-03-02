"""Tests for Trello delete operations — delete_webhook."""

from unittest.mock import MagicMock

import httpx
import pytest

from app.apps.trello.crud.delete import delete_webhook


class TestDeleteWebhook:
    async def test_deletes_webhook(self, trello_client, make_response):
        trello_client.delete.return_value = make_response(None)

        result = await delete_webhook("wh_abc")

        assert result is None

    async def test_sends_correct_endpoint(self, trello_client, make_response):
        trello_client.delete.return_value = make_response(None)

        await delete_webhook("wh_xyz")

        args = trello_client.delete.call_args.args
        assert args == ("webhooks/wh_xyz",)

    async def test_sends_auth_params(self, trello_client, make_response):
        trello_client.delete.return_value = make_response(None)

        await delete_webhook("wh1")

        params = trello_client.delete.call_args.kwargs["params"]
        assert params["key"] == "test_key"
        assert params["token"] == "test_token"

    async def test_calls_raise_for_status(self, trello_client, make_response):
        resp = make_response(None)
        trello_client.delete.return_value = resp

        await delete_webhook("wh1")

        resp.raise_for_status.assert_called_once()

    async def test_http_error_propagates(self, trello_client):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=resp,
        )
        trello_client.delete.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            await delete_webhook("nonexistent")
