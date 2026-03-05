"""Application configuration via pydantic-settings. Loads .env for secrets, config.json for topology."""

import json
import logging
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _resolve_prompt(value: str) -> str:
    """Resolve a system prompt value — load from file if prefixed with ``@``."""
    if not value.startswith("@"):
        return value
    path = BASE_DIR / value[1:]
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        raise ValueError(f"System prompt file not found: {path}")


# --- Agent topology models (loaded from config.json) ---


class WorkerListsConfig(BaseModel):
    """Trello list IDs for a worker agent."""

    todo: Annotated[str, Field(min_length=1, description="Trello list ID for todo")]
    doing: Annotated[str, Field(min_length=1, description="Trello list ID for doing")]
    done: Annotated[str, Field(min_length=1, description="Trello list ID for done")]


class WorkerAgentConfig(BaseModel):
    """Configuration for a worker agent."""

    label_id: Annotated[str, Field(min_length=1, description="Trello label ID that routes cards to this worker")]
    repo: Annotated[str, Field(default="", description="Git repo SSH URL (required when repo_access is 'write')")]
    branch_prefix: Annotated[str, Field(default="", description="Branch prefix (required when repo_access is 'write')")]
    base_branch: Annotated[str, Field(default="main", description="Base branch to pull and target PRs against")]
    system_prompt: Annotated[str, Field(default="", description="System prompt for Claude (use @path/to/file.md to load from file)")]
    repo_access: Annotated[
        Literal["write", "read", "none"],
        Field(default="write", description="Repo access level: write (clone+branch+commit), read (clone for context), none (no repo)"),
    ]
    output_mode: Annotated[
        Literal["pr", "comment", "cards", "update"],
        Field(default="pr", description="Output mode: pr (code+PR), comment (analysis as card comment), cards (create sub-cards via MCP), update (rewrite card description)"),
    ]
    allowed_tools: Annotated[
        list[str],
        Field(default_factory=lambda: ["Read", "Write", "Edit", "Bash", "Glob", "Grep"], description="Tools available to the Claude SDK agent"),
    ]
    sdk_timeout: Annotated[
        int,
        Field(default=1800, ge=60, description="Wall-clock timeout in seconds for the SDK query (default: 1800 = 30 min)"),
    ]

    @model_validator(mode="after")
    def _validate_config_axes(self) -> "WorkerAgentConfig":
        """Enforce cross-field constraints and resolve file-based system prompts."""
        if self.repo_access == "write":
            if not self.repo:
                raise ValueError("repo is required when repo_access is 'write'")
            if not self.branch_prefix:
                raise ValueError("branch_prefix is required when repo_access is 'write'")
        if self.output_mode == "pr" and self.repo_access != "write":
            raise ValueError("output_mode 'pr' requires repo_access 'write'")
        self.system_prompt = _resolve_prompt(self.system_prompt)
        return self


class BoardConfig(BaseModel):
    """Configuration for a Trello board containing workers."""

    board_id: Annotated[str, Field(min_length=1, description="Trello board ID")]
    description: Annotated[str, Field(default="", description="Human-readable purpose of this board, shown to orchestrator and agents")]
    failed_list_id: Annotated[str, Field(min_length=1, description="Trello list ID for failed cards")]
    max_bounces: Annotated[int, Field(default=3, ge=1, description="Maximum route_card bounces before a card is killed")]
    lists: Annotated[WorkerListsConfig, Field(description="Shared Trello list IDs (todo/doing/done)")]
    workers: Annotated[dict[str, WorkerAgentConfig], Field(default_factory=dict, description="Worker agents on this board")]



class OrchestratorAgentConfig(BaseModel):
    """Configuration for the orchestrator agent."""

    repos: Annotated[list[str], Field(min_length=1, description="Git repo SSH URLs for read access")]
    base_branch: Annotated[str, Field(default="main", description="Base branch to pull from repos")]
    system_prompt: Annotated[str, Field(default="", description="System prompt for Claude (use @path/to/file.md to load from file)")]
    allowed_tools: Annotated[
        list[str],
        Field(default_factory=lambda: ["Read", "Glob", "Grep", "WebSearch", "WebFetch"], description="SDK tools available to the orchestrator (MCP tools are always added)"),
    ]

    @model_validator(mode="after")
    def _resolve_system_prompt(self) -> "OrchestratorAgentConfig":
        """Resolve file-based system prompt."""
        self.system_prompt = _resolve_prompt(self.system_prompt)
        return self


# --- Main settings ---


class Settings(BaseSettings):
    """Application settings loaded from environment variables and config.json."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Trello
    trello_api_key: Annotated[str, Field(min_length=1, description="Trello API key")]
    trello_api_secret: Annotated[str, Field(min_length=1, description="Trello API secret (OAuth secret) for webhook signature verification")]
    trello_token: Annotated[str, Field(min_length=1, description="Trello API token")]

    # Anthropic
    anthropic_api_key: Annotated[str, Field(min_length=1, description="Anthropic API key")]

    # Telegram
    telegram_bot_token: Annotated[str, Field(min_length=1, description="Telegram bot token")]
    telegram_secret: Annotated[str, Field(min_length=1, description="Webhook URL path suffix")]
    telegram_allowed_user_ids: Annotated[list[int], Field(default_factory=list, description="Allowed Telegram user IDs")]

    # Git / GitHub
    git_ssh_key_path: Annotated[str, Field(default="/root/.ssh/id_ed25519", description="Path to SSH key")]
    webhook_base_url: Annotated[str, Field(min_length=1, description="Public base URL for webhooks")]
    github_token: Annotated[str, Field(min_length=1, description="GitHub personal access token")]

    # Topology — loaded from config.json
    config_json_path: Annotated[str, Field(default="", description="Path to config.json (default: BASE_DIR/config.json)")]
    boards: Annotated[dict[str, BoardConfig], Field(default_factory=dict, description="Board configurations")]
    orchestrator: Annotated[OrchestratorAgentConfig | None, Field(default=None, description="Orchestrator configuration")]

    def model_post_init(self, __context: object) -> None:
        """Load topology from config.json after env is loaded, then validate cross-board constraints."""
        if not self.boards and not self.orchestrator:
            config_path = Path(self.config_json_path) if self.config_json_path else BASE_DIR / "config.json"
            if config_path.exists():
                with open(config_path) as f:
                    data = json.load(f)

                # Parse boards
                boards_raw = data.get("boards", {})
                parsed_boards: dict[str, BoardConfig] = {}
                for board_name, board_cfg in boards_raw.items():
                    parsed_boards[board_name] = BoardConfig.model_validate(board_cfg)
                self.boards = parsed_boards

                # Parse orchestrator
                orch_raw = data.get("orchestrator")
                if orch_raw:
                    self.orchestrator = OrchestratorAgentConfig.model_validate(orch_raw)

                total_workers = sum(len(b.workers) for b in parsed_boards.values())
                logger.info("Loaded %d boards with %d workers from config.json", len(parsed_boards), total_workers)
            else:
                logger.warning("config.json not found at %s", config_path)

        # Validate after boards are loaded (model_validator runs before model_post_init,
        # so cross-board checks must live here)
        self._check_unique_worker_names()
        self._check_unique_label_ids()

    def _check_unique_worker_names(self) -> None:
        """Enforce unique worker names across all boards."""
        seen: dict[str, str] = {}
        for board_name, board in self.boards.items():
            for worker_name in board.workers:
                if worker_name in seen:
                    raise ValueError(
                        f"Duplicate worker name '{worker_name}' found in boards "
                        f"'{seen[worker_name]}' and '{board_name}'"
                    )
                seen[worker_name] = board_name

    def _check_unique_label_ids(self) -> None:
        """Enforce unique label IDs across all workers."""
        seen: dict[str, str] = {}
        for board_name, board in self.boards.items():
            for worker_name, config in board.workers.items():
                if config.label_id in seen:
                    raise ValueError(
                        f"Duplicate label_id '{config.label_id}' on worker '{worker_name}' "
                        f"(board '{board_name}') — already used by worker '{seen[config.label_id]}'"
                    )
                seen[config.label_id] = worker_name

    @property
    def all_workers(self) -> dict[str, WorkerAgentConfig]:
        """Return all worker configs flattened across boards."""
        workers: dict[str, WorkerAgentConfig] = {}
        for board in self.boards.values():
            workers.update(board.workers)
        return workers

    @property
    def done_list_ids(self) -> set[str]:
        """Return all known 'done' list IDs across all boards."""
        return {board.lists.done for board in self.boards.values()}

    @property
    def all_failed_list_ids(self) -> set[str]:
        """Return all failed list IDs across all boards."""
        return {board.failed_list_id for board in self.boards.values()}

    def board_for_worker(self, name: str) -> BoardConfig | None:
        """Look up the board containing the named worker."""
        for board in self.boards.values():
            if name in board.workers:
                return board
        return None

    def failed_list_for_worker(self, name: str) -> str | None:
        """Return the failed list ID for the board containing the named worker."""
        board = self.board_for_worker(name)
        return board.failed_list_id if board else None


settings = Settings()
