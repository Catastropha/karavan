"""Hook app output models."""

from typing import Annotated, Any

from pydantic import BaseModel, Field


class WebhookPostOut(BaseModel):
    """Response for Trello webhook POST."""

    ok: Annotated[bool, Field(default=True, description="Acknowledged")]


class AgentStatusOut(BaseModel):
    """Status of a single agent."""

    running: Annotated[bool, Field(description="Whether the agent loop is running")]
    queue_depth: Annotated[int, Field(description="Number of items in the agent's queue")]
    last_activity_at: Annotated[float, Field(description="Unix timestamp of last processed item (0 if never)")]
    cards_processed: Annotated[int, Field(description="Total cards successfully processed")]


class HealthGetOut(BaseModel):
    """Response for health check endpoint."""

    status: Annotated[str, Field(default="ok", description="Service status")]
    agents: Annotated[
        dict[str, AgentStatusOut],
        Field(default_factory=dict, description="Per-agent status"),
    ]
    costs_by_agent: Annotated[
        dict[str, dict[str, Any]],
        Field(default_factory=dict, description="Cost breakdown per agent"),
    ]
    costs_total: Annotated[
        dict[str, Any],
        Field(default_factory=dict, description="Aggregate cost totals"),
    ]
