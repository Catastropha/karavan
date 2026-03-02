"""Trello domain input models — webhook payloads and card creation inputs."""

from typing import Annotated

from pydantic import BaseModel, Field


# --- Webhook payload models ---


class TrelloList(BaseModel):
    """List reference in a Trello webhook action."""

    id: Annotated[str, Field(description="List ID")]
    name: Annotated[str, Field(default="", description="List name")]

    model_config = {"extra": "ignore"}


class TrelloCardRef(BaseModel):
    """Card reference in a Trello webhook action."""

    id: Annotated[str, Field(description="Card ID")]
    name: Annotated[str, Field(default="", description="Card name")]

    model_config = {"extra": "ignore"}


class TrelloActionData(BaseModel):
    """Data payload within a Trello webhook action."""

    card: Annotated[TrelloCardRef | None, Field(default=None, description="Card reference")]
    list_after: Annotated[TrelloList | None, Field(default=None, description="New list", alias="listAfter")]

    model_config = {"extra": "ignore", "populate_by_name": True}


class TrelloAction(BaseModel):
    """A single Trello webhook action."""

    type: Annotated[str, Field(description="Action type (e.g. updateCard)")]
    data: Annotated[TrelloActionData, Field(description="Action data")]

    model_config = {"extra": "ignore"}


class TrelloWebhookPayload(BaseModel):
    """Full Trello webhook POST payload."""

    action: Annotated[TrelloAction, Field(description="The action that triggered the webhook")]

    model_config = {"extra": "ignore"}


# --- Card creation input ---


class CardCreateIn(BaseModel):
    """Input for creating a Trello card."""

    name: Annotated[str, Field(min_length=1, max_length=255, description="Card title")]
    desc: Annotated[str, Field(default="", max_length=16384, description="Card description in markdown")]
    id_list: Annotated[str, Field(min_length=1, description="Target Trello list ID", alias="idList")]
    id_labels: Annotated[list[str], Field(default_factory=list, description="Label IDs", alias="idLabels")]

    model_config = {"populate_by_name": True}
