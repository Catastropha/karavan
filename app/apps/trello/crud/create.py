"""Trello create operations — create cards and register webhooks."""

import logging

from app.apps.trello.model.input import CardCreateIn
from app.apps.trello.model.output import CardOut, WebhookOut
from app.core.config import settings
from app.core.resource import res

logger = logging.getLogger(__name__)


def _auth_params() -> dict[str, str]:
    """Return Trello auth query params."""
    return {"key": settings.trello_api_key, "token": settings.trello_token}


async def create_card(card_in: CardCreateIn) -> CardOut:
    """Create a new Trello card."""
    params = {
        **_auth_params(),
        "name": card_in.name,
        "desc": card_in.desc,
        "idList": card_in.id_list,
    }
    if card_in.id_labels:
        params["idLabels"] = ",".join(card_in.id_labels)
    resp = await res.trello_client.post("cards", params=params)
    resp.raise_for_status()
    logger.info("Created card '%s' in list %s", card_in.name, card_in.id_list)
    return CardOut(**resp.json())


async def register_webhook(model_id: str, callback_url: str, description: str = "") -> WebhookOut:
    """Register a Trello webhook on a board or list."""
    params = {
        **_auth_params(),
        "callbackURL": callback_url,
        "idModel": model_id,
        "description": description,
    }
    resp = await res.trello_client.post("webhooks", params=params)
    resp.raise_for_status()
    logger.info("Registered webhook for model %s -> %s", model_id, callback_url)
    return WebhookOut(**resp.json())
