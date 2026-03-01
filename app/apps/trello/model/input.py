"""Trello domain input models — webhook payloads and card creation inputs."""

from typing import Annotated

from pydantic import BaseModel, Field


# --- Webhook payload models ---


class TrelloBoard(BaseModel):
    """Board reference in a Trello webhook action."""

    id: Annotated[str, Field(description="Board ID")]
    name: Annotated[str, Field(default="", description="Board name")]

    model_config = {"extra": "ignore"}


class TrelloList(BaseModel):
    """List reference in a Trello webhook action."""

    id: Annotated[str, Field(description="List ID")]
    name: Annotated[str, Field(default="", description="List name")]

    model_config = {"extra": "ignore"}


class TrelloCardRef(BaseModel):
    """Card reference in a Trello webhook action."""

    id: Annotated[str, Field(description="Card ID")]
    name: Annotated[str, Field(default="", description="Card name")]
    short_link: Annotated[str, Field(default="", description="Short link", alias="shortLink")]

    model_config = {"extra": "ignore", "populate_by_name": True}


class TrelloActionData(BaseModel):
    """Data payload within a Trello webhook action."""

    board: Annotated[TrelloBoard | None, Field(default=None, description="Board reference")]
    card: Annotated[TrelloCardRef | None, Field(default=None, description="Card reference")]
    list: Annotated[TrelloList | None, Field(default=None, description="List reference")]
    list_before: Annotated[TrelloList | None, Field(default=None, description="Previous list", alias="listBefore")]
    list_after: Annotated[TrelloList | None, Field(default=None, description="New list", alias="listAfter")]

    model_config = {"extra": "ignore", "populate_by_name": True}


class TrelloMember(BaseModel):
    """Member who performed the action."""

    id: Annotated[str, Field(description="Member ID")]
    username: Annotated[str, Field(default="", description="Username")]

    model_config = {"extra": "ignore"}


class TrelloAction(BaseModel):
    """A single Trello webhook action."""

    id: Annotated[str, Field(description="Action ID")]
    type: Annotated[str, Field(description="Action type (e.g. updateCard)")]
    data: Annotated[TrelloActionData, Field(description="Action data")]
    member_creator: Annotated[TrelloMember | None, Field(default=None, description="Who did it", alias="memberCreator")]

    model_config = {"extra": "ignore", "populate_by_name": True}


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
