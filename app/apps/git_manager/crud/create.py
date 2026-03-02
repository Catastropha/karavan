"""Git create operations — clone repos and create branches."""

import asyncio
import logging
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

GIT_SSH_COMMAND = f"ssh -i {settings.git_ssh_key_path} -o StrictHostKeyChecking=no"


async def _run_git(cmd: list[str], cwd: str | Path | None = None) -> str:
    """Run a git command via subprocess, return stdout."""
    env = {"GIT_SSH_COMMAND": GIT_SSH_COMMAND}
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**__import__("os").environ, **env},
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        error_msg = stderr.decode().strip()
        logger.error("Git command failed: %s -> %s", " ".join(cmd), error_msg)
        raise RuntimeError(f"Git command failed: {error_msg}")
    return stdout.decode().strip()


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
    """Create and checkout a branch, resetting it to HEAD if it already exists."""
    await _run_git(["git", "checkout", "-B", branch_name], cwd=repo_dir)
    logger.info("Created branch %s in %s", branch_name, repo_dir)
