"""Git manager output models."""

from typing import Annotated

from pydantic import BaseModel, Field


class PROut(BaseModel):
    """GitHub pull request output."""

    number: Annotated[int, Field(description="PR number")]
    html_url: Annotated[str, Field(description="PR URL")]
    title: Annotated[str, Field(description="PR title")]
    state: Annotated[str, Field(default="open", description="PR state")]

    model_config = {"extra": "ignore"}
