"""Bot app output models."""

from typing import Annotated

from pydantic import BaseModel, Field


class HookTelegramPostOut(BaseModel):
    """Response for Telegram webhook POST."""

    ok: Annotated[bool, Field(default=True, description="Always true to acknowledge receipt")]
