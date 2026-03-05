"""Tests for agent MCP tools — list_boards, create_trello_card, get_card_status, get_board_cards."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.apps.agent.tools import (
    MCP_TOOL_NAMES,
    _resolve_list,
    _resolve_worker_from_labels,
    _routing_decisions,
    _text_result,
    _worker_not_found,
    build_mcp_server,
    build_worker_mcp_server,
    create_trello_card_tool,
    get_board_cards_tool,
    get_card_status_tool,
    get_routing_decision,
    list_boards_tool,
)

# The @tool decorator wraps functions into SdkMcpTool objects.
# Access the original async function via .handler for direct testing.
_list_boards = list_boards_tool.handler
_create_trello_card = create_trello_card_tool.handler
_get_card_status = get_card_status_tool.handler
_get_board_cards = get_board_cards_tool.handler


def _mock_board(workers: dict, lists: dict | None = None) -> MagicMock:
    """Build a mock BoardConfig with shared lists and worker configs."""
    board = MagicMock()
    board.lists.todo = (lists or {}).get("todo", "todo_shared")
    board.lists.doing = (lists or {}).get("doing", "doing_shared")
    board.lists.done = (lists or {}).get("done", "done_shared")
    board.description = "Test board"
    board.workers = workers
    return board


def _mock_worker(label_id: str = "lbl_1", **kwargs) -> MagicMock:
    """Build a mock WorkerAgentConfig with label_id."""
    worker = MagicMock()
    worker.label_id = label_id
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


# --- list_boards_tool ---


class TestListBoardsTool:
    async def test_returns_boards_with_workers(self):
        """Lists all boards with their workers nested inside."""
        worker = _mock_worker(label_id="lbl_api")
        board = _mock_board({"api": worker})

        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {"main": board}
            result = await _list_boards({})

        data = json.loads(result["content"][0]["text"])
        assert len(data) == 1
        assert data[0]["name"] == "main"
        assert data[0]["description"] == "Test board"
        assert len(data[0]["workers"]) == 1
        assert data[0]["workers"][0]["name"] == "api"
        assert "label_id" not in data[0]["workers"][0]
        assert "lists" not in data[0]

    async def test_no_boards(self):
        """Returns message when no boards are configured."""
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {}
            result = await _list_boards({})
        assert "No boards configured" in result["content"][0]["text"]


# --- create_trello_card_tool ---


class TestCreateTrelloCardTool:
    async def test_with_worker_name(self):
        """Creates a card with the specified worker's label."""
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

        call_args = mock_create.call_args[0][0]
        assert call_args.id_list == "todo_shared"
        assert call_args.id_labels == ["lbl_api"]

    async def test_with_board_name(self):
        """Creates a card with the first worker's label when using board_name."""
        first_worker = _mock_worker(label_id="lbl_first")
        second_worker = _mock_worker(label_id="lbl_second")
        board = _mock_board({"coder": first_worker, "reviewer": second_worker})

        mock_card = MagicMock()
        mock_card.id = "board_card_id"
        mock_card.name = "Board task"
        mock_card.url = "https://trello.com/c/board"

        with patch("app.apps.agent.tools.settings") as mock_settings, \
             patch("app.apps.agent.tools.create_card", new_callable=AsyncMock, return_value=mock_card) as mock_create:
            mock_settings.boards = {"backend": board}
            result = await _create_trello_card({
                "name": "Board task",
                "description": "## Task\nDo something",
                "board_name": "backend",
            })

        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "created"
        assert data["board"] == "backend"

        call_args = mock_create.call_args[0][0]
        assert call_args.id_list == "todo_shared"
        assert call_args.id_labels == ["lbl_first"]

    async def test_neither_provided(self):
        """Returns error when neither board_name nor worker_name is provided."""
        result = await _create_trello_card({
            "name": "Task",
            "description": "Desc",
        })
        assert result["is_error"] is True
        assert "board_name or worker_name is required" in result["content"][0]["text"]

    async def test_both_provided(self):
        """Returns error when both board_name and worker_name are provided."""
        result = await _create_trello_card({
            "name": "Task",
            "description": "Desc",
            "board_name": "main",
            "worker_name": "api",
        })
        assert result["is_error"] is True
        assert "not both" in result["content"][0]["text"]

    async def test_unknown_board(self):
        """Returns error for unknown board."""
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {}
            result = await _create_trello_card({
                "name": "Task",
                "description": "Desc",
                "board_name": "nonexistent",
            })
        assert result["is_error"] is True
        assert "nonexistent" in result["content"][0]["text"]

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
             patch("app.apps.agent.tools.get_card_actions", new_callable=AsyncMock, return_value=[]), \
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
             patch("app.apps.agent.tools.get_card_actions", new_callable=AsyncMock, return_value=[]), \
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


# --- get_board_cards_tool ---


class TestGetBoardCardsTool:
    async def test_returns_all_cards(self):
        """Returns all cards from the board's list without label filtering."""
        worker = _mock_worker(label_id="lbl_api")
        board = _mock_board({"api": worker})

        card1 = MagicMock()
        card1.id = "c1"
        card1.name = "Task 1"
        card1.url = "https://trello.com/c/c1"

        card2 = MagicMock()
        card2.id = "c2"
        card2.name = "Task 2"
        card2.url = "https://trello.com/c/c2"

        with patch("app.apps.agent.tools.settings") as mock_settings, \
             patch("app.apps.agent.tools.get_list_cards", new_callable=AsyncMock, return_value=[card1, card2]):
            mock_settings.boards = {"main": board}
            result = await _get_board_cards({"board_name": "main", "list_type": "todo"})

        data = json.loads(result["content"][0]["text"])
        assert data["board"] == "main"
        assert data["count"] == 2
        assert data["cards"][0]["id"] == "c1"
        assert data["cards"][1]["id"] == "c2"

    async def test_unknown_board(self):
        """Returns error for unknown board."""
        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {}
            result = await _get_board_cards({"board_name": "ghost", "list_type": "todo"})
        assert result["is_error"] is True
        assert "ghost" in result["content"][0]["text"]

    async def test_empty_list(self):
        """Returns empty cards list for a list with no cards."""
        worker = _mock_worker(label_id="lbl_api")
        board = _mock_board({"api": worker})

        with patch("app.apps.agent.tools.settings") as mock_settings, \
             patch("app.apps.agent.tools.get_list_cards", new_callable=AsyncMock, return_value=[]):
            mock_settings.boards = {"main": board}
            result = await _get_board_cards({"board_name": "main", "list_type": "done"})

        data = json.loads(result["content"][0]["text"])
        assert data["count"] == 0
        assert data["cards"] == []


# --- MCP_TOOL_NAMES ---


class TestMcpToolNames:
    def test_contains_all_tools(self):
        assert "list_boards" in MCP_TOOL_NAMES
        assert "create_trello_card" in MCP_TOOL_NAMES
        assert "get_card_status" in MCP_TOOL_NAMES
        assert "get_board_cards" in MCP_TOOL_NAMES
        assert "route_card" in MCP_TOOL_NAMES
        assert "web_fetch" in MCP_TOOL_NAMES
        assert len(MCP_TOOL_NAMES) == 6


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


# --- get_routing_decision ---


class TestGetRoutingDecision:
    def test_pops_stored_decision(self):
        """get_routing_decision pops and returns the stored target."""
        _routing_decisions["card_abc"] = "reviewer"
        result = get_routing_decision("card_abc")
        assert result == "reviewer"
        assert "card_abc" not in _routing_decisions

    def test_returns_none_for_unknown_card(self):
        """get_routing_decision returns None when no decision exists."""
        result = get_routing_decision("card_unknown")
        assert result is None

    def test_second_call_returns_none(self):
        """get_routing_decision returns None on second call (already popped)."""
        _routing_decisions["card_xyz"] = "api"
        get_routing_decision("card_xyz")
        result = get_routing_decision("card_xyz")
        assert result is None


# --- route_card (via build_worker_mcp_server) ---


class TestRouteCardTool:
    def _get_route_card_handler(self, card_id: str):
        """Build a worker MCP server and extract the route_card handler."""
        with patch("app.apps.agent.tools.create_sdk_mcp_server") as mock_create:
            mock_create.return_value = MagicMock()
            build_worker_mcp_server("test_worker", card_id)

        # Find the route_card tool in the tools passed to create_sdk_mcp_server
        call_kwargs = mock_create.call_args
        tools = call_kwargs.kwargs.get("tools", call_kwargs[1].get("tools", []))
        for t in tools:
            if t.name == "route_card":
                return t.handler
        raise AssertionError("route_card tool not found in build_worker_mcp_server tools")

    async def test_stores_routing_decision(self):
        """route_card stores the target in _routing_decisions."""
        handler = self._get_route_card_handler("card_route_test")

        worker = _mock_worker(label_id="lbl_api")
        board = _mock_board({"api": worker})

        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {"main": board}
            result = await handler({"target": "api", "reason": "needs changes"})

        assert _routing_decisions.pop("card_route_test") == "api"
        assert "is_error" not in result
        assert "routed to 'api'" in result["content"][0]["text"]

    async def test_invalid_target_returns_error(self):
        """route_card with unknown target returns error."""
        handler = self._get_route_card_handler("card_bad_target")

        with patch("app.apps.agent.tools.settings") as mock_settings:
            mock_settings.boards = {}
            mock_settings.all_workers = {}
            result = await handler({"target": "nonexistent", "reason": "test"})

        assert result["is_error"] is True
        assert "nonexistent" in result["content"][0]["text"]
        assert "card_bad_target" not in _routing_decisions


# --- build_worker_mcp_server ---


class TestBuildWorkerMcpServer:
    def test_includes_route_card_tool(self):
        """build_worker_mcp_server includes route_card in the tools list."""
        with patch("app.apps.agent.tools.create_sdk_mcp_server") as mock_create:
            mock_create.return_value = MagicMock()
            build_worker_mcp_server("test", "card_123")

        call_kwargs = mock_create.call_args
        tools = call_kwargs.kwargs.get("tools", call_kwargs[1].get("tools", []))
        tool_names = [t.name for t in tools]
        assert "route_card" in tool_names
        assert "list_boards" in tool_names
        assert "create_trello_card" in tool_names

    def test_includes_all_standard_tools(self):
        """build_worker_mcp_server includes all standard MCP tools."""
        with patch("app.apps.agent.tools.create_sdk_mcp_server") as mock_create:
            mock_create.return_value = MagicMock()
            build_worker_mcp_server("test", "card_123")

        call_kwargs = mock_create.call_args
        tools = call_kwargs.kwargs.get("tools", call_kwargs[1].get("tools", []))
        tool_names = [t.name for t in tools]
        assert len(tool_names) == 6  # 4 standard + route_card + web_fetch
