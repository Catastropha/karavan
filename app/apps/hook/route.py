"""Trello webhook and health check routes."""

import logging

from fastapi import APIRouter, Request, Response

from app.apps.hook.model.output import WebhookPostOut
from app.apps.trello.model.input import TrelloWebhookPayload

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
async def health_check() -> dict[str, str]:
    """Basic health check endpoint."""
    return {"status": "ok"}
