"""Tests for OrchestratorAgent — message handling, done/failed events, and dependency tracking."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.apps.agent.orchestrator import OrchestratorAgent
from app.apps.trello.model.output import CardOut
from app.common.model.input import BotMessage

from .conftest import make_card


# --- Helpers ---


def _make_bot_message(text: str = "Hello", chat_id: int = 999, user_id: int = 123456789) -> BotMessage:
    """Create a BotMessage with sensible defaults."""
    return BotMessage.model_validate({
        "chat_id": chat_id,
        "user_id": user_id,
        "username": "alice",
        "text": text,
        "message_id": 1,
    })


# --- __init__ ---


class TestOrchestratorInit:
    def test_initial_state(self, orchestrator_config):
        """Orchestrator starts with correct defaults."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        assert orch.name == "orchestrator"
        assert orch._client is None
        assert orch._repo_dirs == []
        assert orch._known_chat_ids == set()
        assert orch._session_id == "default"


# --- should_process_webhook ---


class TestOrchestratorShouldProcessWebhook:
    def test_matches_done_list(self, orchestrator_config):
        """Returns True for done list IDs."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        with patch("app.apps.agent.orchestrator.settings") as mock_settings:
            mock_settings.done_list_ids = {"done_list_1", "done_list_2"}
            mock_settings.all_failed_list_ids = {"failed_list_1"}
            assert orch.should_process_webhook("done_list_1") is True

    def test_matches_failed_list(self, orchestrator_config):
        """Returns True for failed list IDs."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        with patch("app.apps.agent.orchestrator.settings") as mock_settings:
            mock_settings.done_list_ids = {"done_list_1"}
            mock_settings.all_failed_list_ids = {"failed_list_1"}
            assert orch.should_process_webhook("failed_list_1") is True

    def test_rejects_unknown_list(self, orchestrator_config):
        """Returns False for unknown list IDs."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        with patch("app.apps.agent.orchestrator.settings") as mock_settings:
            mock_settings.done_list_ids = {"done_list_1"}
            mock_settings.all_failed_list_ids = {"failed_list_1"}
            assert orch.should_process_webhook("random_list") is False


# --- reset_session ---


class TestResetSession:
    def test_changes_session_id(self, orchestrator_config):
        """reset_session generates a new UUID session ID."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        old_id = orch._session_id
        orch.reset_session()
        assert orch._session_id != old_id
        assert orch._session_id != "default"

    def test_session_ids_are_unique(self, orchestrator_config):
        """Each reset produces a different session ID."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        orch.reset_session()
        id1 = orch._session_id
        orch.reset_session()
        id2 = orch._session_id
        assert id1 != id2


# --- _process ---


class TestOrchestratorProcess:
    async def test_clear_command_resets_session(self, orchestrator_config):
        """The /clear command resets session and sends confirmation."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        msg = _make_bot_message(text="/clear")

        with patch("app.apps.agent.orchestrator.send_message", new_callable=AsyncMock) as mock_send, \
             patch("app.apps.agent.orchestrator.escape_markdown_v2", side_effect=lambda x: x):
            await orch._process(msg)

        assert orch._session_id != "default"
        assert 999 in orch._known_chat_ids
        mock_send.assert_awaited_once()
        assert "Context cleared" in mock_send.call_args[0][1]

    async def test_bot_message_dispatches_to_handler(self, orchestrator_config):
        """Regular BotMessage dispatches to _handle_user_message."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        msg = _make_bot_message(text="Hello")

        with patch.object(orch, "_handle_user_message", new_callable=AsyncMock) as mock_handler:
            await orch._process(msg)
            mock_handler.assert_awaited_once_with(msg)

    async def test_done_event_dispatches(self, orchestrator_config):
        """Dict event with action_type dispatches to _handle_done_event."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        event = {"action_type": "updateCard", "card_id": "c1", "card_name": "Task", "list_after_id": "done_list_1"}

        with patch.object(orch, "_handle_done_event", new_callable=AsyncMock) as mock_handler, \
             patch("app.apps.agent.orchestrator.settings") as mock_settings:
            mock_settings.all_failed_list_ids = set()
            await orch._process(event)
            mock_handler.assert_awaited_once_with(event)

    async def test_failed_event_dispatches(self, orchestrator_config):
        """Dict event with failed list_after_id dispatches to _handle_failed_event."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        event = {"action_type": "updateCard", "card_id": "c1", "card_name": "Task", "list_after_id": "failed_list_id"}

        with patch.object(orch, "_handle_failed_event", new_callable=AsyncMock) as mock_handler, \
             patch("app.apps.agent.orchestrator.settings") as mock_settings:
            mock_settings.all_failed_list_ids = {"failed_list_id"}
            await orch._process(event)
            mock_handler.assert_awaited_once_with(event)

    async def test_unknown_item_logged(self, orchestrator_config):
        """Unknown item types are logged as warnings."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        await orch._process(42)  # Should not raise


# --- _handle_user_message ---


class TestHandleUserMessage:
    async def test_no_client_returns_early(self, orchestrator_config):
        """Returns immediately if _client is None."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        msg = _make_bot_message()
        # Should not raise — just logs error and returns
        await orch._handle_user_message(msg)

    async def test_tracks_chat_id(self, orchestrator_config):
        """Chat ID is added to _known_chat_ids."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        orch._client = MagicMock()
        orch._client.query = AsyncMock()

        result_msg = MagicMock()
        result_msg.total_cost_usd = 0.01
        result_msg.usage = {}
        result_msg.result = "Response"

        async def mock_receive():
            yield result_msg

        orch._client.receive_response = mock_receive
        msg = _make_bot_message(chat_id=42)

        with patch("app.apps.agent.orchestrator.send_typing_action", new_callable=AsyncMock), \
             patch("app.apps.agent.orchestrator.pull_base", new_callable=AsyncMock), \
             patch("app.apps.agent.orchestrator.send_message", new_callable=AsyncMock), \
             patch("app.apps.agent.orchestrator.escape_markdown_v2", side_effect=lambda x: x), \
             patch("app.apps.agent.orchestrator.cost_tracker"):
            await orch._handle_user_message(msg)

        assert 42 in orch._known_chat_ids

    async def test_sends_response_via_telegram(self, orchestrator_config):
        """Response text is sent back via Telegram."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        orch._client = MagicMock()
        orch._client.query = AsyncMock()

        result_msg = MagicMock()
        result_msg.total_cost_usd = 0.01
        result_msg.usage = {}
        result_msg.result = "Here is my response."

        async def mock_receive():
            yield result_msg

        orch._client.receive_response = mock_receive

        msg = _make_bot_message()

        with patch("app.apps.agent.orchestrator.send_typing_action", new_callable=AsyncMock), \
             patch("app.apps.agent.orchestrator.pull_base", new_callable=AsyncMock), \
             patch("app.apps.agent.orchestrator.send_message", new_callable=AsyncMock) as mock_send, \
             patch("app.apps.agent.orchestrator.escape_markdown_v2", side_effect=lambda x: x), \
             patch("app.apps.agent.orchestrator.cost_tracker"):
            await orch._handle_user_message(msg)

        mock_send.assert_awaited()
        # The actual text should contain the response
        sent_text = mock_send.call_args[0][1]
        assert "Here is my response" in sent_text

    async def test_empty_response_sends_fallback(self, orchestrator_config):
        """Empty response sends a fallback message."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        orch._client = MagicMock()
        orch._client.query = AsyncMock()

        result_msg = MagicMock()
        result_msg.total_cost_usd = 0.01
        result_msg.usage = {}
        result_msg.result = ""

        async def mock_receive():
            yield result_msg

        orch._client.receive_response = mock_receive

        msg = _make_bot_message()

        with patch("app.apps.agent.orchestrator.send_typing_action", new_callable=AsyncMock), \
             patch("app.apps.agent.orchestrator.pull_base", new_callable=AsyncMock), \
             patch("app.apps.agent.orchestrator.send_message", new_callable=AsyncMock) as mock_send, \
             patch("app.apps.agent.orchestrator.escape_markdown_v2", side_effect=lambda x: x), \
             patch("app.apps.agent.orchestrator.cost_tracker"):
            await orch._handle_user_message(msg)

        sent_text = mock_send.call_args[0][1]
        assert "No text response generated" in sent_text

    async def test_sdk_error_sends_apology(self, orchestrator_config):
        """SDK exception sends error message to user."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        orch._client = MagicMock()
        orch._client.query = AsyncMock(side_effect=RuntimeError("SDK broke"))

        msg = _make_bot_message()

        with patch("app.apps.agent.orchestrator.send_typing_action", new_callable=AsyncMock), \
             patch("app.apps.agent.orchestrator.pull_base", new_callable=AsyncMock), \
             patch("app.apps.agent.orchestrator.send_message", new_callable=AsyncMock) as mock_send, \
             patch("app.apps.agent.orchestrator.escape_markdown_v2", side_effect=lambda x: x):
            await orch._handle_user_message(msg)

        sent_text = mock_send.call_args[0][1]
        assert "went wrong" in sent_text


# --- _extract_pr_link ---


class TestExtractPrLink:
    async def test_finds_pr_link(self, orchestrator_config):
        """Extracts PR link from card comments."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        actions = [
            {"data": {"text": "PR opened: https://github.com/acme/app/pull/42"}},
        ]
        with patch("app.apps.agent.orchestrator.get_card_actions", new_callable=AsyncMock, return_value=actions):
            link = await orch._extract_pr_link("card_id")
        assert link == "https://github.com/acme/app/pull/42"

    async def test_no_pr_link(self, orchestrator_config):
        """Returns None when no PR link is found."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        actions = [{"data": {"text": "Some comment"}}]
        with patch("app.apps.agent.orchestrator.get_card_actions", new_callable=AsyncMock, return_value=actions):
            link = await orch._extract_pr_link("card_id")
        assert link is None

    async def test_api_error_returns_none(self, orchestrator_config):
        """API error returns None instead of raising."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        with patch("app.apps.agent.orchestrator.get_card_actions", new_callable=AsyncMock, side_effect=RuntimeError):
            link = await orch._extract_pr_link("card_id")
        assert link is None


# --- _parse_dependencies ---


class TestParseDependencies:
    def test_extracts_card_ids(self):
        """Extracts 24-char hex card IDs from dependencies section."""
        desc = (
            "## Task\nDo something\n\n"
            "## Dependencies\n"
            "- Requires: abc123def456789012345678 (api agent) to be in Done\n"
            "- Requires: 111222333444555666777888 (frontend agent) to be in Done\n\n"
            "## Acceptance Criteria\n"
            "- [ ] Tests pass\n"
        )
        ids = OrchestratorAgent._parse_dependencies(desc)
        assert ids == ["abc123def456789012345678", "111222333444555666777888"]

    def test_no_dependencies_section(self):
        """Returns empty list when no dependencies section exists."""
        desc = "## Task\nDo something\n\n## Acceptance Criteria\n- [ ] Done\n"
        ids = OrchestratorAgent._parse_dependencies(desc)
        assert ids == []

    def test_empty_dependencies_section(self):
        """Returns empty list when dependencies section has no card IDs."""
        desc = "## Task\nDo something\n\n## Dependencies\n\n## Acceptance Criteria\n"
        ids = OrchestratorAgent._parse_dependencies(desc)
        assert ids == []

    def test_stops_at_next_section(self):
        """Stops parsing at the next ## header."""
        desc = (
            "## Dependencies\n"
            "- Requires: aabbccddee112233445566ff\n"
            "## Acceptance Criteria\n"
            "- Contains: 112233445566778899aabbcc (should NOT be captured)\n"
        )
        ids = OrchestratorAgent._parse_dependencies(desc)
        assert ids == ["aabbccddee112233445566ff"]

    def test_case_insensitive_header(self):
        """Dependencies header is matched case-insensitively."""
        desc = "## DEPENDENCIES\n- Requires: aabbccddee112233445566ff\n"
        ids = OrchestratorAgent._parse_dependencies(desc)
        assert ids == ["aabbccddee112233445566ff"]


# --- _find_unblocked_cards ---


class TestFindUnblockedCards:
    async def test_finds_unblocked_card(self, orchestrator_config):
        """Card with all dependencies satisfied is returned."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)

        # Card IDs must be 24-char hex to match the regex in _parse_dependencies
        completed_id = "aabbccddee112233ff445566"
        waiting_id = "112233445566778899aabbcc"

        dep_card = make_card(
            card_id=waiting_id,
            desc=f"## Dependencies\n- Requires: {completed_id} (api) to be in Done\n",
            id_list="todo_list_id",
        )
        completed_dep = make_card(card_id=completed_id, id_list="done_list_id")

        with patch("app.apps.agent.orchestrator.settings") as mock_settings, \
             patch("app.apps.agent.orchestrator.get_list_cards", new_callable=AsyncMock, return_value=[dep_card]), \
             patch("app.apps.agent.orchestrator.get_card", new_callable=AsyncMock, return_value=completed_dep):
            mock_settings.all_workers = {"api": MagicMock(lists=MagicMock(todo="todo_list_id"))}
            mock_settings.done_list_ids = {"done_list_id"}
            unblocked = await orch._find_unblocked_cards(completed_id)

        assert len(unblocked) == 1
        assert unblocked[0]["card_id"] == waiting_id
        assert unblocked[0]["worker"] == "api"

    async def test_card_with_unsatisfied_dep_not_returned(self, orchestrator_config):
        """Card with an unsatisfied dependency is not returned."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)

        done_id = "aabbccddee112233ff445566"
        doing_id = "112233445566778899aabbcc"
        blocked_id = "ffeeddccbbaa998877665544"

        dep_card = make_card(
            card_id=blocked_id,
            desc=(
                "## Dependencies\n"
                f"- Requires: {done_id} (api)\n"
                f"- Requires: {doing_id} (api)\n"
            ),
            id_list="todo_list_id",
        )
        done_card = make_card(card_id=done_id, id_list="done_list_id")
        doing_card = make_card(card_id=doing_id, id_list="doing_list_id")

        async def mock_get_card(card_id):
            if card_id == done_id:
                return done_card
            return doing_card

        with patch("app.apps.agent.orchestrator.settings") as mock_settings, \
             patch("app.apps.agent.orchestrator.get_list_cards", new_callable=AsyncMock, return_value=[dep_card]), \
             patch("app.apps.agent.orchestrator.get_card", new_callable=AsyncMock, side_effect=mock_get_card):
            mock_settings.all_workers = {"api": MagicMock(lists=MagicMock(todo="todo_list_id"))}
            mock_settings.done_list_ids = {"done_list_id"}
            unblocked = await orch._find_unblocked_cards(done_id)

        assert len(unblocked) == 0

    async def test_card_without_completed_dep_not_returned(self, orchestrator_config):
        """Card whose dependency list doesn't include the completed card is skipped."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)

        other_id = "aabbccddee112233ff445566"
        completed_id = "112233445566778899aabbcc"
        unrelated_id = "ffeeddccbbaa998877665544"

        dep_card = make_card(
            card_id=unrelated_id,
            desc=f"## Dependencies\n- Requires: {other_id} (api)\n",
            id_list="todo_list_id",
        )

        with patch("app.apps.agent.orchestrator.settings") as mock_settings, \
             patch("app.apps.agent.orchestrator.get_list_cards", new_callable=AsyncMock, return_value=[dep_card]):
            mock_settings.all_workers = {"api": MagicMock(lists=MagicMock(todo="todo_list_id"))}
            unblocked = await orch._find_unblocked_cards(completed_id)

        assert len(unblocked) == 0


# --- _notify_chats ---


class TestNotifyChats:
    async def test_sends_to_known_chats(self, orchestrator_config):
        """Sends message to all known chat IDs."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        orch._known_chat_ids = {100, 200}

        with patch("app.apps.agent.orchestrator.send_message", new_callable=AsyncMock) as mock_send, \
             patch("app.apps.agent.orchestrator.escape_markdown_v2", side_effect=lambda x: x):
            await orch._notify_chats("Test notification")

        assert mock_send.await_count == 2

    async def test_falls_back_to_allowed_users(self, orchestrator_config):
        """Falls back to telegram_allowed_user_ids when no known chat IDs."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)

        with patch("app.apps.agent.orchestrator.send_message", new_callable=AsyncMock) as mock_send, \
             patch("app.apps.agent.orchestrator.escape_markdown_v2", side_effect=lambda x: x), \
             patch("app.apps.agent.orchestrator.settings") as mock_settings:
            mock_settings.telegram_allowed_user_ids = [111, 222]
            await orch._notify_chats("Fallback notification")

        assert mock_send.await_count == 2

    async def test_swallows_send_errors(self, orchestrator_config):
        """Telegram send errors are logged but do not raise."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        orch._known_chat_ids = {100}

        with patch("app.apps.agent.orchestrator.send_message", new_callable=AsyncMock, side_effect=RuntimeError("network")), \
             patch("app.apps.agent.orchestrator.escape_markdown_v2", side_effect=lambda x: x):
            await orch._notify_chats("Will fail silently")  # Should not raise


# --- _handle_done_event ---


class TestHandleDoneEvent:
    async def test_basic_notification(self, orchestrator_config):
        """Sends notification with card name."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        orch._known_chat_ids = {100}
        event = {"card_name": "Add login", "card_id": "card_abc"}

        with patch.object(orch, "_extract_pr_link", new_callable=AsyncMock, return_value=None), \
             patch.object(orch, "_find_unblocked_cards", new_callable=AsyncMock, return_value=[]), \
             patch.object(orch, "_notify_chats", new_callable=AsyncMock) as mock_notify:
            await orch._handle_done_event(event)

        msg = mock_notify.call_args[0][0]
        assert "Add login" in msg

    async def test_includes_pr_link(self, orchestrator_config):
        """Includes PR link in notification when available."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        orch._known_chat_ids = {100}
        event = {"card_name": "Add login", "card_id": "card_abc"}

        with patch.object(orch, "_extract_pr_link", new_callable=AsyncMock, return_value="https://github.com/test/pr/1"), \
             patch.object(orch, "_find_unblocked_cards", new_callable=AsyncMock, return_value=[]), \
             patch.object(orch, "_notify_chats", new_callable=AsyncMock) as mock_notify:
            await orch._handle_done_event(event)

        msg = mock_notify.call_args[0][0]
        assert "https://github.com/test/pr/1" in msg

    async def test_includes_unblocked_cards(self, orchestrator_config):
        """Includes unblocked card names in notification."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        orch._known_chat_ids = {100}
        event = {"card_name": "Add login", "card_id": "card_abc"}

        unblocked = [
            {"card_id": "c1", "card_name": "Add dashboard", "worker": "frontend"},
        ]

        with patch.object(orch, "_extract_pr_link", new_callable=AsyncMock, return_value=None), \
             patch.object(orch, "_find_unblocked_cards", new_callable=AsyncMock, return_value=unblocked), \
             patch.object(orch, "_notify_chats", new_callable=AsyncMock) as mock_notify:
            await orch._handle_done_event(event)

        msg = mock_notify.call_args[0][0]
        assert "Add dashboard" in msg
        assert "Unblocked" in msg


# --- _handle_failed_event ---


class TestHandleFailedEvent:
    async def test_notifies_failure(self, orchestrator_config):
        """Sends failure notification via Telegram."""
        orch = OrchestratorAgent("orchestrator", orchestrator_config)
        event = {"card_name": "Broken task", "card_id": "card_xyz"}

        with patch.object(orch, "_notify_chats", new_callable=AsyncMock) as mock_notify:
            await orch._handle_failed_event(event)

        msg = mock_notify.call_args[0][0]
        assert "Broken task" in msg
        assert "failed" in msg.lower()
