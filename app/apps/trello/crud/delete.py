"""Trello delete operations — deregister webhooks."""

import logging

from app.core.config import settings
from app.core.resource import res

logger = logging.getLogger(__name__)


def _auth_params() -> dict[str, str]:
    """Return Trello auth query params."""
    return {"key": settings.trello_api_key, "token": settings.trello_token}


async def delete_webhook(webhook_id: str) -> None:
    """Delete a Trello webhook."""
    resp = await res.trello_client.delete(f"webhooks/{webhook_id}", params=_auth_params())
    resp.raise_for_status()
    logger.info("Deleted webhook %s", webhook_id)
