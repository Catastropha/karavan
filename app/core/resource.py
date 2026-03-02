"""Shared resources — httpx async client singletons for Trello, Telegram, and GitHub APIs."""

import asyncio
import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class RateLimitedTransport(httpx.AsyncBaseTransport):
    """Async httpx transport with sliding-window rate limiting and 429 retry."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport,
        *,
        max_requests: int = 90,
        window: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        self._transport = transport
        self._max_requests = max_requests
        self._window = window
        self._max_retries = max_retries
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def _acquire_capacity(self) -> None:
        """Block until there is capacity in the sliding rate-limit window."""
        while True:
            async with self._lock:
                now = time.monotonic()
                self._timestamps = [t for t in self._timestamps if now - t < self._window]
                if len(self._timestamps) < self._max_requests:
                    self._timestamps.append(now)
                    return
                wait_time = self._window - (now - self._timestamps[0]) + 0.1
            logger.debug("Trello rate limit capacity reached, waiting %.1fs", wait_time)
            await asyncio.sleep(wait_time)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Send request with proactive rate limiting and 429 retry with backoff."""
        for attempt in range(self._max_retries + 1):
            await self._acquire_capacity()
            response = await self._transport.handle_async_request(request)
            if response.status_code != 429:
                return response
            if attempt == self._max_retries:
                return response
            await response.aclose()
            backoff = 2 ** attempt
            retry_after = float(response.headers.get("retry-after", str(backoff)))
            logger.warning(
                "Trello 429 rate limited, retry %d/%d in %.1fs",
                attempt + 1, self._max_retries, retry_after,
            )
            await asyncio.sleep(retry_after)
        return response  # unreachable, satisfies type checker

    async def aclose(self) -> None:
        """Close the wrapped transport."""
        await self._transport.aclose()


class Resources:
    """Manages shared httpx.AsyncClient instances with proper lifecycle."""

    def __init__(self) -> None:
        self.trello_client: httpx.AsyncClient | None = None
        self.telegram_client: httpx.AsyncClient | None = None
        self.github_client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        """Create all httpx client singletons."""
        self.trello_client = httpx.AsyncClient(
            transport=RateLimitedTransport(httpx.AsyncHTTPTransport()),
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
