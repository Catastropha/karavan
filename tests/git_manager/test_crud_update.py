"""Tests for git update operations — pull_base, commit_and_push, and create_pr."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest

from app.apps.git_manager.crud.update import commit_and_push, create_pr, pull_base
from app.apps.git_manager.model.input import PRCreateIn


class TestPullBase:
    async def test_checkouts_and_pulls_default_branch(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await pull_base("/tmp/repo")

        assert mock_exec.call_count == 2
        checkout_args = mock_exec.call_args_list[0].args
        pull_args = mock_exec.call_args_list[1].args
        assert checkout_args == ("git", "checkout", "main")
        assert pull_args == ("git", "pull", "origin", "main")

    async def test_uses_custom_branch(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await pull_base("/tmp/repo", branch="develop")

        checkout_args = mock_exec.call_args_list[0].args
        pull_args = mock_exec.call_args_list[1].args
        assert checkout_args == ("git", "checkout", "develop")
        assert pull_args == ("git", "pull", "origin", "develop")

    async def test_passes_cwd(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await pull_base("/tmp/my-repo")

        for mock_call in mock_exec.call_args_list:
            assert mock_call.kwargs["cwd"] == "/tmp/my-repo"

    async def test_accepts_path_object(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await pull_base(Path("/tmp/repo"))

        for mock_call in mock_exec.call_args_list:
            assert mock_call.kwargs["cwd"] == "/tmp/repo"

    async def test_propagates_checkout_error(self, mock_process):
        proc = mock_process(returncode=1, stderr=b"error: pathspec 'main' did not match")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(RuntimeError, match="pathspec"):
                await pull_base("/tmp/repo")

    async def test_propagates_pull_error(self, mock_process):
        """Checkout succeeds but pull fails."""
        proc_ok = mock_process()
        proc_fail = mock_process(returncode=1, stderr=b"fatal: couldn't find remote ref")

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return proc_ok if call_count == 1 else proc_fail

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            with pytest.raises(RuntimeError, match="remote ref"):
                await pull_base("/tmp/repo")


class TestCommitAndPush:
    async def test_returns_true_when_changes_exist(self, mock_process):
        """diff --cached --quiet returns 1 when there are staged changes."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # 1: git add -A (rc=0), 2: git diff --cached --quiet (rc=1 = has changes),
            # 3: git commit (rc=0), 4: git push (rc=0)
            if call_count == 2:
                return mock_process(returncode=1)
            return mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await commit_and_push("/tmp/repo", "feature/branch", "[karavan] Task")

        assert result is True

    async def test_returns_false_when_no_changes(self, mock_process):
        """diff --cached --quiet returns 0 when no staged changes."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # 1: git add -A (rc=0), 2: git diff --cached --quiet (rc=0 = no changes)
            return mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await commit_and_push("/tmp/repo", "feature/branch", "[karavan] Task")

        assert result is False

    async def test_stages_all_changes_first(self, mock_process):
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect) as mock_exec:
            await commit_and_push("/tmp/repo", "branch", "msg")

        first_call_args = mock_exec.call_args_list[0].args
        assert first_call_args == ("git", "add", "-A")

    async def test_skips_commit_push_when_no_changes(self, mock_process):
        """When no changes, should only call add and diff (2 calls total)."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect) as mock_exec:
            await commit_and_push("/tmp/repo", "branch", "msg")

        assert mock_exec.call_count == 2

    async def test_commits_with_message(self, mock_process):
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return mock_process(returncode=1)  # has changes
            return mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect) as mock_exec:
            await commit_and_push("/tmp/repo", "branch", "[karavan] Fix bug")

        commit_args = mock_exec.call_args_list[2].args
        assert commit_args == ("git", "commit", "-m", "[karavan] Fix bug")

    async def test_pushes_with_upstream(self, mock_process):
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return mock_process(returncode=1)  # has changes
            return mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect) as mock_exec:
            await commit_and_push("/tmp/repo", "agent/api/card-abc123", "msg")

        push_args = mock_exec.call_args_list[3].args
        assert push_args == ("git", "push", "-u", "origin", "agent/api/card-abc123")

    async def test_passes_cwd_to_all_commands(self, mock_process):
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return mock_process(returncode=1)
            return mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect) as mock_exec:
            await commit_and_push("/tmp/my-repo", "branch", "msg")

        for mock_call in mock_exec.call_args_list:
            assert mock_call.kwargs["cwd"] == "/tmp/my-repo"

    async def test_propagates_commit_error(self, mock_process):
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return mock_process(returncode=1)  # has changes
            if call_count == 3:
                return mock_process(returncode=1, stderr=b"error: commit failed")
            return mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            with pytest.raises(RuntimeError, match="commit failed"):
                await commit_and_push("/tmp/repo", "branch", "msg")


class TestCreatePR:
    async def test_creates_pr(self, github_client, make_response):
        pr_data = {
            "number": 42,
            "html_url": "https://github.com/user/repo/pull/42",
            "title": "Add feature",
            "state": "open",
        }
        github_client.post.return_value = make_response(pr_data)

        pr_in = PRCreateIn.model_validate({
            "owner": "user",
            "repo": "myproject",
            "title": "Add feature",
            "head": "feature/branch",
        })
        result = await create_pr(pr_in)

        assert result.number == 42
        assert result.html_url == "https://github.com/user/repo/pull/42"
        assert result.title == "Add feature"
        assert result.state == "open"

    async def test_sends_correct_endpoint(self, github_client, make_response):
        github_client.post.return_value = make_response({
            "number": 1,
            "html_url": "https://github.com/user/repo/pull/1",
            "title": "Fix",
        })

        pr_in = PRCreateIn.model_validate({
            "owner": "acme",
            "repo": "backend",
            "title": "Fix",
            "head": "fix/bug",
        })
        await create_pr(pr_in)

        args = github_client.post.call_args.args
        assert args == ("repos/acme/backend/pulls",)

    async def test_sends_correct_json_body(self, github_client, make_response):
        github_client.post.return_value = make_response({
            "number": 1,
            "html_url": "https://github.com/user/repo/pull/1",
            "title": "Add feature",
        })

        pr_in = PRCreateIn.model_validate({
            "owner": "user",
            "repo": "repo",
            "title": "Add feature",
            "body": "## Changes\n- Added endpoint",
            "head": "feature/api",
            "base": "develop",
        })
        await create_pr(pr_in)

        kwargs = github_client.post.call_args.kwargs
        assert kwargs["json"] == {
            "title": "Add feature",
            "body": "## Changes\n- Added endpoint",
            "head": "feature/api",
            "base": "develop",
        }

    async def test_uses_default_base_branch(self, github_client, make_response):
        github_client.post.return_value = make_response({
            "number": 1,
            "html_url": "https://github.com/user/repo/pull/1",
            "title": "Fix",
        })

        pr_in = PRCreateIn.model_validate({
            "owner": "user",
            "repo": "repo",
            "title": "Fix",
            "head": "fix/bug",
        })
        await create_pr(pr_in)

        kwargs = github_client.post.call_args.kwargs
        assert kwargs["json"]["base"] == "main"

    async def test_calls_raise_for_status(self, github_client, make_response):
        resp = make_response({
            "number": 1,
            "html_url": "https://github.com/user/repo/pull/1",
            "title": "Fix",
        })
        github_client.post.return_value = resp

        pr_in = PRCreateIn.model_validate({
            "owner": "user",
            "repo": "repo",
            "title": "Fix",
            "head": "fix/bug",
        })
        await create_pr(pr_in)

        resp.raise_for_status.assert_called_once()

    async def test_http_error_propagates(self, github_client):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unprocessable Entity", request=MagicMock(), response=resp,
        )
        github_client.post.return_value = resp

        pr_in = PRCreateIn.model_validate({
            "owner": "user",
            "repo": "repo",
            "title": "Fix",
            "head": "fix/bug",
        })
        with pytest.raises(httpx.HTTPStatusError):
            await create_pr(pr_in)

    async def test_extra_github_fields_ignored(self, github_client, make_response):
        """GitHub API returns many fields — PROut should ignore extras."""
        pr_data = {
            "number": 10,
            "html_url": "https://github.com/user/repo/pull/10",
            "title": "Feature",
            "state": "open",
            "user": {"login": "bot"},
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "merged": False,
            "comments": 0,
            "additions": 50,
            "deletions": 10,
        }
        github_client.post.return_value = make_response(pr_data)

        pr_in = PRCreateIn.model_validate({
            "owner": "user",
            "repo": "repo",
            "title": "Feature",
            "head": "feature/x",
        })
        result = await create_pr(pr_in)

        assert result.number == 10
        assert not hasattr(result, "user")
        assert not hasattr(result, "merged")
