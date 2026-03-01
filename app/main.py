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

    # 3. Register Trello webhooks
    webhook_base = settings.webhook_base_url
    for name, worker in registry.workers.items():
        try:
            callback_url = f"{webhook_base}/webhook/{name}"
            await register_webhook(
                model_id=worker.config.lists.todo,
                callback_url=callback_url,
                description=f"karavan-worker-{name}",
            )
        except Exception:
            logger.exception("Failed to register Trello webhook for worker %s", name)

    if orchestrator:
        try:
            callback_url = f"{webhook_base}/webhook/{orchestrator.name}"
            await register_webhook(
                model_id=orchestrator.config.board_id,
                callback_url=callback_url,
                description=f"karavan-orchestrator-{orchestrator.name}",
            )
        except Exception:
            logger.exception("Failed to register Trello webhook for orchestrator")

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
