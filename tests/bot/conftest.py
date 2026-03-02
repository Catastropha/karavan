"""Bot test fixtures — mock Telegram httpx client and response helpers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.apps.bot import route as bot_route
from app.core.resource import res


@pytest.fixture
def make_response():
    """Factory for mock httpx responses."""

    def _make(data, status_code=200):
        resp = MagicMock()
        resp.json.return_value = data
        resp.status_code = status_code
        resp.raise_for_status.return_value = None
        resp.headers = {"content-type": "application/json"}
        return resp

    return _make


@pytest.fixture
def telegram_client(monkeypatch):
    """Replace res.telegram_client with an AsyncMock for isolated CRUD testing."""
    client = AsyncMock()
    monkeypatch.setattr(res, "telegram_client", client)
    return client


@pytest.fixture
def orchestrator_queue():
    """Provide an asyncio.Queue and inject it into the bot route module."""
    queue = asyncio.Queue()
    bot_route.set_orchestrator_queue(queue)
    yield queue
    bot_route.set_orchestrator_queue(None)
