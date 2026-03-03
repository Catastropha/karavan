"""Trello webhook and health check routes — board-level routing with label matching."""

import logging

from fastapi import APIRouter, Request, Response
from pydantic import ValidationError

from app.apps.agent.registry import AgentRegistry
from app.apps.hook.model.output import HealthGetOut, WebhookPostOut
from app.apps.trello.model.input import TrelloWebhookPayload
from app.common.cost import cost_tracker
from app.core.config import settings
from app.core.security import verify_trello_webhook

logger = logging.getLogger(__name__)

router = APIRouter(tags=["hook"])

# Agent registry reference — set during app startup
_agent_registry: AgentRegistry | None = None

# Label-to-worker lookup — built when registry is set
_label_to_worker: dict[str, str] = {}

# Reusable OK response (every webhook return is identical)
_OK = WebhookPostOut()


def set_agent_registry(registry: AgentRegistry) -> None:
    """Set the agent registry and build label lookup maps."""
    global _agent_registry
    _agent_registry = registry

    # Build label → worker_name lookup across all boards
    _label_to_worker.clear()
    for board in settings.boards.values():
        for worker_name, config in board.workers.items():
            _label_to_worker[config.label_id] = worker_name


@router.head("/webhook/{board_name}")
async def trello_webhook_verify(board_name: str) -> Response:
    """Trello sends HEAD to verify the webhook URL. Return 200."""
    return Response(status_code=200)


@router.post("/webhook/{board_name}", response_model=WebhookPostOut)
async def trello_webhook(board_name: str, request: Request) -> WebhookPostOut:
    """Receive Trello webhook events and route by label (workers) or list (orchestrator)."""
    raw_body = await request.body()

    signature = request.headers.get("x-trello-webhook", "")
    if not signature or not verify_trello_webhook(
        body=raw_body,
        callback_url=f"{settings.webhook_base_url}/webhook/{board_name}",
        api_secret=settings.trello_api_secret,
        signature=signature,
    ):
        logger.warning("Invalid Trello webhook signature for board %s", board_name)
        return _OK

    try:
        payload = TrelloWebhookPayload.model_validate_json(raw_body)
    except ValidationError:
        logger.warning("Failed to parse Trello webhook payload for board %s", board_name)
        return _OK

    if _agent_registry is None:
        logger.error("Agent registry not set — dropping webhook event")
        return _OK

    action_type = payload.action.type
    card = payload.action.data.card

    if not card:
        return _OK

    # Route addLabelToCard events to the matching worker
    if action_type == "addLabelToCard":
        label = payload.action.data.label
        if not label:
            return _OK

        worker_name = _label_to_worker.get(label.id)
        if not worker_name:
            return _OK

        agent = _agent_registry.get_agent(worker_name)
        if agent is None:
            logger.warning("No agent found for worker '%s' (label %s)", worker_name, label.id)
            return _OK

        await agent.queue.put({
            "action_type": "addLabelToCard",
            "card_id": card.id,
            "card_name": card.name,
            "label_id": label.id,
        })
        logger.info(
            "Queued label event for worker %s: card '%s' (label %s)",
            worker_name, card.name, label.id,
        )
        return _OK

    # Route updateCard (list moves) to orchestrator for done/failed tracking
    if action_type == "updateCard":
        list_after = payload.action.data.list_after
        if not list_after:
            return _OK

        orchestrator = _agent_registry.orchestrator
        if not orchestrator:
            return _OK

        if list_after.id in settings.done_list_ids or list_after.id in settings.all_failed_list_ids:
            await orchestrator.queue.put({
                "action_type": action_type,
                "card_id": card.id,
                "card_name": card.name,
                "list_after_id": list_after.id,
            })
            logger.info(
                "Queued done/failed event for orchestrator: card '%s' moved to list %s",
                card.name, list_after.name,
            )

    return _OK


@router.get("/health")
async def health_check() -> HealthGetOut:
    """Health check endpoint with agent status and cost tracking data."""
    agents = _agent_registry.get_all_status() if _agent_registry else {}
    data = {
        "agents": agents,
        "costs_by_agent": cost_tracker.get_summary(),
        "costs_total": cost_tracker.get_totals(),
    }
    return HealthGetOut.model_validate(data)
