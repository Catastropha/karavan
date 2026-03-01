"""Shared input models used across apps."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class BotMessage(BaseModel):
    """Normalized message from Telegram, shared between bot and agent apps."""

    tp: Annotated[Literal["telegram"], Field(default="telegram", description="Message source type")]
    chat_id: Annotated[int, Field(description="Telegram chat ID")]
    user_id: Annotated[int, Field(description="Telegram user ID")]
    username: Annotated[str, Field(default="", description="Telegram username")]
    text: Annotated[str, Field(min_length=1, description="Message text")]
    message_id: Annotated[int, Field(description="Telegram message ID")]
