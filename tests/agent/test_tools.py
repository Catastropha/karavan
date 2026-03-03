"""Tests for agent MCP tools — list_workers, create_trello_card, get_card_status, get_worker_cards."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.apps.agent.tools import (
    MCP_TOOL_NAMES,
    _resolve_list,
    _resolve_worker_from_labels,
    _text_result,
    _worker_not_found,
    build_mcp_server,
    create_trello_card_tool,
    get_card_status_tool,
    get_worker_cards_tool,
    list_workers_tool,
)

# The @tool decorator wraps functions into SdkMcpTool objects.
# Access the original async function via .handler for direct testing.
_list_workers = list_workers_tool.handler
_create_trello_card = create_trello_card_tool.handler
_get_card_status = get_card_status_tool.handler
_get_worker_cards = get_worker_cards_tool.handler


def _mock_board(workers: dict, lists: dict | None = None) -> MagicMock:
    """Build a mock BoardConfig with shared lists and worker configs."""
    board = MagicMock()
    board.lists.todo = (lists or {}).get("todo", "todo_shared")
    board.lists.doing = (lists or {}).get("doing", "doing_shared")
    board.lists.done = (lists or {}).get("done", "done_shared")
    board.description = "Test board"
    board.workers = workers
    return board


def _mock_worker(label_id: str = "lbl_1", next_stage: str | None = None, **kwargs) -> MagicMock:
    """Build a mock WorkerAgentConfig with label_id."""
    worker = MagicMock()
    worker.label_id = label_id
    worker.next_stage = next_stage
    worker.repo = kwargs.get("repo", "git@github.com:acme/app.git")
    worker.repo_access = kwargs.get("repo_access", "write")
    worker.output_mode = kwargs.get("output_mode", "pr")
    worker.system_prompt = kwargs.get("system_prompt", "Test prompt")
    return worker


# --- _text_result ---


class TestTextResult:
    def test_success_result(self):
        result = _text_result("Hello")
        assert result == {"content": [{"type": "text", "text": "Hello"}]}
        assert "is_error" not in result

    def test_error_result(self):
        result = _text_result("Bad input", is_error=True)
        assert result["is_error"] is True
        assert result["content"][0]["text"] == "Bad input"


# --- _worker_not_found ---


class TestWorkerNotFound:
    def test_includes_worker_name(self):
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.all_workers = {"api": MagicMock(), "frontend": MagicMock()}
            result = _worker_not_found("unknown")
        assert result["is_error"] is True
        text = result["content"][0]["text"]
        assert "unknown" in text
        assert "api" in text
        assert "frontend" in text


# --- _resolve_list ---


class TestResolveList:
    def test_resolves_todo_list(self):
        board = _mock_board({}, {"todo": "todo_123", "doing": "doing_123", "done": "done_123"})
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {"main": board}
            result = _resolve_list("todo_123")
        assert result == ("main", "todo")

    def test_resolves_done_list(self):
        board = _mock_board({}, {"todo": "todo_123", "doing": "doing_123", "done": "done_123"})
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {"main": board}
            result = _resolve_list("done_123")
        assert result == ("main", "done")

    def test_returns_none_for_unknown(self):
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {}
            result = _resolve_list("unknown_list")
        assert result is None


# --- _resolve_worker_from_labels ---


class TestResolveWorkerFromLabels:
    def test_resolves_worker_by_label(self):
        worker = _mock_worker(label_id="lbl_api")
        board = _mock_board({"api": worker})
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {"main": board}
            result = _resolve_worker_from_labels(["lbl_api", "lbl_other"])
        assert result == ("api", "main")

    def test_returns_none_for_no_match(self):
        worker = _mock_worker(label_id="lbl_api")
        board = _mock_board({"api": worker})
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {"main": board}
            result = _resolve_worker_from_labels(["lbl_unknown"])
        assert result is None

    def test_returns_none_for_empty_labels(self):
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {}
            result = _resolve_worker_from_labels([])
        assert result is None


# --- list_workers_tool ---


class TestListWorkersTool:
    async def test_returns_all_workers(self):
        """Lists all worker agents with their configs."""
        worker = _mock_worker(label_id="lbl_api", next_stage=None)
        board = _mock_board({"api": worker})

        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {"main": board}
            result = await _list_workers({})

        data = json.loads(result["content"][0]["text"])
        assert len(data) == 1
        assert data[0]["name"] == "api"
        assert data[0]["label_id"] == "lbl_api"
        assert data[0]["next_stage"] is None
        assert data[0]["lists"]["todo"] == "todo_shared"

    async def test_no_workers(self):
        """Returns message when no workers are configured."""
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {}
            result = await _list_workers({})
        assert "No worker agents configured" in result["content"][0]["text"]


# --- create_trello_card_tool ---


class TestCreateTrelloCardTool:
    async def test_creates_card_with_label(self):
        """Creates a card in the board's todo list with worker's label."""
        worker = _mock_worker(label_id="lbl_api")
        board = _mock_board({"api": worker})

        mock_card = MagicMock()
        mock_card.id = "new_card_id"
        mock_card.name = "New task"
        mock_card.url = "https://trello.com/c/new"

        with patch("app.apps.agent.tools.settings") as mock_settings, \
             patch("app.apps.agent.tools.create_card", new_callable=AsyncMock, return_value=mock_card) as mock_create:
            mock_settings.boards = {"main": board}
            mock_settings.all_workers = {"api": worker}
            result = await _create_trello_card({
                "name": "New task",
                "description": "## Task\nDo something",
                "worker_name": "api",
            })

        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "created"
        assert data["card_id"] == "new_card_id"
        assert data["worker"] == "api"

        # Verify create_card was called with board's todo list and worker's label
        call_args = mock_create.call_args[0][0]
        assert call_args.id_list == "todo_shared"
        assert call_args.id_labels == ["lbl_api"]

    async def test_unknown_worker(self):
        """Returns error for unknown worker."""
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {}
            mock_settings.all_workers = {}
            result = await _create_trello_card({
                "name": "Task",
                "description": "Desc",
                "worker_name": "nonexistent",
            })
        assert result["is_error"] is True
        assert "nonexistent" in result["content"][0]["text"]

    async def test_trello_api_error(self):
        """Returns error result on Trello API failure."""
        worker = _mock_worker(label_id="lbl_api")
        board = _mock_board({"api": worker})

        with patch("app.apps.agent.tools.settings") as mock_settings, \
             patch("app.apps.agent.tools.create_card", new_callable=AsyncMock, side_effect=RuntimeError("API error")):
            mock_settings.boards = {"main": board}
            mock_settings.all_workers = {"api": worker}
            result = await _create_trello_card({
                "name": "Task",
                "description": "Desc",
                "worker_name": "api",
            })
        assert result["is_error"] is True
        assert "Failed to create card" in result["content"][0]["text"]


# --- get_card_status_tool ---


class TestGetCardStatusTool:
    async def test_known_list_with_label(self):
        """Returns card with resolved board, status, and worker from label."""
        mock_card = MagicMock()
        mock_card.id = "card_123"
        mock_card.name = "Task"
        mock_card.desc = "Description"
        mock_card.url = "https://trello.com/c/123"
        mock_card.id_list = "doing_list"
        mock_card.id_labels = ["lbl_api"]

        with patch("app.apps.agent.tools.get_card", new_callable=AsyncMock, return_value=mock_card), \
             patch("app.apps.agent.tools._resolve_list", return_value=("main", "doing")), \
             patch("app.apps.agent.tools._resolve_worker_from_labels", return_value=("api", "main")):
            result = await _get_card_status({"card_id": "card_123"})

        data = json.loads(result["content"][0]["text"])
        assert data["id"] == "card_123"
        assert data["board"] == "main"
        assert data["status"] == "doing"
        assert data["worker"] == "api"

    async def test_unknown_list(self):
        """Returns card with 'unknown' status for unrecognized list."""
        mock_card = MagicMock()
        mock_card.id = "card_123"
        mock_card.name = "Task"
        mock_card.desc = ""
        mock_card.url = ""
        mock_card.id_list = "mystery_list"
        mock_card.id_labels = []

        with patch("app.apps.agent.tools.get_card", new_callable=AsyncMock, return_value=mock_card), \
             patch("app.apps.agent.tools._resolve_list", return_value=None), \
             patch("app.apps.agent.tools._resolve_worker_from_labels", return_value=None):
            result = await _get_card_status({"card_id": "card_123"})

        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "unknown"
        assert data["list_id"] == "mystery_list"
        assert "worker" not in data

    async def test_api_error(self):
        """Returns error result on Trello API failure."""
        with patch("app.apps.agent.tools.get_card", new_callable=AsyncMock, side_effect=RuntimeError("Not found")):
            result = await _get_card_status({"card_id": "bad_id"})
        assert result["is_error"] is True


# --- get_worker_cards_tool ---


class TestGetWorkerCardsTool:
    async def test_returns_filtered_cards(self):
        """Returns only cards matching the worker's label from the shared list."""
        worker = _mock_worker(label_id="lbl_api")
        board = _mock_board({"api": worker})

        card1 = MagicMock()
        card1.id = "c1"
        card1.name = "Task 1"
        card1.url = "https://trello.com/c/c1"
        card1.id_labels = ["lbl_api"]

        card2 = MagicMock()
        card2.id = "c2"
        card2.name = "Task 2"
        card2.url = "https://trello.com/c/c2"
        card2.id_labels = ["lbl_other"]  # different worker's label

        card3 = MagicMock()
        card3.id = "c3"
        card3.name = "Task 3"
        card3.url = "https://trello.com/c/c3"
        card3.id_labels = ["lbl_api"]

        with patch("app.apps.agent.tools.settings") as mock_settings, \
             patch("app.apps.agent.tools.get_list_cards", new_callable=AsyncMock, return_value=[card1, card2, card3]):
            mock_settings.boards = {"main": board}
            mock_settings.all_workers = {"api": worker}
            result = await _get_worker_cards({"worker_name": "api", "list_type": "todo"})

        data = json.loads(result["content"][0]["text"])
        assert data["worker"] == "api"
        assert data["count"] == 2
        assert data["cards"][0]["id"] == "c1"
        assert data["cards"][1]["id"] == "c3"

    async def test_unknown_worker(self):
        """Returns error for unknown worker."""
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {}
            mock_settings.all_workers = {}
            result = await _get_worker_cards({"worker_name": "ghost", "list_type": "todo"})
        assert result["is_error"] is True

    async def test_empty_list(self):
        """Returns empty cards list for a list with no cards matching label."""
        worker = _mock_worker(label_id="lbl_api")
        board = _mock_board({"api": worker})

        with patch("app.apps.agent.tools.settings") as mock_settings, \
             patch("app.apps.agent.tools.get_list_cards", new_callable=AsyncMock, return_value=[]):
            mock_settings.boards = {"main": board}
            mock_settings.all_workers = {"api": worker}
            result = await _get_worker_cards({"worker_name": "api", "list_type": "done"})

        data = json.loads(result["content"][0]["text"])
        assert data["count"] == 0
        assert data["cards"] == []


# --- MCP_TOOL_NAMES ---


class TestMcpToolNames:
    def test_contains_all_tools(self):
        assert "list_workers" in MCP_TOOL_NAMES
        assert "create_trello_card" in MCP_TOOL_NAMES
        assert "get_card_status" in MCP_TOOL_NAMES
        assert "get_worker_cards" in MCP_TOOL_NAMES
        assert len(MCP_TOOL_NAMES) == 4


# --- build_mcp_server ---


class TestBuildMcpServer:
    def test_creates_server(self):
        """build_mcp_server returns a server without errors."""
        with patch("app.apps.agent.tools.create_sdk_mcp_server") as mock_create:
            mock_create.return_value = MagicMock()
            server = build_mcp_server("test_server")
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs.get("name") or call_kwargs[1].get("name") == "test_server"

    def test_default_name(self):
        """build_mcp_server uses 'karavan' as default name."""
        with patch("app.apps.agent.tools.create_sdk_mcp_server") as mock_create:
            mock_create.return_value = MagicMock()
            build_mcp_server()
        call_kwargs = mock_create.call_args
        name = call_kwargs.kwargs.get("name", call_kwargs[1].get("name", call_kwargs[0][0] if call_kwargs[0] else None))
        assert name == "karavan"
