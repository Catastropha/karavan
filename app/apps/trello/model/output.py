"""Trello domain output models."""

from typing import Annotated

from pydantic import BaseModel, Field


class CardOut(BaseModel):
    """Trello card output."""

    id: Annotated[str, Field(description="Card ID")]
    name: Annotated[str, Field(description="Card title")]
    desc: Annotated[str, Field(default="", description="Card description")]
    url: Annotated[str, Field(default="", description="Card URL")]
    id_list: Annotated[str, Field(default="", description="Current list ID", alias="idList")]
    id_labels: Annotated[list[str], Field(default_factory=list, description="Label IDs on this card", alias="idLabels")]

    model_config = {"extra": "ignore", "populate_by_name": True}


class WebhookOut(BaseModel):
    """Trello webhook output."""

    id: Annotated[str, Field(description="Webhook ID")]
    description: Annotated[str, Field(default="", description="Webhook description")]
    callback_url: Annotated[str, Field(default="", description="Callback URL", alias="callbackURL")]
    id_model: Annotated[str, Field(default="", description="Model ID (board or list)", alias="idModel")]
    active: Annotated[bool, Field(default=True, description="Whether webhook is active")]

    model_config = {"extra": "ignore", "populate_by_name": True}
