"""Trello CRUD utilities."""

from app.core.config import settings


def auth_params() -> dict[str, str]:
    """Return Trello auth query params."""
    return {"key": settings.trello_api_key, "token": settings.trello_token}
