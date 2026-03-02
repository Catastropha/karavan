"""Git manager input models."""

from typing import Annotated

from pydantic import BaseModel, Field


class PRCreateIn(BaseModel):
    """Input for creating a GitHub pull request."""

    owner: Annotated[str, Field(min_length=1, description="Repository owner")]
    repo: Annotated[str, Field(min_length=1, description="Repository name")]
    title: Annotated[str, Field(min_length=1, max_length=255, description="PR title")]
    body: Annotated[str, Field(default="", description="PR body in markdown")]
    head: Annotated[str, Field(min_length=1, description="Branch with changes")]
    base: Annotated[str, Field(default="main", description="Target branch")]
