"""Trello update operations — update cards and add comments."""

import logging

from app.apps.trello.crud import auth_params
from app.apps.trello.model.output import CardOut
from app.core.resource import res

logger = logging.getLogger(__name__)


async def update_card(card_id: str, *, id_list: str = "", desc: str | None = None) -> CardOut:
    """Update a card's list and/or description (single PUT)."""
    params = auth_params()
    if id_list:
        params["idList"] = id_list
    if desc is not None:
        params["desc"] = desc
    resp = await res.trello_client.put(f"cards/{card_id}", params=params)
    resp.raise_for_status()
    logger.info("Updated card %s", card_id)
    return CardOut.model_validate(resp.json())


async def add_comment(card_id: str, text: str) -> dict:
    """Add a comment to a Trello card."""
    params = {**auth_params(), "text": text}
    resp = await res.trello_client.post(f"cards/{card_id}/actions/comments", params=params)
    resp.raise_for_status()
    logger.info("Added comment to card %s", card_id)
    return resp.json()
