"""Agent status output models."""

from typing import Annotated

from pydantic import BaseModel, Field


class AgentStatusOut(BaseModel):
    """Agent status output."""

    name: Annotated[str, Field(description="Agent name")]
    type: Annotated[str, Field(description="Agent type (worker/orchestrator)")]
    running: Annotated[bool, Field(description="Whether the agent loop is running")]
    queue_size: Annotated[int, Field(description="Number of items in the agent's queue")]
