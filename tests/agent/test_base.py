"""Tests for BaseAgent — lifecycle, queue processing, and status reporting."""

import asyncio

import pytest

from app.apps.agent.base import BaseAgent


# --- Concrete implementation for testing ---


class StubAgent(BaseAgent):
    """Minimal BaseAgent subclass for testing the abstract base class."""

    def __init__(self, name: str = "stub") -> None:
        super().__init__(name)
        self.processed_items: list[object] = []
        self.process_error: Exception | None = None

    async def _process(self, item: object) -> None:
        if self.process_error:
            raise self.process_error
        self.processed_items.append(item)

    def should_process_webhook(self, list_id: str) -> bool:
        return list_id == "target_list"


# --- __init__ ---


class TestBaseAgentInit:
    def test_initial_state(self):
        """Agent starts with correct defaults."""
        agent = StubAgent("test_agent")
        assert agent.name == "test_agent"
        assert agent.running is False
        assert agent._task is None
        assert agent._last_activity_at == 0.0
        assert agent._cards_processed == 0
        assert agent.queue.empty()


# --- start / stop ---


class TestBaseAgentLifecycle:
    async def test_start_sets_running(self):
        """Starting an agent sets running to True and creates a task."""
        agent = StubAgent()
        await agent.start()
        try:
            assert agent.running is True
            assert agent._task is not None
        finally:
            await agent.stop()

    async def test_stop_clears_state(self):
        """Stopping an agent clears running and task."""
        agent = StubAgent()
        await agent.start()
        await agent.stop()
        assert agent.running is False
        assert agent._task is None

    async def test_double_start_is_idempotent(self):
        """Starting an already running agent is a no-op."""
        agent = StubAgent()
        await agent.start()
        task1 = agent._task
        await agent.start()
        assert agent._task is task1
        await agent.stop()

    async def test_stop_without_start_is_safe(self):
        """Stopping a never-started agent does nothing."""
        agent = StubAgent()
        await agent.stop()
        assert agent.running is False


# --- _run loop ---


class TestBaseAgentRunLoop:
    async def test_processes_queue_item(self):
        """Items placed in the queue are processed."""
        agent = StubAgent()
        await agent.start()
        agent.queue.put_nowait({"card_id": "abc"})
        await asyncio.sleep(0.1)
        await agent.stop()
        assert {"card_id": "abc"} in agent.processed_items

    async def test_increments_cards_processed(self):
        """Each processed item increments cards_processed counter."""
        agent = StubAgent()
        await agent.start()
        agent.queue.put_nowait("item1")
        agent.queue.put_nowait("item2")
        await asyncio.sleep(0.2)
        await agent.stop()
        assert agent._cards_processed == 2

    async def test_updates_last_activity(self):
        """Processing an item updates last_activity_at."""
        agent = StubAgent()
        await agent.start()
        agent.queue.put_nowait("item")
        await asyncio.sleep(0.1)
        await agent.stop()
        assert agent._last_activity_at > 0.0

    async def test_exception_does_not_crash_loop(self):
        """An exception in _process does not stop the run loop."""
        agent = StubAgent()
        agent.process_error = RuntimeError("boom")
        await agent.start()
        agent.queue.put_nowait("bad_item")
        await asyncio.sleep(0.1)
        # The agent should still be running despite the error
        assert agent.running is True
        # After the error, remove it and verify the loop continues
        agent.process_error = None
        agent.queue.put_nowait("good_item")
        await asyncio.sleep(0.1)
        await agent.stop()
        assert "good_item" in agent.processed_items

    async def test_exception_does_not_increment_counter(self):
        """A failed processing does not increment cards_processed."""
        agent = StubAgent()
        agent.process_error = RuntimeError("boom")
        await agent.start()
        agent.queue.put_nowait("bad_item")
        await asyncio.sleep(0.1)
        await agent.stop()
        assert agent._cards_processed == 0


# --- get_status ---


class TestBaseAgentGetStatus:
    def test_status_when_idle(self):
        """Status of a non-running agent with no activity."""
        agent = StubAgent()
        status = agent.get_status()
        assert status == {
            "running": False,
            "queue_depth": 0,
            "last_activity_at": 0.0,
            "cards_processed": 0,
        }

    async def test_status_when_running(self):
        """Status reflects running state and queue depth."""
        agent = StubAgent()
        await agent.start()
        status = agent.get_status()
        assert status["running"] is True
        assert status["queue_depth"] == 0
        await agent.stop()

    async def test_status_reflects_processed_count(self):
        """Status shows the number of processed cards."""
        agent = StubAgent()
        await agent.start()
        agent.queue.put_nowait("item")
        await asyncio.sleep(0.1)
        await agent.stop()
        status = agent.get_status()
        assert status["cards_processed"] == 1
        assert status["last_activity_at"] > 0.0


# --- should_process_webhook ---


class TestShouldProcessWebhook:
    def test_matching_list(self):
        """Returns True for the target list."""
        agent = StubAgent()
        assert agent.should_process_webhook("target_list") is True

    def test_non_matching_list(self):
        """Returns False for a different list."""
        agent = StubAgent()
        assert agent.should_process_webhook("other_list") is False
