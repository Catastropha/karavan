"""Agent test fixtures — mock configs, agents, and helpers."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.apps.agent.base import BaseAgent
from app.apps.agent.worker import WorkerAgent
from app.apps.trello.model.output import CardOut
from app.core.config import BoardConfig, OrchestratorAgentConfig, WorkerAgentConfig, WorkerListsConfig


# --- Config fixtures ---


@pytest.fixture
def worker_lists():
    """Standard board-level list config."""
    return WorkerListsConfig.model_validate({
        "todo": "todo_list_id",
        "doing": "doing_list_id",
        "done": "done_list_id",
    })


@pytest.fixture
def worker_config():
    """Standard write-mode worker config for PR output."""
    return WorkerAgentConfig.model_validate({
        "label_id": "lbl_api",
        "repo": "git@github.com:testowner/testrepo.git",
        "branch_prefix": "agent/api",
        "base_branch": "main",
        "system_prompt": "You are a test agent.",
        "repo_access": "write",
        "output_mode": "pr",
    })


@pytest.fixture
def comment_worker_config():
    """Read-mode worker config for comment output."""
    return WorkerAgentConfig.model_validate({
        "label_id": "lbl_reviewer",
        "repo": "git@github.com:testowner/testrepo.git",
        "repo_access": "read",
        "output_mode": "comment",
        "allowed_tools": ["Read", "Glob", "Grep"],
        "system_prompt": "You are a code reviewer.",
    })


@pytest.fixture
def cards_worker_config():
    """None-mode worker config for cards output."""
    return WorkerAgentConfig.model_validate({
        "label_id": "lbl_planner",
        "repo_access": "none",
        "output_mode": "cards",
        "allowed_tools": ["list_workers", "create_trello_card"],
        "system_prompt": "You are a planner.",
    })


@pytest.fixture
def update_worker_config():
    """Read-mode worker config for update output."""
    return WorkerAgentConfig.model_validate({
        "label_id": "lbl_improver",
        "repo": "git@github.com:testowner/testrepo.git",
        "repo_access": "read",
        "output_mode": "update",
        "allowed_tools": ["Read", "Glob", "Grep"],
        "system_prompt": "You improve card descriptions.",
    })


@pytest.fixture
def pipeline_worker_config():
    """Write-mode worker config that hands off to a next stage."""
    return WorkerAgentConfig.model_validate({
        "label_id": "lbl_api",
        "repo": "git@github.com:testowner/testrepo.git",
        "branch_prefix": "agent/api",
        "base_branch": "main",
        "system_prompt": "You are a test agent.",
        "repo_access": "write",
        "output_mode": "pr",
        "next_stage": "reviewer",
    })


@pytest.fixture
def board_config(worker_config, worker_lists):
    """Board config with shared lists and a single worker."""
    return BoardConfig.model_validate({
        "board_id": "board_123",
        "failed_list_id": "failed_list_id",
        "lists": worker_lists.model_dump(),
        "workers": {"api": worker_config.model_dump()},
    })


@pytest.fixture
def pipeline_board_config(pipeline_worker_config, comment_worker_config, worker_lists):
    """Board config with two workers in a pipeline: api → reviewer."""
    return BoardConfig.model_validate({
        "board_id": "board_123",
        "failed_list_id": "failed_list_id",
        "lists": worker_lists.model_dump(),
        "workers": {
            "api": pipeline_worker_config.model_dump(),
            "reviewer": comment_worker_config.model_dump(),
        },
    })


@pytest.fixture
def orchestrator_config():
    """Orchestrator agent config."""
    return OrchestratorAgentConfig.model_validate({
        "repos": ["git@github.com:testowner/testrepo.git"],
        "base_branch": "main",
        "system_prompt": "You are a test orchestrator.",
    })


# --- Agent fixtures ---


@pytest.fixture
def worker_agent(worker_config, board_config):
    """Create a standard WorkerAgent instance."""
    return WorkerAgent("api", worker_config, board_config)


@pytest.fixture
def comment_worker(comment_worker_config, board_config):
    """Create a comment-mode WorkerAgent."""
    return WorkerAgent("reviewer", comment_worker_config, board_config)


@pytest.fixture
def cards_worker(cards_worker_config, board_config):
    """Create a cards-mode WorkerAgent."""
    return WorkerAgent("planner", cards_worker_config, board_config)


@pytest.fixture
def update_worker(update_worker_config, board_config):
    """Create an update-mode WorkerAgent."""
    return WorkerAgent("improver", update_worker_config, board_config)


@pytest.fixture
def pipeline_worker(pipeline_worker_config, pipeline_board_config):
    """Create a WorkerAgent with next_stage set (api → reviewer)."""
    return WorkerAgent("api", pipeline_worker_config, pipeline_board_config)


# --- Shared helpers ---


def make_card(
    card_id: str = "abc123def456789012345678",
    name: str = "Test task",
    desc: str = "## Task\nDo something",
    url: str = "https://trello.com/c/test",
    id_list: str = "todo_list_id",
    id_labels: list[str] | None = None,
) -> CardOut:
    """Create a CardOut instance with sensible defaults."""
    return CardOut.model_validate({
        "id": card_id,
        "name": name,
        "desc": desc,
        "url": url,
        "idList": id_list,
        "idLabels": id_labels or [],
    })
