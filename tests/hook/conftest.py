"""Hook test fixtures — mock agent registry and webhook signature helpers."""

import asyncio
import base64
import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.apps.hook import route as hook_route


@pytest.fixture
def agent_registry(monkeypatch):
    """Provide a mock agent registry and inject it into the hook route module.

    Patches settings.boards to include a mock board with a label-to-worker mapping
    so that set_agent_registry() can build the _label_to_worker lookup.
    """
    registry = MagicMock()
    registry.get_agent.return_value = None
    registry.get_all_status.return_value = {}
    registry.orchestrator = None

    # Mock board with one worker label for routing
    mock_worker = MagicMock()
    mock_worker.label_id = "lbl_api"
    mock_board = MagicMock()
    mock_board.board_id = "board_123"
    mock_board.lists.todo = "todo_list_1"
    mock_board.lists.doing = "doing_list_1"
    mock_board.lists.done = "done_list_1"
    mock_board.workers = {"api": mock_worker}

    with patch.object(hook_route, "settings") as mock_settings:
        mock_settings.boards = {"main": mock_board}
        mock_settings.webhook_base_url = "https://test.example.com"
        mock_settings.trello_api_secret = "test_secret"
        mock_settings.done_list_ids = {"done_list_1"}
        mock_settings.all_failed_list_ids = {"failed_list_1"}
        hook_route.set_agent_registry(registry)
        yield registry

    hook_route.set_agent_registry(None)


@pytest.fixture
def mock_agent():
    """Create a mock agent with an async queue."""
    agent = MagicMock()
    agent.queue = asyncio.Queue()
    return agent


@pytest.fixture
def mock_orchestrator():
    """Create a mock orchestrator with an async queue."""
    orch = MagicMock()
    orch.queue = asyncio.Queue()
    return orch


def sign_payload(body: bytes, callback_url: str, api_secret: str = "test_secret") -> str:
    """Compute valid Trello HMAC-SHA1 signature for test payloads."""
    return base64.b64encode(
        hmac.new(
            api_secret.encode("utf-8"),
            body + callback_url.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")
