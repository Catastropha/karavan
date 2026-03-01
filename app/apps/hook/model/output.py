"""Hook app output models."""

from typing import Annotated

from pydantic import BaseModel, Field


class WebhookPostOut(BaseModel):
    """Response for Trello webhook POST."""

    ok: Annotated[bool, Field(default=True, description="Acknowledged")]
