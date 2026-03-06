"""Git create operations — clone repos and create branches."""

import asyncio
import logging
import os
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

_GIT_ENV = {**os.environ, "GIT_SSH_COMMAND": f"ssh -i {settings.git_ssh_key_path} -o StrictHostKeyChecking=no"}


async def _run_git(cmd: list[str], cwd: str | Path | None = None, *, check: bool = True) -> tuple[int, str]:
    """Run a git command via subprocess. Returns (returncode, stdout).

    When *check* is True (default), raises RuntimeError on non-zero exit.
    When False, returns the exit code so callers can branch on it.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_GIT_ENV,
    )
    stdout, stderr = await proc.communicate()
    if check and proc.returncode != 0:
        error_msg = stderr.decode().strip()
        logger.error("Git command failed: %s -> %s", " ".join(cmd), error_msg)
        raise RuntimeError(f"Git command failed: {error_msg}")
    return proc.returncode, stdout.decode().strip()


async def clone_repo(repo_url: str, target_dir: str | Path) -> None:
    """Clone a git repository to the target directory."""
    target = Path(target_dir)
    if target.exists():
        logger.info("Repo already exists at %s, skipping clone", target)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    await _run_git(["git", "clone", repo_url, str(target)])
    logger.info("Cloned %s to %s", repo_url, target)


async def create_branch(repo_dir: str | Path, branch_name: str) -> None:
    """Create and checkout a branch.

    If the branch already exists on the remote (e.g. a prior pipeline stage
    pushed to it), fetch and check it out so work continues on the same branch.
    Otherwise create a fresh branch from current HEAD.
    """
    _, ls_output = await _run_git(
        ["git", "ls-remote", "--heads", "origin", branch_name],
        cwd=repo_dir,
    )
    if ls_output.strip():
        await _run_git(["git", "fetch", "origin", branch_name], cwd=repo_dir)
        await _run_git(
            ["git", "checkout", "-B", branch_name, f"origin/{branch_name}"],
            cwd=repo_dir,
        )
        logger.info("Checked out existing remote branch %s in %s", branch_name, repo_dir)
    else:
        await _run_git(["git", "checkout", "-B", branch_name], cwd=repo_dir)
        logger.info("Created new branch %s in %s", branch_name, repo_dir)
