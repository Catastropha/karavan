"""Trello read operations — get cards and lists."""

import logging

from app.apps.trello.crud import auth_params
from app.apps.trello.model.output import CardOut, ListOut
from app.core.resource import res

logger = logging.getLogger(__name__)


async def get_card(card_id: str) -> CardOut:
    """Fetch a single Trello card by ID."""
    resp = await res.trello_client.get(f"cards/{card_id}", params=auth_params())
    resp.raise_for_status()
    return CardOut(**resp.json())


async def get_list_cards(list_id: str) -> list[CardOut]:
    """Fetch all cards in a Trello list."""
    resp = await res.trello_client.get(f"lists/{list_id}/cards", params=auth_params())
    resp.raise_for_status()
    return [CardOut(**c) for c in resp.json()]


async def get_board_lists(board_id: str) -> list[ListOut]:
    """Fetch all lists on a Trello board."""
    resp = await res.trello_client.get(f"boards/{board_id}/lists", params=auth_params())
    resp.raise_for_status()
    return [ListOut(**lst) for lst in resp.json()]
