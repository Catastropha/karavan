"""Trello read operations — get cards and lists."""

import logging

from app.apps.trello.crud import auth_params
from app.apps.trello.model.output import CardOut, WebhookOut
from app.core.resource import res

logger = logging.getLogger(__name__)


async def get_card(card_id: str) -> CardOut:
    """Fetch a single Trello card by ID."""
    resp = await res.trello_client.get(f"cards/{card_id}", params=auth_params())
    resp.raise_for_status()
    return CardOut.model_validate(resp.json())


async def get_list_cards(list_id: str) -> list[CardOut]:
    """Fetch all cards in a Trello list."""
    resp = await res.trello_client.get(f"lists/{list_id}/cards", params=auth_params())
    resp.raise_for_status()
    return [CardOut.model_validate(c) for c in resp.json()]


async def get_card_actions(card_id: str, action_filter: str = "commentCard") -> list[dict]:
    """Fetch actions on a Trello card, filtered by type."""
    params = {**auth_params(), "filter": action_filter}
    resp = await res.trello_client.get(f"cards/{card_id}/actions", params=params)
    resp.raise_for_status()
    return resp.json()


async def get_token_webhooks() -> list[WebhookOut]:
    """Fetch all webhooks registered for the current Trello token."""
    params = auth_params()
    resp = await res.trello_client.get(f"tokens/{params['token']}/webhooks", params=params)
    resp.raise_for_status()
    return [WebhookOut.model_validate(w) for w in resp.json()]
