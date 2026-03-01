"""Hook app input models — Trello webhook event filtering."""

from typing import Annotated

from pydantic import BaseModel, Field


class TrelloHookEvent(BaseModel):
    """Simplified Trello webhook event for agent routing."""

    action_type: Annotated[str, Field(description="Action type (e.g. updateCard)")]
    card_id: Annotated[str, Field(description="Card ID")]
    card_name: Annotated[str, Field(default="", description="Card name")]
    list_after_id: Annotated[str | None, Field(default=None, description="ID of the list the card moved to")]
    list_after_name: Annotated[str | None, Field(default=None, description="Name of the list the card moved to")]
