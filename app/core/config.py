"""Application configuration via pydantic-settings. Loads .env for secrets, config.json for topology."""

import json
import logging
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent


# --- Agent topology models (loaded from config.json) ---


class WorkerListsConfig(BaseModel):
    """Trello list IDs for a worker agent."""

    todo: Annotated[str, Field(min_length=1, description="Trello list ID for todo")]
    doing: Annotated[str, Field(min_length=1, description="Trello list ID for doing")]
    done: Annotated[str, Field(min_length=1, description="Trello list ID for done")]


class WorkerAgentConfig(BaseModel):
    """Configuration for a worker agent."""

    type: Annotated[Literal["worker"], Field(description="Agent type")]
    lists: Annotated[WorkerListsConfig, Field(description="Trello list IDs")]
    repo: Annotated[str, Field(min_length=1, description="Git repo SSH URL")]
    branch_prefix: Annotated[str, Field(min_length=1, description="Branch prefix for this agent")]
    base_branch: Annotated[str, Field(default="main", description="Base branch to pull and target PRs against")]
    system_prompt: Annotated[str, Field(default="", description="System prompt for Claude")]


class OrchestratorAgentConfig(BaseModel):
    """Configuration for the orchestrator agent."""

    type: Annotated[Literal["orchestrator"], Field(description="Agent type")]
    board_id: Annotated[str, Field(min_length=1, description="Trello board ID")]
    repos: Annotated[list[str], Field(min_items=1, description="Git repo SSH URLs for read access")]
    failed_list_id: Annotated[str, Field(min_length=1, description="Shared Trello list ID for failed cards")]
    base_branch: Annotated[str, Field(default="main", description="Base branch to pull from repos")]
    system_prompt: Annotated[str, Field(default="", description="System prompt for Claude")]


AgentConfig = WorkerAgentConfig | OrchestratorAgentConfig


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
    agents: Annotated[dict[str, AgentConfig], Field(default_factory=dict, description="Agent configurations")]

    def model_post_init(self, __context: object) -> None:
        """Load agent topology from config.json after env is loaded."""
        if not self.agents:
            config_path = BASE_DIR / "config.json"
            if config_path.exists():
                with open(config_path) as f:
                    data = json.load(f)
                agents_raw = data.get("agents", {})
                parsed: dict[str, AgentConfig] = {}
                for name, cfg in agents_raw.items():
                    if cfg.get("type") == "worker":
                        parsed[name] = WorkerAgentConfig(**cfg)
                    elif cfg.get("type") == "orchestrator":
                        parsed[name] = OrchestratorAgentConfig(**cfg)
                    else:
                        logger.warning("Unknown agent type for '%s': %s", name, cfg.get("type"))
                self.agents = parsed
                logger.info("Loaded %d agents from config.json", len(parsed))
            else:
                logger.warning("config.json not found at %s", config_path)

    @property
    def worker_agents(self) -> dict[str, WorkerAgentConfig]:
        """Return only worker agent configs."""
        return {k: v for k, v in self.agents.items() if isinstance(v, WorkerAgentConfig)}

    @property
    def orchestrator_agent(self) -> tuple[str, OrchestratorAgentConfig] | None:
        """Return the orchestrator agent config (name, config) or None."""
        for k, v in self.agents.items():
            if isinstance(v, OrchestratorAgentConfig):
                return k, v
        return None

    @property
    def done_list_ids(self) -> set[str]:
        """Return all known 'done' list IDs across workers."""
        return {v.lists.done for v in self.worker_agents.values()}

    @property
    def failed_list_id(self) -> str | None:
        """Return the shared failed list ID from the orchestrator config, or None."""
        orch = self.orchestrator_agent
        if orch:
            return orch[1].failed_list_id
        return None


settings = Settings()
