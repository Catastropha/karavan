"""MarkdownV2 escaping utility for Telegram messages."""

import re

# Characters that must be escaped in Telegram MarkdownV2
_SPECIAL_CHARS = r"_[]()~`>#+-=|{}.!"


def escape_markdown_v2(text: str) -> str:
    """Escape text for Telegram MarkdownV2, preserving **bold** as *bold*.

    Splits on **bold** markers, converts to Telegram's *bold* syntax,
    and escapes all special characters in the non-bold parts.
    """
    parts = re.split(r"\*\*(.+?)\*\*", text)
    result: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Regular text — escape special chars
            result.append(_escape_chars(part))
        else:
            # Bold text — wrap in single *, escape inside
            result.append(f"*{_escape_chars(part)}*")
    return "".join(result)


def _escape_chars(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
    return re.sub(r"([" + re.escape(_SPECIAL_CHARS) + r"])", r"\\\1", text)
