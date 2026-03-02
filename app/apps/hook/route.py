"""Trello webhook and health check routes."""

import logging

from fastapi import APIRouter, Request, Response

from app.apps.hook.model.output import HealthGetOut, WebhookPostOut
from app.apps.trello.model.input import TrelloWebhookPayload
from app.common.cost import cost_tracker
from app.core.config import settings
from app.core.security import verify_trello_webhook

logger = logging.getLogger(__name__)

router = APIRouter(tags=["hook"])

# Agent registry reference — set during app startup
_agent_registry = None


def set_agent_registry(registry: object) -> None:
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
    # Verify Trello webhook signature
    signature = request.headers.get("x-trello-webhook", "")
    raw_body = await request.body()
    callback_url = f"{settings.webhook_base_url}/webhook/{agent_name}"
    if not signature or not verify_trello_webhook(
        body=raw_body,
        callback_url=callback_url,
        api_secret=settings.trello_api_secret,
        signature=signature,
    ):
        logger.warning("Invalid Trello webhook signature for %s", agent_name)
        return WebhookPostOut()

    body = await request.json()
    try:
        payload = TrelloWebhookPayload(**body)
    except Exception:
        logger.warning("Failed to parse Trello webhook payload for %s", agent_name)
        return WebhookPostOut()

    action = payload.action
    list_after = action.data.list_after
    card = action.data.card

    if not card:
        return WebhookPostOut()

    if _agent_registry is None:
        logger.error("Agent registry not set — dropping webhook event")
        return WebhookPostOut()

    agent = _agent_registry.get_agent(agent_name)
    if agent is None:
        logger.warning("No agent found for name '%s'", agent_name)
        return WebhookPostOut()

    # Route the event based on agent type
    if list_after and card:
        should_process = agent.should_process_webhook(list_after.id)
        if should_process:
            await agent.queue.put({
                "action_type": action.type,
                "card_id": card.id,
                "card_name": card.name,
                "list_after_id": list_after.id,
            })
            logger.info(
                "Queued webhook event for %s: card '%s' moved to list %s",
                agent_name, card.name, list_after.name,
            )

    return WebhookPostOut()


@router.get("/health")
async def health_check() -> HealthGetOut:
    """Health check endpoint with agent status and cost tracking data."""
    agents = _agent_registry.get_all_status() if _agent_registry else {}
    return HealthGetOut(
        agents=agents,
        costs_by_agent=cost_tracker.get_summary(),
        costs_total=cost_tracker.get_totals(),
    )
