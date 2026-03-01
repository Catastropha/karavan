"""Trello delete operations — deregister webhooks."""

import logging

from app.apps.trello.crud import auth_params
from app.core.resource import res

logger = logging.getLogger(__name__)


async def delete_webhook(webhook_id: str) -> None:
    """Delete a Trello webhook."""
    resp = await res.trello_client.delete(f"webhooks/{webhook_id}", params=auth_params())
    resp.raise_for_status()
    logger.info("Deleted webhook %s", webhook_id)
