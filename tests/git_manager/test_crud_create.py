"""Tests for git create operations — _run_git, clone_repo, and create_branch."""

from pathlib import Path
from unittest.mock import AsyncMock, call, patch

import pytest

from app.apps.git_manager.crud.create import _run_git, clone_repo, create_branch


class TestRunGit:
    async def test_returns_stdout(self, mock_process):
        proc = mock_process(returncode=0, stdout=b"abc123\n")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            rc, stdout = await _run_git(["git", "status"])

        assert rc == 0
        assert stdout == "abc123"

    async def test_passes_command_args(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await _run_git(["git", "checkout", "-B", "feature/test"])

        args = mock_exec.call_args.args
        assert args == ("git", "checkout", "-B", "feature/test")

    async def test_passes_cwd(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await _run_git(["git", "status"], cwd="/tmp/repo")

        kwargs = mock_exec.call_args.kwargs
        assert kwargs["cwd"] == "/tmp/repo"

    async def test_cwd_none_when_not_provided(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await _run_git(["git", "status"])

        kwargs = mock_exec.call_args.kwargs
        assert kwargs["cwd"] is None

    async def test_path_cwd_converted_to_string(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await _run_git(["git", "status"], cwd=Path("/tmp/repo"))

        kwargs = mock_exec.call_args.kwargs
        assert kwargs["cwd"] == "/tmp/repo"

    async def test_raises_on_nonzero_exit_when_check(self, mock_process):
        proc = mock_process(returncode=128, stderr=b"fatal: not a git repository")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(RuntimeError, match="fatal: not a git repository"):
                await _run_git(["git", "status"], check=True)

    async def test_returns_exit_code_when_no_check(self, mock_process):
        proc = mock_process(returncode=1, stdout=b"")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            rc, stdout = await _run_git(["git", "diff", "--cached", "--quiet"], check=False)

        assert rc == 1
        assert stdout == ""

    async def test_sets_git_ssh_env(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await _run_git(["git", "clone", "repo"])

        kwargs = mock_exec.call_args.kwargs
        assert "GIT_SSH_COMMAND" in kwargs["env"]
        assert "StrictHostKeyChecking=no" in kwargs["env"]["GIT_SSH_COMMAND"]

    async def test_strips_stdout(self, mock_process):
        proc = mock_process(returncode=0, stdout=b"  output with spaces  \n")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            rc, stdout = await _run_git(["git", "log", "--oneline"])

        assert stdout == "output with spaces"


class TestCloneRepo:
    async def test_clones_repo(self, tmp_path, mock_process):
        target = tmp_path / "new_repo"
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await clone_repo("git@github.com:user/repo.git", target)

        args = mock_exec.call_args.args
        assert args == ("git", "clone", "git@github.com:user/repo.git", str(target))

    async def test_skips_when_target_exists(self, tmp_path, mock_process):
        target = tmp_path / "existing_repo"
        target.mkdir()
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            await clone_repo("git@github.com:user/repo.git", target)

        mock_exec.assert_not_called()

    async def test_creates_parent_directories(self, tmp_path, mock_process):
        target = tmp_path / "deep" / "nested" / "repo"
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            await clone_repo("git@github.com:user/repo.git", target)

        assert target.parent.exists()

    async def test_accepts_string_path(self, tmp_path, mock_process):
        target = str(tmp_path / "repo")
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await clone_repo("git@github.com:user/repo.git", target)

        args = mock_exec.call_args.args
        assert args == ("git", "clone", "git@github.com:user/repo.git", target)

    async def test_propagates_git_error(self, tmp_path, mock_process):
        target = tmp_path / "repo"
        proc = mock_process(returncode=128, stderr=b"fatal: repository not found")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(RuntimeError, match="repository not found"):
                await clone_repo("git@github.com:user/nonexistent.git", target)


class TestCreateBranch:
    async def test_creates_branch(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await create_branch("/tmp/repo", "agent/api/card-abc123")

        args = mock_exec.call_args.args
        assert args == ("git", "checkout", "-B", "agent/api/card-abc123")

    async def test_uses_idempotent_checkout(self, mock_process):
        """Verifies -B flag is used (resets branch if it already exists)."""
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await create_branch("/tmp/repo", "existing-branch")

        args = mock_exec.call_args.args
        assert "-B" in args

    async def test_passes_cwd(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await create_branch("/tmp/my-repo", "branch")

        kwargs = mock_exec.call_args.kwargs
        assert kwargs["cwd"] == "/tmp/my-repo"

    async def test_accepts_path_object(self, mock_process):
        proc = mock_process()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await create_branch(Path("/tmp/repo"), "branch")

        kwargs = mock_exec.call_args.kwargs
        assert kwargs["cwd"] == "/tmp/repo"

    async def test_propagates_git_error(self, mock_process):
        proc = mock_process(returncode=1, stderr=b"error: pathspec 'bad' did not match")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(RuntimeError):
                await create_branch("/tmp/repo", "bad")
