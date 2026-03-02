"""MarkdownV2 escaping utility for Telegram messages.

Converts standard markdown (as produced by LLMs) to Telegram's MarkdownV2 format.
Handles fenced code blocks, inline code, links, and bold text.
"""

import re

# Regex to match markdown constructs, ordered by priority.
# Fenced code blocks must match first to prevent inner content from being parsed.
_TOKEN_RE = re.compile(
    r"(?P<fenced>```(?:\w*)\n[\s\S]*?```)"
    r"|(?P<inline_code>`[^`\n]+?`)"
    r"|(?P<link>\[(?P<link_text>[^\]]+)\]\((?P<link_url>[^)]+)\))"
    r"|(?P<bold>\*\*(?P<bold_text>.+?)\*\*)",
)


def escape_markdown_v2(text: str) -> str:
    """Convert standard markdown to Telegram MarkdownV2.

    Handles fenced code blocks, inline code, links, and bold.
    All other text has MarkdownV2 special characters escaped.
    """
    result: list[str] = []
    last_end = 0

    for match in _TOKEN_RE.finditer(text):
        start, end = match.span()

        # Escape plain text before this match
        if start > last_end:
            result.append(_escape_text(text[last_end:start]))

        if match.group("fenced"):
            result.append(_format_fenced_code(match.group("fenced")))
        elif match.group("inline_code"):
            code = match.group("inline_code")[1:-1]
            result.append(f"`{_escape_code(code)}`")
        elif match.group("link"):
            link_text = match.group("link_text")
            link_url = match.group("link_url")
            result.append(f"[{_escape_text(link_text)}]({_escape_link_url(link_url)})")
        elif match.group("bold"):
            bold_text = match.group("bold_text")
            result.append(f"*{_escape_text(bold_text)}*")

        last_end = end

    # Escape remaining plain text
    if last_end < len(text):
        result.append(_escape_text(text[last_end:]))

    return "".join(result)


def strip_markdown_v2(text: str) -> str:
    """Strip MarkdownV2 escaping to produce readable plain text for fallback."""
    return re.sub(r"\\(.)", r"\1", text)


def _escape_text(text: str) -> str:
    """Escape special characters for regular MarkdownV2 text."""
    return re.sub(r"([_*\[\]()~`>#\+\-=|{}.!\\])", r"\\\1", text)


def _escape_code(text: str) -> str:
    """Escape characters inside pre/code entities (only ` and \\)."""
    return text.replace("\\", "\\\\").replace("`", "\\`")


def _escape_link_url(url: str) -> str:
    """Escape characters inside a link URL (only ) and \\)."""
    return url.replace("\\", "\\\\").replace(")", "\\)")


def _format_fenced_code(raw: str) -> str:
    """Format a fenced code block for MarkdownV2."""
    inner = raw[3:-3]  # strip outer ```
    first_nl = inner.find("\n")
    if first_nl >= 0:
        lang = inner[:first_nl].strip()
        code = inner[first_nl + 1:]
    else:
        lang = ""
        code = inner
    if code.endswith("\n"):
        code = code[:-1]
    escaped = _escape_code(code)
    if lang:
        return f"```{lang}\n{escaped}\n```"
    return f"```\n{escaped}\n```"
