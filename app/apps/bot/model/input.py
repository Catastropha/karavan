"""Telegram webhook payload models."""

from typing import Annotated

from pydantic import BaseModel, Field


class TelegramUser(BaseModel):
    """Telegram user."""

    id: Annotated[int, Field(description="User ID")]
    is_bot: Annotated[bool, Field(default=False, description="Whether user is a bot")]
    first_name: Annotated[str, Field(default="", description="First name")]

    model_config = {"extra": "ignore"}


class TelegramChat(BaseModel):
    """Telegram chat."""

    id: Annotated[int, Field(description="Chat ID")]
    type: Annotated[str, Field(default="private", description="Chat type")]

    model_config = {"extra": "ignore"}


class TelegramMessage(BaseModel):
    """Telegram message."""

    message_id: Annotated[int, Field(description="Message ID")]
    from_: Annotated[TelegramUser | None, Field(default=None, alias="from", description="Sender")]
    chat: Annotated[TelegramChat, Field(description="Chat")]
    text: Annotated[str, Field(default="", min_length=0, max_length=4096, description="Message text")]
    date: Annotated[int, Field(default=0, description="Unix timestamp")]

    model_config = {"extra": "ignore", "populate_by_name": True}


class TelegramCallbackQuery(BaseModel):
    """Telegram inline keyboard callback."""

    id: Annotated[str, Field(description="Callback query ID")]
    from_: Annotated[TelegramUser, Field(alias="from", description="User who pressed the button")]
    message: Annotated[TelegramMessage | None, Field(default=None, description="Original message")]
    data: Annotated[str, Field(default="", description="Callback data")]

    model_config = {"extra": "ignore", "populate_by_name": True}


class TelegramUpdate(BaseModel):
    """Telegram webhook update payload."""

    update_id: Annotated[int, Field(description="Update ID")]
    message: Annotated[TelegramMessage | None, Field(default=None, description="New message")]
    callback_query: Annotated[TelegramCallbackQuery | None, Field(default=None, description="Callback query")]

    model_config = {"extra": "ignore"}
