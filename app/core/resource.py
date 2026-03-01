"""Shared resources — httpx async client singletons for Trello, Telegram, and GitHub APIs."""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class Resources:
    """Manages shared httpx.AsyncClient instances with proper lifecycle."""

    def __init__(self) -> None:
        self.trello_client: httpx.AsyncClient | None = None
        self.telegram_client: httpx.AsyncClient | None = None
        self.github_client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        """Create all httpx client singletons."""
        self.trello_client = httpx.AsyncClient(
            base_url="https://api.trello.com/1/",
            timeout=30.0,
        )
        self.telegram_client = httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{settings.telegram_bot_token}/",
            timeout=30.0,
        )
        self.github_client = httpx.AsyncClient(
            base_url="https://api.github.com/",
            headers={
                "Authorization": f"token {settings.github_token}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=30.0,
        )
        logger.info("Resources started: Trello, Telegram, GitHub clients created")

    async def shutdown(self) -> None:
        """Close all httpx clients."""
        for name, client in [
            ("trello", self.trello_client),
            ("telegram", self.telegram_client),
            ("github", self.github_client),
        ]:
            if client:
                await client.aclose()
                logger.info("Closed %s client", name)


res = Resources()
