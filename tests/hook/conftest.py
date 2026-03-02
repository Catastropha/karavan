"""Hook test fixtures — mock agent registry and webhook signature helpers."""

import asyncio
import base64
import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.apps.hook import route as hook_route


@pytest.fixture
def agent_registry(monkeypatch):
    """Provide a mock agent registry and inject it into the hook route module."""
    registry = MagicMock()
    registry.get_agent.return_value = None
    registry.get_all_status.return_value = {}
    hook_route.set_agent_registry(registry)
    yield registry
    hook_route.set_agent_registry(None)


@pytest.fixture
def mock_agent():
    """Create a mock agent with an async queue and configurable webhook processing."""
    agent = MagicMock()
    agent.queue = asyncio.Queue()
    agent.should_process_webhook.return_value = True
    return agent


def sign_payload(body: bytes, callback_url: str, api_secret: str = "test_secret") -> str:
    """Compute valid Trello HMAC-SHA1 signature for test payloads."""
    return base64.b64encode(
        hmac.new(
            api_secret.encode("utf-8"),
            body + callback_url.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")
