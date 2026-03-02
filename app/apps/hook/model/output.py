"""Hook app output models."""

from typing import Annotated, Any

from pydantic import BaseModel, Field


class WebhookPostOut(BaseModel):
    """Response for Trello webhook POST."""

    ok: Annotated[bool, Field(default=True, description="Acknowledged")]


class HealthGetOut(BaseModel):
    """Response for health check endpoint."""

    status: Annotated[str, Field(default="ok", description="Service status")]
    costs_by_agent: Annotated[
        dict[str, dict[str, Any]],
        Field(default_factory=dict, description="Cost breakdown per agent"),
    ]
    costs_total: Annotated[
        dict[str, Any],
        Field(default_factory=dict, description="Aggregate cost totals"),
    ]
