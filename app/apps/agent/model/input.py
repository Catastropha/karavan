"""Agent configuration input models."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class AgentStatusIn(BaseModel):
    """Input for querying agent status."""

    agent_name: Annotated[str, Field(min_length=1, description="Agent name")]
