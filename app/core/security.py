"""Security utilities. Single-user system — minimal auth via Telegram secret and allowed user IDs."""

import secrets


def verify_secret(provided: str, expected: str) -> bool:
    """Constant-time comparison of webhook secret."""
    return secrets.compare_digest(provided, expected)
