"""Trello update operations — move cards, add comments and labels."""

import logging

from app.apps.trello.model.output import CardOut
from app.core.config import settings
from app.core.resource import res

logger = logging.getLogger(__name__)


def _auth_params() -> dict[str, str]:
    """Return Trello auth query params."""
    return {"key": settings.trello_api_key, "token": settings.trello_token}


async def move_card(card_id: str, list_id: str) -> CardOut:
    """Move a card to a different list."""
    params = {**_auth_params(), "idList": list_id}
    resp = await res.trello_client.put(f"cards/{card_id}", params=params)
    resp.raise_for_status()
    logger.info("Moved card %s to list %s", card_id, list_id)
    return CardOut(**resp.json())


async def add_comment(card_id: str, text: str) -> dict:
    """Add a comment to a Trello card."""
    params = {**_auth_params(), "text": text}
    resp = await res.trello_client.post(f"cards/{card_id}/actions/comments", params=params)
    resp.raise_for_status()
    logger.info("Added comment to card %s", card_id)
    return resp.json()


async def add_label(card_id: str, label_id: str) -> None:
    """Add a label to a Trello card."""
    params = {**_auth_params(), "value": label_id}
    resp = await res.trello_client.post(f"cards/{card_id}/idLabels", params=params)
    resp.raise_for_status()
    logger.info("Added label %s to card %s", label_id, card_id)
