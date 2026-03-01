"""Git read operations — check repo state."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def repo_exists(repo_dir: str | Path) -> bool:
    """Check if a cloned repo exists at the given path."""
    path = Path(repo_dir)
    exists = path.exists() and (path / ".git").exists()
    logger.debug("Repo exists at %s: %s", path, exists)
    return exists
