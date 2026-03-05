"""Karavan — FastAPI application entry point with lifespan management."""

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from app.apps.agent.registry import AgentRegistry
from app.apps.bot.crud.create import register_telegram_webhook
from app.apps.bot.route import router as bot_router, set_orchestrator_queue
from app.apps.hook.route import router as hook_router, set_agent_registry
from app.apps.trello.crud.create import register_webhook
from app.apps.trello.crud.delete import delete_webhook
from app.apps.trello.crud.read import get_token_webhooks
from app.core.config import settings
from app.core.middleware import setup_middleware
from app.core.resource import res

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _reconcile_trello_webhooks(registry: AgentRegistry) -> None:
    """Register Trello webhooks, deduplicating and cleaning stale ones."""
    webhook_base = settings.webhook_base_url

    # One board-level webhook per board — handles both worker and orchestrator events
    desired: list[dict] = []
    for board_name, board in settings.boards.items():
        desired.append({
            "model_id": board.board_id,
            "callback_url": f"{webhook_base}/webhook/{board_name}",
            "description": f"karavan-board-{board_name}",
        })

    # Fetch existing webhooks and reconcile
    try:
        existing = await get_token_webhooks()
    except Exception:
        logger.exception("Failed to list existing Trello webhooks, registering fresh")
        existing = []

    # Track which desired webhooks already exist (by model_id + callback_url)
    registered_keys: set[str] = set()
    for wh in existing:
        match_key = f"{wh.id_model}|{wh.callback_url}"
        is_desired = any(
            wh.id_model == d["model_id"] and wh.callback_url == d["callback_url"]
            for d in desired
        )
        if is_desired:
            registered_keys.add(match_key)
        elif wh.description.startswith("karavan-"):
            try:
                await delete_webhook(wh.id)
                logger.info("Deleted stale webhook %s (%s)", wh.id, wh.description)
            except Exception:
                logger.warning("Failed to delete stale webhook %s", wh.id)

    # Register missing webhooks
    for webhook in desired:
        match_key = f"{webhook['model_id']}|{webhook['callback_url']}"
        if match_key in registered_keys:
            logger.info("Webhook already exists for %s, skipping", webhook["description"])
            continue
        try:
            await register_webhook(
                model_id=webhook["model_id"],
                callback_url=webhook["callback_url"],
                description=webhook["description"],
            )
        except Exception:
            logger.exception("Failed to register Trello webhook: %s", webhook["description"])


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle — startup and shutdown."""
    logger.info("Starting Karavan...")

    await res.startup()

    registry = AgentRegistry()
    registry.load_from_config()

    orchestrator = registry.orchestrator
    if orchestrator:
        set_orchestrator_queue(orchestrator.queue)
    set_agent_registry(registry)

    await registry.start_all()

    logger.info("Karavan started with %d agents", len(registry.agents))

    async def _register_webhooks_after_startup() -> None:
        """Wait for uvicorn to start serving, then register external webhooks."""
        await asyncio.sleep(2)
        await _reconcile_trello_webhooks(registry)
        try:
            await register_telegram_webhook()
        except Exception:
            logger.exception("Failed to register Telegram webhook")

    webhook_task = asyncio.create_task(_register_webhooks_after_startup())

    yield

    webhook_task.cancel()

    logger.info("Shutting down Karavan...")
    await registry.stop_all()
    await res.shutdown()
    logger.info("Karavan shut down")


app = FastAPI(
    title="Karavan",
    description="AI coding agent orchestration via Trello",
    version="0.1.0",
    lifespan=lifespan,
)

setup_middleware(app)

app.include_router(bot_router)
app.include_router(hook_router)
