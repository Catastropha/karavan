"""Karavan — FastAPI application entry point with lifespan management."""

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

# Global registry reference for access in other modules
registry = AgentRegistry()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle — startup and shutdown."""
    # --- Startup ---
    logger.info("Starting Karavan...")

    # 1. Start shared HTTP clients
    await res.startup()

    # 2. Load and start agents
    registry.load_from_config()

    # Wire up orchestrator queue to bot route
    orchestrator = registry.orchestrator
    if orchestrator:
        set_orchestrator_queue(orchestrator.queue)

    # Wire up agent registry to hook route
    set_agent_registry(registry)

    await registry.start_all()

    # 3. Register Trello webhooks (deduplicate — clean stale, skip existing)
    webhook_base = settings.webhook_base_url

    # Build desired webhook specs: {(model_id, callback_url): description}
    desired: dict[tuple[str, str], str] = {}
    for name, worker in registry.workers.items():
        callback_url = f"{webhook_base}/webhook/{name}"
        desired[(worker.config.lists.todo, callback_url)] = f"karavan-worker-{name}"
    if orchestrator:
        callback_url = f"{webhook_base}/webhook/{orchestrator.name}"
        for board_name, board in settings.boards.items():
            desired[(board.board_id, callback_url)] = f"karavan-board-{board_name}"

    # Fetch existing webhooks and reconcile
    try:
        existing = await get_token_webhooks()
    except Exception:
        logger.exception("Failed to list existing Trello webhooks, registering fresh")
        existing = []

    # Track which desired webhooks already exist
    already_registered: set[tuple[str, str]] = set()
    for wh in existing:
        key = (wh.id_model, wh.callback_url)
        if key in desired:
            # Exact match exists — keep it
            already_registered.add(key)
        elif wh.description.startswith("karavan-"):
            # Stale karavan webhook (old URL or removed agent) — delete it
            try:
                await delete_webhook(wh.id)
                logger.info("Deleted stale webhook %s (%s)", wh.id, wh.description)
            except Exception:
                logger.warning("Failed to delete stale webhook %s", wh.id)

    # Register missing webhooks
    for key, description in desired.items():
        if key in already_registered:
            logger.info("Webhook already exists for %s, skipping", description)
            continue
        model_id, callback_url = key
        try:
            await register_webhook(
                model_id=model_id,
                callback_url=callback_url,
                description=description,
            )
        except Exception:
            logger.exception("Failed to register Trello webhook: %s", description)

    # 4. Register Telegram webhook
    try:
        await register_telegram_webhook()
    except Exception:
        logger.exception("Failed to register Telegram webhook")

    logger.info("Karavan started with %d agents", len(registry.agents))

    yield

    # --- Shutdown ---
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

# Include routers
app.include_router(bot_router)
app.include_router(hook_router)
