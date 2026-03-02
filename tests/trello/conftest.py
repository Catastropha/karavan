"""Trello test fixtures — mock httpx client and response helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.resource import res


@pytest.fixture
def make_response():
    """Factory for mock httpx responses."""

    def _make(data, status_code=200):
        resp = MagicMock()
        resp.json.return_value = data
        resp.status_code = status_code
        resp.raise_for_status.return_value = None
        return resp

    return _make


@pytest.fixture
def trello_client(monkeypatch):
    """Replace res.trello_client with an AsyncMock for isolated CRUD testing."""
    client = AsyncMock()
    monkeypatch.setattr(res, "trello_client", client)
    return client
