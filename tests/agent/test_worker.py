"""Tests for WorkerAgent — card execution, stages, retry logic, and deduplication."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.apps.agent.worker import FAIL_PREFIX, MAX_RETRIES, WorkerAgent, _parse_repo_url
from app.apps.trello.model.output import CardOut
from app.core.config import BoardConfig, WorkerAgentConfig

from .conftest import make_card


# --- _parse_repo_url ---


class TestParseRepoUrl:
    def test_standard_ssh_url(self):
        owner, repo = _parse_repo_url("git@github.com:acme/myapp.git")
        assert owner == "acme"
        assert repo == "myapp"

    def test_without_dot_git(self):
        owner, repo = _parse_repo_url("git@github.com:acme/myapp")
        assert owner == "acme"
        assert repo == "myapp"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Cannot parse repo URL"):
            _parse_repo_url("https://github.com/acme/myapp")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Cannot parse repo URL"):
            _parse_repo_url("")


# --- WorkerAgent.__init__ ---


class TestWorkerAgentInit:
    def test_write_mode_parses_repo(self, worker_agent):
        """Write-mode worker parses owner/repo from SSH URL."""
        assert worker_agent.owner == "testowner"
        assert worker_agent.repo_name == "testrepo"
        assert worker_agent.name == "api"
        assert worker_agent._processed_cards == set()

    def test_none_mode_no_repo(self, cards_worker):
        """None-mode worker has empty owner/repo."""
        assert cards_worker.owner == ""
        assert cards_worker.repo_name == ""

    def test_read_mode_parses_repo(self, comment_worker):
        """Read-mode worker still parses owner/repo."""
        assert comment_worker.owner == "testowner"
        assert comment_worker.repo_name == "testrepo"


# --- should_process_webhook ---


class TestWorkerShouldProcessWebhook:
    def test_always_returns_false(self, worker_agent):
        """Label-based routing means should_process_webhook is not used."""
        assert worker_agent.should_process_webhook("todo_list_id") is False
        assert worker_agent.should_process_webhook("doing_list_id") is False
        assert worker_agent.should_process_webhook("random_list") is False


# --- _process ---


class TestWorkerProcess:
    async def test_ignores_non_dict(self, worker_agent):
        """Non-dict items are logged and skipped."""
        await worker_agent._process("not a dict")
        assert worker_agent._cards_processed == 0

    async def test_ignores_missing_card_id(self, worker_agent):
        """Dict without card_id is skipped."""
        await worker_agent._process({"some_key": "value"})

    async def test_skips_duplicate_card(self, worker_agent):
        """Cards already in _processed_cards are skipped."""
        worker_agent._processed_cards.add("card_123")
        with patch.object(worker_agent, "_execute_card") as mock_exec:
            await worker_agent._process({"card_id": "card_123"})
            mock_exec.assert_not_called()

    async def test_calls_execute_card(self, worker_agent):
        """Valid item triggers _execute_card."""
        with patch.object(worker_agent, "_execute_card", new_callable=AsyncMock) as mock_exec:
            await worker_agent._process({"card_id": "card_456"})
            mock_exec.assert_awaited_once_with("card_456")


# --- _count_failures ---


class TestCountFailures:
    async def test_counts_fail_comments(self, worker_agent):
        """Counts comments starting with FAIL_PREFIX."""
        actions = [
            {"data": {"text": f"{FAIL_PREFIX} Attempt 1/3 failed"}},
            {"data": {"text": "PR opened: https://github.com/..."}},
            {"data": {"text": f"{FAIL_PREFIX} Attempt 2/3 failed"}},
        ]
        with patch("app.apps.agent.worker.get_card_actions", new_callable=AsyncMock, return_value=actions):
            count = await worker_agent._count_failures("card_id")
        assert count == 2

    async def test_zero_when_no_failures(self, worker_agent):
        """Returns 0 when no fail comments exist."""
        actions = [{"data": {"text": "Normal comment"}}]
        with patch("app.apps.agent.worker.get_card_actions", new_callable=AsyncMock, return_value=actions):
            count = await worker_agent._count_failures("card_id")
        assert count == 0

    async def test_empty_actions(self, worker_agent):
        """Returns 0 for empty actions list."""
        with patch("app.apps.agent.worker.get_card_actions", new_callable=AsyncMock, return_value=[]):
            count = await worker_agent._count_failures("card_id")
        assert count == 0


# --- _setup_repo ---


class TestSetupRepo:
    async def test_write_mode_clones_pulls_branches(self, worker_agent):
        """Write-mode calls clone, pull, and create_branch."""
        with patch("app.apps.agent.worker.clone_repo", new_callable=AsyncMock) as mock_clone, \
             patch("app.apps.agent.worker.pull_base", new_callable=AsyncMock) as mock_pull, \
             patch("app.apps.agent.worker.create_branch", new_callable=AsyncMock) as mock_branch:
            await worker_agent._setup_repo("agent/api/card-abc123")
            mock_clone.assert_awaited_once()
            mock_pull.assert_awaited_once_with(worker_agent.repo_dir, "main")
            mock_branch.assert_awaited_once_with(worker_agent.repo_dir, "agent/api/card-abc123")

    async def test_read_mode_clones_pulls_no_branch(self, comment_worker):
        """Read-mode calls clone and pull, but not create_branch."""
        with patch("app.apps.agent.worker.clone_repo", new_callable=AsyncMock) as mock_clone, \
             patch("app.apps.agent.worker.pull_base", new_callable=AsyncMock) as mock_pull, \
             patch("app.apps.agent.worker.create_branch", new_callable=AsyncMock) as mock_branch:
            await comment_worker._setup_repo("unused")
            mock_clone.assert_awaited_once()
            mock_pull.assert_awaited_once()
            mock_branch.assert_not_awaited()

    async def test_none_mode_skips_all(self, cards_worker):
        """None-mode skips all git operations."""
        with patch("app.apps.agent.worker.clone_repo", new_callable=AsyncMock) as mock_clone:
            await cards_worker._setup_repo("unused")
            mock_clone.assert_not_awaited()


# --- _build_prompt ---


class TestBuildPrompt:
    def test_pr_mode_prompt(self, worker_agent):
        """PR-mode prompt includes environment, branch, and git rules."""
        card = make_card()
        prompt = worker_agent._build_prompt(card, "agent/api/card-345678")
        assert "# Task: Test task" in prompt
        assert "write code" in prompt
        assert "testowner/testrepo" in prompt
        assert "agent/api/card-345678" in prompt
        assert "DO NOT** run any git commands" in prompt
        assert "## Card Description" in prompt
        assert card.desc in prompt

    def test_comment_mode_prompt(self, comment_worker):
        """Comment-mode prompt instructs analysis, no file modifications."""
        card = make_card()
        prompt = comment_worker._build_prompt(card, "")
        assert "analyze" in prompt
        assert "read-only" in prompt.lower()
        assert "DO NOT** modify any files" in prompt

    def test_cards_mode_prompt(self, cards_worker):
        """Cards-mode prompt instructs creating sub-tasks via MCP tools."""
        card = make_card()
        prompt = cards_worker._build_prompt(card, "")
        assert "break down" in prompt
        assert "list_workers" in prompt
        assert "create_trello_card" in prompt

    def test_update_mode_prompt(self, update_worker):
        """Update-mode prompt instructs rewriting the card description."""
        card = make_card()
        prompt = update_worker._build_prompt(card, "")
        assert "improved version" in prompt
        assert "ONLY the updated card description" in prompt

    def test_none_repo_access_no_environment(self, cards_worker):
        """No environment section when repo_access is none."""
        card = make_card()
        prompt = cards_worker._build_prompt(card, "")
        assert "## Environment" not in prompt

    def test_read_repo_access_shows_directory(self, comment_worker):
        """Read-mode shows directory as read-only context."""
        card = make_card()
        prompt = comment_worker._build_prompt(card, "")
        assert "read-only context" in prompt


# --- _run_sdk ---


class TestRunSdk:
    async def test_write_mode_sets_cwd(self, worker_agent):
        """Write-mode passes cwd in the SDK kwargs dict."""
        card = make_card()
        tracker = MagicMock()
        tracker.record_activity = MagicMock()
        captured_kwargs = {}

        def mock_validate(data):
            captured_kwargs.update(data)
            return MagicMock()

        with patch("app.apps.agent.worker.query") as mock_query, \
             patch("app.apps.agent.worker.ClaudeAgentOptions") as mock_opts:
            mock_opts.model_validate = mock_validate
            mock_query.return_value = aiter_from([])
            await worker_agent._run_sdk(card, "agent/api/card-345678", tracker)

        assert captured_kwargs["cwd"] == str(worker_agent.repo_dir)
        assert "add_dirs" not in captured_kwargs

    async def test_read_mode_sets_add_dirs(self, comment_worker):
        """Read-mode passes add_dirs in the SDK kwargs dict."""
        card = make_card()
        tracker = MagicMock()
        tracker.record_activity = MagicMock()
        captured_kwargs = {}

        def mock_validate(data):
            captured_kwargs.update(data)
            return MagicMock()

        with patch("app.apps.agent.worker.query") as mock_query, \
             patch("app.apps.agent.worker.ClaudeAgentOptions") as mock_opts:
            mock_opts.model_validate = mock_validate
            mock_query.return_value = aiter_from([])
            await comment_worker._run_sdk(card, "", tracker)

        assert str(comment_worker.repo_dir) in captured_kwargs["add_dirs"]
        assert "cwd" not in captured_kwargs

    async def test_cards_mode_adds_mcp_tools(self, cards_worker):
        """Cards-mode includes MCP server and tool names in SDK kwargs."""
        card = make_card()
        tracker = MagicMock()
        tracker.record_activity = MagicMock()
        captured_kwargs = {}

        def mock_validate(data):
            captured_kwargs.update(data)
            return MagicMock()

        with patch("app.apps.agent.worker.query") as mock_query, \
             patch("app.apps.agent.worker.ClaudeAgentOptions") as mock_opts, \
             patch("app.apps.agent.worker.build_mcp_server") as mock_mcp:
            mock_opts.model_validate = mock_validate
            mock_mcp.return_value = MagicMock()
            mock_query.return_value = aiter_from([])
            await cards_worker._run_sdk(card, "", tracker)

        mock_mcp.assert_called_once_with("karavan_worker")
        assert "karavan" in captured_kwargs["mcp_servers"]
        assert "list_workers" in captured_kwargs["allowed_tools"]
        assert "create_trello_card" in captured_kwargs["allowed_tools"]

    async def test_collects_result_from_result_message(self, worker_agent):
        """Extracts result text, cost, and usage from the final ResultMessage."""
        card = make_card()
        tracker = MagicMock()
        tracker.record_activity = MagicMock()

        result_msg = MagicMock()
        result_msg.total_cost_usd = 0.05
        result_msg.usage = {"input_tokens": 1000, "output_tokens": 500}
        result_msg.result = "I changed file X."

        with patch("app.apps.agent.worker.query") as mock_query, \
             patch("app.apps.agent.worker.ClaudeAgentOptions") as mock_opts:
            mock_opts.model_validate = MagicMock(return_value=MagicMock())
            mock_query.return_value = aiter_from([result_msg])
            text, cost, usage = await worker_agent._run_sdk(card, "branch", tracker)

        assert text == "I changed file X."
        assert cost == 0.05
        assert usage == {"input_tokens": 1000, "output_tokens": 500}
        tracker.record_activity.assert_called_once_with(result_msg)


# --- _deliver_output ---


class TestDeliverOutput:
    async def test_comment_mode_adds_comment(self, comment_worker):
        """Comment mode posts result text as a Trello comment."""
        card = make_card()
        with patch("app.apps.agent.worker.add_comment", new_callable=AsyncMock) as mock_comment:
            result = await comment_worker._deliver_output(card, "card_id", "", "Analysis result", 0.03, MagicMock())
        assert result is True
        call_text = mock_comment.call_args[0][1]
        assert "Analysis result" in call_text
        assert "$0.0300" in call_text

    async def test_comment_mode_default_text(self, comment_worker):
        """Comment mode uses fallback text when result is empty."""
        card = make_card()
        with patch("app.apps.agent.worker.add_comment", new_callable=AsyncMock) as mock_comment:
            await comment_worker._deliver_output(card, "card_id", "", "", None, MagicMock())
        call_text = mock_comment.call_args[0][1]
        assert "no text output" in call_text.lower()

    async def test_cards_mode_adds_summary(self, cards_worker):
        """Cards mode posts a summary comment."""
        card = make_card()
        with patch("app.apps.agent.worker.add_comment", new_callable=AsyncMock) as mock_comment:
            result = await cards_worker._deliver_output(card, "card_id", "", "Created 3 cards", 0.02, MagicMock())
        assert result is True
        call_text = mock_comment.call_args[0][1]
        assert "Created 3 cards" in call_text

    async def test_cards_mode_truncates_long_text(self, cards_worker):
        """Cards mode truncates result text to 500 chars."""
        card = make_card()
        long_text = "x" * 600
        with patch("app.apps.agent.worker.add_comment", new_callable=AsyncMock) as mock_comment:
            await cards_worker._deliver_output(card, "card_id", "", long_text, None, MagicMock())
        call_text = mock_comment.call_args[0][1]
        assert len(call_text) <= 510  # 500 + some slack

    async def test_update_mode_updates_description(self, update_worker):
        """Update mode rewrites the card description."""
        card = make_card()
        with patch("app.apps.agent.worker.update_card", new_callable=AsyncMock) as mock_update, \
             patch("app.apps.agent.worker.add_comment", new_callable=AsyncMock) as mock_comment:
            result = await update_worker._deliver_output(card, "card_id", "", "New description", 0.01, MagicMock())
        assert result is True
        mock_update.assert_awaited_once_with("card_id", desc="New description")
        call_text = mock_comment.call_args[0][1]
        assert "Description updated" in call_text
        assert "$0.0100" in call_text

    async def test_update_mode_no_text_skips_update(self, update_worker):
        """Update mode does not call update_card when result text is empty."""
        card = make_card()
        with patch("app.apps.agent.worker.update_card", new_callable=AsyncMock) as mock_update, \
             patch("app.apps.agent.worker.add_comment", new_callable=AsyncMock):
            await update_worker._deliver_output(card, "card_id", "", "", 0.01, MagicMock())
        # update_card should only be called for cost comment, not for desc
        for call in mock_update.call_args_list:
            assert "desc" not in (call.kwargs or {})


# --- _deliver_pr ---


class TestDeliverPr:
    async def test_success_creates_pr(self, worker_agent):
        """Successful PR delivery commits, pushes, creates PR, and comments link."""
        card = make_card()
        pr_out = MagicMock()
        pr_out.html_url = "https://github.com/testowner/testrepo/pull/42"

        tracker = AsyncMock()

        with patch("app.apps.agent.worker.commit_and_push", new_callable=AsyncMock, return_value=True) as mock_cap, \
             patch("app.apps.agent.worker.create_pr", new_callable=AsyncMock, return_value=pr_out), \
             patch("app.apps.agent.worker.add_comment", new_callable=AsyncMock) as mock_comment:
            result = await worker_agent._deliver_pr(card, "card_id", "branch", "Changes summary", 0.05, tracker)

        assert result is True
        mock_cap.assert_awaited_once()
        comment_text = mock_comment.call_args[0][1]
        assert "https://github.com/testowner/testrepo/pull/42" in comment_text
        assert "$0.0500" in comment_text
        tracker.finish.assert_awaited_once_with(success=True, pr_url="https://github.com/testowner/testrepo/pull/42", cost_usd=0.05)

    async def test_no_changes_moves_to_failed(self, worker_agent):
        """When commit_and_push returns False (no changes), card moves to failed."""
        card = make_card()
        tracker = AsyncMock()

        with patch("app.apps.agent.worker.commit_and_push", new_callable=AsyncMock, return_value=False), \
             patch("app.apps.agent.worker.add_comment", new_callable=AsyncMock) as mock_comment, \
             patch("app.apps.agent.worker.update_card", new_callable=AsyncMock) as mock_update:
            result = await worker_agent._deliver_pr(card, "card_id", "branch", "", None, tracker)

        assert result is False
        # Should add fail comment
        call_text = mock_comment.call_args[0][1]
        assert FAIL_PREFIX in call_text
        # Should move to failed list
        mock_update.assert_awaited_once_with("card_id", id_list="failed_list_id")
        tracker.finish.assert_awaited_once_with(success=False, error="No code changes produced")


# --- _execute_card ---


class TestExecuteCard:
    async def test_skips_card_not_in_todo(self, worker_agent):
        """Card not in the todo list is skipped."""
        card = make_card(id_list="doing_list_id", id_labels=["lbl_api"])
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch.object(worker_agent, "_setup_repo", new_callable=AsyncMock) as mock_setup:
            await worker_agent._execute_card("card_id")
            mock_setup.assert_not_awaited()

    async def test_skips_card_without_label(self, worker_agent):
        """Card without the worker's label is skipped."""
        card = make_card(id_labels=["lbl_other"])
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch.object(worker_agent, "_setup_repo", new_callable=AsyncMock) as mock_setup:
            await worker_agent._execute_card("card_id")
            mock_setup.assert_not_awaited()

    async def test_adds_card_to_processed_set(self, worker_agent):
        """Card ID is added to _processed_cards after pickup."""
        card = make_card(id_labels=["lbl_api"])
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch("app.apps.agent.worker.update_card", new_callable=AsyncMock), \
             patch("app.apps.agent.worker.remove_label", new_callable=AsyncMock), \
             patch.object(worker_agent, "_setup_repo", new_callable=AsyncMock), \
             patch.object(worker_agent, "_run_sdk", new_callable=AsyncMock, return_value=("result", 0.01, {})), \
             patch.object(worker_agent, "_deliver_output", new_callable=AsyncMock, return_value=True), \
             patch("app.apps.agent.worker.cost_tracker") as mock_ct, \
             patch("app.apps.agent.worker.ProgressTracker") as mock_pt:
            mock_pt.return_value = AsyncMock()
            await worker_agent._execute_card("abc123def456789012345678")

        assert "abc123def456789012345678" in worker_agent._processed_cards

    async def test_moves_card_to_doing(self, worker_agent):
        """Card is moved to the doing list at the start of execution."""
        card = make_card(id_labels=["lbl_api"])
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch("app.apps.agent.worker.update_card", new_callable=AsyncMock) as mock_update, \
             patch("app.apps.agent.worker.remove_label", new_callable=AsyncMock), \
             patch.object(worker_agent, "_setup_repo", new_callable=AsyncMock), \
             patch.object(worker_agent, "_run_sdk", new_callable=AsyncMock, return_value=("result", 0.01, {})), \
             patch.object(worker_agent, "_deliver_output", new_callable=AsyncMock, return_value=True), \
             patch("app.apps.agent.worker.cost_tracker") as mock_ct, \
             patch("app.apps.agent.worker.ProgressTracker") as mock_pt:
            mock_pt.return_value = AsyncMock()
            await worker_agent._execute_card("abc123def456789012345678")

        # First update_card call should be moving to doing
        first_call = mock_update.call_args_list[0]
        assert first_call == (("abc123def456789012345678",), {"id_list": "doing_list_id"})

    async def test_moves_card_to_done_on_success(self, worker_agent):
        """Terminal worker removes label and moves card to done list."""
        card = make_card(id_labels=["lbl_api"])
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch("app.apps.agent.worker.update_card", new_callable=AsyncMock) as mock_update, \
             patch("app.apps.agent.worker.remove_label", new_callable=AsyncMock) as mock_remove, \
             patch.object(worker_agent, "_setup_repo", new_callable=AsyncMock), \
             patch.object(worker_agent, "_run_sdk", new_callable=AsyncMock, return_value=("result", 0.01, {})), \
             patch.object(worker_agent, "_deliver_output", new_callable=AsyncMock, return_value=True), \
             patch("app.apps.agent.worker.cost_tracker") as mock_ct, \
             patch("app.apps.agent.worker.ProgressTracker") as mock_pt:
            mock_pt.return_value = AsyncMock()
            await worker_agent._execute_card("abc123def456789012345678")

        # Label should be removed
        mock_remove.assert_awaited_once_with("abc123def456789012345678", "lbl_api")
        # Last update_card call should be moving to done
        last_call = mock_update.call_args_list[-1]
        assert last_call == (("abc123def456789012345678",), {"id_list": "done_list_id"})

    async def test_branch_name_from_config(self, worker_agent):
        """Branch name is constructed from branch_prefix and card_id suffix."""
        card = make_card(card_id="abc123def456789012345678", id_labels=["lbl_api"])
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch("app.apps.agent.worker.update_card", new_callable=AsyncMock), \
             patch("app.apps.agent.worker.remove_label", new_callable=AsyncMock), \
             patch.object(worker_agent, "_setup_repo", new_callable=AsyncMock) as mock_setup, \
             patch.object(worker_agent, "_run_sdk", new_callable=AsyncMock, return_value=("", 0.0, {})), \
             patch.object(worker_agent, "_deliver_output", new_callable=AsyncMock, return_value=True), \
             patch("app.apps.agent.worker.cost_tracker"), \
             patch("app.apps.agent.worker.ProgressTracker") as mock_pt:
            mock_pt.return_value = AsyncMock()
            await worker_agent._execute_card("abc123def456789012345678")

        mock_setup.assert_awaited_once_with("agent/api/card-345678")

    async def test_no_branch_prefix_gives_empty_branch(self, cards_worker):
        """Worker without branch_prefix produces an empty branch name."""
        card = make_card(id_labels=["lbl_planner"])
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch("app.apps.agent.worker.update_card", new_callable=AsyncMock), \
             patch("app.apps.agent.worker.remove_label", new_callable=AsyncMock), \
             patch.object(cards_worker, "_setup_repo", new_callable=AsyncMock) as mock_setup, \
             patch.object(cards_worker, "_run_sdk", new_callable=AsyncMock, return_value=("", 0.0, {})), \
             patch.object(cards_worker, "_deliver_output", new_callable=AsyncMock, return_value=True), \
             patch("app.apps.agent.worker.cost_tracker"), \
             patch("app.apps.agent.worker.ProgressTracker") as mock_pt:
            mock_pt.return_value = AsyncMock()
            await cards_worker._execute_card("abc123def456789012345678")

        mock_setup.assert_awaited_once_with("")

    async def test_records_cost(self, worker_agent):
        """Cost is recorded via cost_tracker after SDK run."""
        card = make_card(id_labels=["lbl_api"])
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch("app.apps.agent.worker.update_card", new_callable=AsyncMock), \
             patch("app.apps.agent.worker.remove_label", new_callable=AsyncMock), \
             patch.object(worker_agent, "_setup_repo", new_callable=AsyncMock), \
             patch.object(worker_agent, "_run_sdk", new_callable=AsyncMock, return_value=("result", 0.07, {"input_tokens": 100})), \
             patch.object(worker_agent, "_deliver_output", new_callable=AsyncMock, return_value=True), \
             patch("app.apps.agent.worker.cost_tracker") as mock_ct, \
             patch("app.apps.agent.worker.ProgressTracker") as mock_pt:
            mock_pt.return_value = AsyncMock()
            await worker_agent._execute_card("abc123def456789012345678")

        mock_ct.record.assert_called_once_with("api", 0.07, {"input_tokens": 100}, card_id="abc123def456789012345678")


# --- Retry logic ---


class TestRetryLogic:
    async def test_failure_adds_comment_and_retries(self, worker_agent):
        """On failure with retries remaining, card is moved back to todo with label re-add."""
        card = make_card(id_labels=["lbl_api"])
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch("app.apps.agent.worker.update_card", new_callable=AsyncMock) as mock_update, \
             patch("app.apps.agent.worker.remove_label", new_callable=AsyncMock) as mock_remove, \
             patch("app.apps.agent.worker.add_label", new_callable=AsyncMock) as mock_add, \
             patch.object(worker_agent, "_setup_repo", new_callable=AsyncMock, side_effect=RuntimeError("git failed")), \
             patch("app.apps.agent.worker.get_card_actions", new_callable=AsyncMock, return_value=[]), \
             patch("app.apps.agent.worker.add_comment", new_callable=AsyncMock) as mock_comment, \
             patch("app.apps.agent.worker.ProgressTracker") as mock_pt:
            mock_pt.return_value = AsyncMock()
            await worker_agent._execute_card("abc123def456789012345678")

        # Should add a fail comment with attempt count
        comment_text = mock_comment.call_args[0][1]
        assert FAIL_PREFIX in comment_text
        assert "Attempt 1/3" in comment_text
        assert "will retry" in comment_text

        # Card should be moved back to todo
        last_update = mock_update.call_args_list[-1]
        assert last_update == (("abc123def456789012345678",), {"id_list": "todo_list_id"})

        # Label should be re-added to re-trigger webhook
        mock_remove.assert_awaited_once_with("abc123def456789012345678", "lbl_api")
        mock_add.assert_awaited_once_with("abc123def456789012345678", "lbl_api")

        # Card should be removed from processed set
        assert "abc123def456789012345678" not in worker_agent._processed_cards

    async def test_max_retries_moves_to_failed(self, worker_agent):
        """On failure at max retries, card is moved to the failed list."""
        card = make_card(id_labels=["lbl_api"])
        # Simulate 2 prior failures
        prior_failures = [
            {"data": {"text": f"{FAIL_PREFIX} Attempt 1/3 failed"}},
            {"data": {"text": f"{FAIL_PREFIX} Attempt 2/3 failed"}},
        ]
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch("app.apps.agent.worker.update_card", new_callable=AsyncMock) as mock_update, \
             patch.object(worker_agent, "_setup_repo", new_callable=AsyncMock, side_effect=RuntimeError("git failed")), \
             patch("app.apps.agent.worker.get_card_actions", new_callable=AsyncMock, return_value=prior_failures), \
             patch("app.apps.agent.worker.add_comment", new_callable=AsyncMock) as mock_comment, \
             patch("app.apps.agent.worker.ProgressTracker") as mock_pt:
            mock_pt.return_value = AsyncMock()
            await worker_agent._execute_card("abc123def456789012345678")

        comment_text = mock_comment.call_args[0][1]
        assert "max retries reached" in comment_text

        # Card should be moved to failed list
        last_update = mock_update.call_args_list[-1]
        assert last_update == (("abc123def456789012345678",), {"id_list": "failed_list_id"})


# --- Graceful shutdown ---


class TestGracefulShutdown:
    async def test_stop_moves_inflight_card_to_todo(self, worker_agent):
        """On stop, an in-flight card is moved back to todo."""
        worker_agent._current_card_id = "card_inflight"
        worker_agent._processed_cards.add("card_inflight")

        with patch("app.apps.agent.worker.update_card", new_callable=AsyncMock) as mock_update:
            await worker_agent.stop()

        mock_update.assert_awaited_once_with("card_inflight", id_list="todo_list_id")
        assert "card_inflight" not in worker_agent._processed_cards

    async def test_stop_no_inflight_card_skips_cleanup(self, worker_agent):
        """On stop with no in-flight card, no Trello calls are made."""
        assert worker_agent._current_card_id is None

        with patch("app.apps.agent.worker.update_card", new_callable=AsyncMock) as mock_update:
            await worker_agent.stop()

        mock_update.assert_not_awaited()

    async def test_stop_handles_trello_error_gracefully(self, worker_agent):
        """If moving card back to todo fails, stop still completes."""
        worker_agent._current_card_id = "card_inflight"

        with patch("app.apps.agent.worker.update_card", new_callable=AsyncMock, side_effect=RuntimeError("Trello down")):
            await worker_agent.stop()  # Should not raise

        assert worker_agent._running is False

    async def test_current_card_id_cleared_after_execute(self, worker_agent):
        """_current_card_id is cleared after _execute_card completes."""
        card = make_card(id_labels=["lbl_api"])
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch("app.apps.agent.worker.update_card", new_callable=AsyncMock), \
             patch("app.apps.agent.worker.remove_label", new_callable=AsyncMock), \
             patch.object(worker_agent, "_setup_repo", new_callable=AsyncMock), \
             patch.object(worker_agent, "_run_sdk", new_callable=AsyncMock, return_value=("result", 0.01, {})), \
             patch.object(worker_agent, "_deliver_output", new_callable=AsyncMock, return_value=True), \
             patch("app.apps.agent.worker.cost_tracker"), \
             patch("app.apps.agent.worker.ProgressTracker") as mock_pt:
            mock_pt.return_value = AsyncMock()
            await worker_agent._execute_card("abc123def456789012345678")

        assert worker_agent._current_card_id is None

    async def test_current_card_id_cleared_after_failure(self, worker_agent):
        """_current_card_id is cleared even when _execute_card fails."""
        card = make_card(id_labels=["lbl_api"])
        with patch("app.apps.agent.worker.get_card", new_callable=AsyncMock, return_value=card), \
             patch("app.apps.agent.worker.update_card", new_callable=AsyncMock), \
             patch("app.apps.agent.worker.remove_label", new_callable=AsyncMock), \
             patch("app.apps.agent.worker.add_label", new_callable=AsyncMock), \
             patch.object(worker_agent, "_setup_repo", new_callable=AsyncMock, side_effect=RuntimeError("boom")), \
             patch("app.apps.agent.worker.get_card_actions", new_callable=AsyncMock, return_value=[]), \
             patch("app.apps.agent.worker.add_comment", new_callable=AsyncMock), \
             patch("app.apps.agent.worker.ProgressTracker") as mock_pt:
            mock_pt.return_value = AsyncMock()
            await worker_agent._execute_card("abc123def456789012345678")

        assert worker_agent._current_card_id is None


# --- Helpers ---


async def _aiter_items(items):
    """Create an async iterator from a list."""
    for item in items:
        yield item


def aiter_from(items):
    """Return an async iterable from a list (for mocking query())."""
    return _aiter_items(items)
