"""AgentRegistry — loads agent configs, instantiates agents, provides lookup."""

import logging
from typing import Any

from app.apps.agent.base import BaseAgent
from app.apps.agent.orchestrator import OrchestratorAgent
from app.apps.agent.worker import WorkerAgent
from app.core.config import settings

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Registry that holds all agent instances and provides name-based lookup."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def load_from_config(self) -> None:
        """Instantiate agents from settings — orchestrator + workers grouped by board."""
        # Orchestrator (always exactly one, hardcoded name)
        if settings.orchestrator:
            self._agents["orchestrator"] = OrchestratorAgent("orchestrator", settings.orchestrator)
            logger.info("Registered orchestrator agent")

        # Workers — iterate boards
        for board_name, board in settings.boards.items():
            for worker_name, worker_config in board.workers.items():
                self._agents[worker_name] = WorkerAgent(worker_name, worker_config, board)
                logger.info("Registered worker agent: %s (board: %s)", worker_name, board_name)

    def get_agent(self, name: str) -> BaseAgent | None:
        """Get an agent by name."""
        return self._agents.get(name)

    @property
    def agents(self) -> dict[str, BaseAgent]:
        """Return all registered agents."""
        return self._agents

    @property
    def workers(self) -> dict[str, WorkerAgent]:
        """Return only worker agents."""
        return {k: v for k, v in self._agents.items() if isinstance(v, WorkerAgent)}

    @property
    def orchestrator(self) -> OrchestratorAgent | None:
        """Return the orchestrator agent, if any."""
        for v in self._agents.values():
            if isinstance(v, OrchestratorAgent):
                return v
        return None

    def get_all_status(self) -> dict[str, dict[str, Any]]:
        """Return status for all registered agents."""
        return {name: agent.get_status() for name, agent in self._agents.items()}

    async def start_all(self) -> None:
        """Start all agents."""
        for name, agent in self._agents.items():
            await agent.start()
            logger.info("Started agent: %s", name)

    async def stop_all(self) -> None:
        """Stop all agents."""
        for name, agent in self._agents.items():
            await agent.stop()
            logger.info("Stopped agent: %s", name)
