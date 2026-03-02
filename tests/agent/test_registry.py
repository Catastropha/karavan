"""Tests for AgentRegistry — loading, lookup, lifecycle, and status reporting."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.apps.agent.orchestrator import OrchestratorAgent
from app.apps.agent.registry import AgentRegistry
from app.apps.agent.worker import WorkerAgent


# --- __init__ ---


class TestRegistryInit:
    def test_starts_empty(self):
        """Registry starts with no agents."""
        registry = AgentRegistry()
        assert registry.agents == {}
        assert registry.workers == {}
        assert registry.orchestrator is None


# --- load_from_config ---


class TestLoadFromConfig:
    def test_loads_orchestrator(self):
        """Loads orchestrator agent from settings."""
        registry = AgentRegistry()
        with patch("app.apps.agent.registry.settings") as mock_settings:
            mock_settings.orchestrator = MagicMock()
            mock_settings.orchestrator.repos = ["git@github.com:acme/app.git"]
            mock_settings.orchestrator.base_branch = "main"
            mock_settings.orchestrator.system_prompt = ""
            mock_settings.boards = {}
            registry.load_from_config()

        assert "orchestrator" in registry.agents
        assert isinstance(registry.agents["orchestrator"], OrchestratorAgent)

    def test_loads_workers(self):
        """Loads worker agents from board config."""
        registry = AgentRegistry()

        mock_worker_config = MagicMock()
        mock_worker_config.repo = "git@github.com:acme/app.git"
        mock_worker_config.repo_access = "write"
        mock_worker_config.branch_prefix = "agent/api"
        mock_worker_config.lists.todo = "t1"
        mock_worker_config.lists.doing = "d1"
        mock_worker_config.lists.done = "dn1"

        mock_board = MagicMock()
        mock_board.workers = {"api": mock_worker_config}
        mock_board.board_id = "board_1"
        mock_board.failed_list_id = "f1"

        with patch("app.apps.agent.registry.settings") as mock_settings:
            mock_settings.orchestrator = None
            mock_settings.boards = {"main": mock_board}
            registry.load_from_config()

        assert "api" in registry.agents
        assert isinstance(registry.agents["api"], WorkerAgent)

    def test_no_orchestrator_when_not_configured(self):
        """No orchestrator agent when settings.orchestrator is None."""
        registry = AgentRegistry()
        with patch("app.apps.agent.registry.settings") as mock_settings:
            mock_settings.orchestrator = None
            mock_settings.boards = {}
            registry.load_from_config()
        assert registry.orchestrator is None

    def test_multiple_boards(self):
        """Loads workers from multiple boards."""
        registry = AgentRegistry()

        mock_worker_1 = MagicMock()
        mock_worker_1.repo = "git@github.com:acme/api.git"
        mock_worker_1.repo_access = "write"
        mock_worker_1.branch_prefix = "agent/api"
        mock_board_1 = MagicMock()
        mock_board_1.workers = {"api": mock_worker_1}

        mock_worker_2 = MagicMock()
        mock_worker_2.repo = "git@github.com:acme/web.git"
        mock_worker_2.repo_access = "write"
        mock_worker_2.branch_prefix = "agent/web"
        mock_board_2 = MagicMock()
        mock_board_2.workers = {"web": mock_worker_2}

        with patch("app.apps.agent.registry.settings") as mock_settings:
            mock_settings.orchestrator = None
            mock_settings.boards = {"backend": mock_board_1, "frontend": mock_board_2}
            registry.load_from_config()

        assert "api" in registry.agents
        assert "web" in registry.agents
        assert len(registry.workers) == 2


# --- get_agent ---


class TestGetAgent:
    def test_returns_agent(self):
        """Returns agent by name."""
        registry = AgentRegistry()
        mock_agent = MagicMock()
        registry._agents["test"] = mock_agent
        assert registry.get_agent("test") is mock_agent

    def test_returns_none_for_unknown(self):
        """Returns None for unknown agent name."""
        registry = AgentRegistry()
        assert registry.get_agent("ghost") is None


# --- properties ---


class TestRegistryProperties:
    def test_workers_filters_correctly(self):
        """workers property returns only WorkerAgent instances."""
        registry = AgentRegistry()
        registry._agents["orchestrator"] = MagicMock(spec=OrchestratorAgent)
        registry._agents["api"] = MagicMock(spec=WorkerAgent)
        registry._agents["web"] = MagicMock(spec=WorkerAgent)

        workers = registry.workers
        assert "api" in workers
        assert "web" in workers
        assert "orchestrator" not in workers

    def test_orchestrator_returns_instance(self):
        """orchestrator property returns the OrchestratorAgent."""
        registry = AgentRegistry()
        orch = MagicMock(spec=OrchestratorAgent)
        registry._agents["orchestrator"] = orch
        assert registry.orchestrator is orch

    def test_orchestrator_returns_none_when_wrong_type(self):
        """orchestrator property returns None if 'orchestrator' is not an OrchestratorAgent."""
        registry = AgentRegistry()
        registry._agents["orchestrator"] = MagicMock(spec=WorkerAgent)
        assert registry.orchestrator is None


# --- get_all_status ---


class TestGetAllStatus:
    def test_returns_status_for_all_agents(self):
        """Returns status dict for every registered agent."""
        registry = AgentRegistry()
        agent1 = MagicMock()
        agent1.get_status.return_value = {"running": True, "queue_depth": 0}
        agent2 = MagicMock()
        agent2.get_status.return_value = {"running": False, "queue_depth": 1}
        registry._agents = {"api": agent1, "web": agent2}

        status = registry.get_all_status()
        assert status["api"]["running"] is True
        assert status["web"]["queue_depth"] == 1

    def test_empty_registry(self):
        """Returns empty dict for empty registry."""
        registry = AgentRegistry()
        assert registry.get_all_status() == {}


# --- start_all / stop_all ---


class TestRegistryLifecycle:
    async def test_start_all(self):
        """start_all starts every registered agent."""
        registry = AgentRegistry()
        agent1 = AsyncMock()
        agent2 = AsyncMock()
        registry._agents = {"a": agent1, "b": agent2}

        await registry.start_all()
        agent1.start.assert_awaited_once()
        agent2.start.assert_awaited_once()

    async def test_stop_all(self):
        """stop_all stops every registered agent."""
        registry = AgentRegistry()
        agent1 = AsyncMock()
        agent2 = AsyncMock()
        registry._agents = {"a": agent1, "b": agent2}

        await registry.stop_all()
        agent1.stop.assert_awaited_once()
        agent2.stop.assert_awaited_once()
