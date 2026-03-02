"""Security utilities. Single-user system — minimal auth via Telegram secret and allowed user IDs."""

import base64
import hashlib
import hmac
import secrets


def verify_secret(provided: str, expected: str) -> bool:
    """Constant-time comparison of webhook secret."""
    return secrets.compare_digest(provided, expected)


def verify_trello_webhook(body: bytes, callback_url: str, api_secret: str, signature: str) -> bool:
    """Verify Trello webhook signature using HMAC-SHA1.

    Trello signs webhook payloads with: base64(HMAC-SHA1(apiSecret, body + callbackURL)).
    The signature is sent in the x-trello-webhook header.
    """
    computed = base64.b64encode(
        hmac.new(
            api_secret.encode("utf-8"),
            body + callback_url.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")
    return hmac.compare_digest(computed, signature)
