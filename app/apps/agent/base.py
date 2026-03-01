"""BaseAgent — abstract base class for all agents with async queue and lifecycle."""

import asyncio
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for worker and orchestrator agents.

    Provides an asyncio.Queue, start/stop lifecycle, and a run loop
    that pulls items from the queue and dispatches them to subclass handlers.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def running(self) -> bool:
        """Whether the agent loop is running."""
        return self._running

    async def start(self) -> None:
        """Start the agent's run loop."""
        if self._running:
            logger.warning("Agent %s is already running", self.name)
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"agent-{self.name}")
        logger.info("Agent %s started", self.name)

    async def stop(self) -> None:
        """Stop the agent's run loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Agent %s stopped", self.name)

    async def _run(self) -> None:
        """Main run loop — pull items from queue and process them."""
        logger.info("Agent %s run loop started", self.name)
        while self._running:
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._process(item)
            except Exception:
                logger.exception("Agent %s failed to process item: %s", self.name, item)

        logger.info("Agent %s run loop ended", self.name)

    @abstractmethod
    async def _process(self, item: object) -> None:
        """Process a single item from the queue. Implemented by subclasses."""
        ...

    @abstractmethod
    def should_process_webhook(self, list_id: str) -> bool:
        """Determine if a webhook event for the given list should be processed."""
        ...
