"""Trello webhook and health check routes."""

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

# Reusable OK response (every webhook return is identical)
_OK = WebhookPostOut()


def set_agent_registry(registry: AgentRegistry) -> None:
    """Set the agent registry for routing webhook events."""
    global _agent_registry
    _agent_registry = registry


@router.head("/webhook/{agent_name}")
async def trello_webhook_verify(agent_name: str) -> Response:
    """Trello sends HEAD to verify the webhook URL. Return 200."""
    return Response(status_code=200)


@router.post("/webhook/{agent_name}", response_model=WebhookPostOut)
async def trello_webhook(agent_name: str, request: Request) -> WebhookPostOut:
    """Receive Trello webhook events and route to the appropriate agent."""
    raw_body = await request.body()

    signature = request.headers.get("x-trello-webhook", "")
    if not signature or not verify_trello_webhook(
        body=raw_body,
        callback_url=f"{settings.webhook_base_url}/webhook/{agent_name}",
        api_secret=settings.trello_api_secret,
        signature=signature,
    ):
        logger.warning("Invalid Trello webhook signature for %s", agent_name)
        return _OK

    # Single-pass parse: validate JSON directly from raw bytes
    try:
        payload = TrelloWebhookPayload.model_validate_json(raw_body)
    except ValidationError:
        logger.warning("Failed to parse Trello webhook payload for %s", agent_name)
        return _OK

    card = payload.action.data.card
    list_after = payload.action.data.list_after
    if not card or not list_after:
        return _OK

    if _agent_registry is None:
        logger.error("Agent registry not set — dropping webhook event")
        return _OK

    agent = _agent_registry.get_agent(agent_name)
    if agent is None:
        logger.warning("No agent found for name '%s'", agent_name)
        return _OK

    if not agent.should_process_webhook(list_after.id):
        return _OK

    await agent.queue.put({
        "action_type": payload.action.type,
        "card_id": card.id,
        "card_name": card.name,
        "list_after_id": list_after.id,
    })
    logger.info(
        "Queued webhook event for %s: card '%s' moved to list %s",
        agent_name, card.name, list_after.name,
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
