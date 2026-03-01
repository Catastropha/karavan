"""Git update operations — pull, commit, push, and create PRs."""

import asyncio
import logging
from pathlib import Path

from app.apps.git_manager.crud.create import _run_git
from app.apps.git_manager.model.input import PRCreateIn
from app.apps.git_manager.model.output import PROut
from app.core.resource import res

logger = logging.getLogger(__name__)


async def pull_dev(repo_dir: str | Path) -> None:
    """Checkout dev and pull latest changes."""
    await _run_git(["git", "checkout", "dev"], cwd=repo_dir)
    await _run_git(["git", "pull", "origin", "dev"], cwd=repo_dir)
    logger.info("Pulled dev in %s", repo_dir)


async def commit_and_push(repo_dir: str | Path, branch_name: str, message: str) -> None:
    """Stage all changes, commit, and push to remote."""
    await _run_git(["git", "add", "-A"], cwd=repo_dir)

    # Check if there are changes to commit
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--cached", "--quiet",
        cwd=str(repo_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode == 0:
        logger.info("No changes to commit in %s", repo_dir)
        return

    await _run_git(["git", "commit", "-m", message], cwd=repo_dir)
    await _run_git(["git", "push", "-u", "origin", branch_name], cwd=repo_dir)
    logger.info("Committed and pushed %s in %s", branch_name, repo_dir)


async def create_pr(pr_in: PRCreateIn) -> PROut:
    """Create a GitHub pull request via API."""
    resp = await res.github_client.post(
        f"repos/{pr_in.owner}/{pr_in.repo}/pulls",
        json={
            "title": pr_in.title,
            "body": pr_in.body,
            "head": pr_in.head,
            "base": pr_in.base,
        },
    )
    resp.raise_for_status()
    logger.info("Created PR #%s for %s/%s", resp.json()["number"], pr_in.owner, pr_in.repo)
    return PROut(**resp.json())
