"""Real-time worker progress feedback via Telegram edit-in-place messages."""

import asyncio
import logging
import re
import time
from collections import deque
from typing import Any

from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock

from app.apps.bot.crud.create import send_message
from app.apps.bot.crud.update import edit_message
from app.core.config import settings

logger = logging.getLogger(__name__)

FLUSH_INTERVAL: float = 5.0
MIN_EDIT_GAP: float = 10.0
MAX_ACTIVITIES: int = 5


_TOOL_DESCRIPTIONS: dict[str, tuple[str, str, str]] = {
    # tool_name: (input_key, label_with_value, label_without_value)
    "Read":  ("file_path", "Reading {}",         "Reading file"),
    "Write": ("file_path", "Writing {}",         "Writing file"),
    "Edit":  ("file_path", "Editing {}",         "Editing file"),
    "Glob":  ("pattern",   "Searching files: {}", "Searching files"),
    "Grep":  ("pattern",   "Searching for: {}",  "Searching content"),
}


def _describe_tool_use(block: ToolUseBlock) -> str | None:
    """Convert a ToolUseBlock into a human-readable one-liner."""
    inp: dict[str, Any] = block.input or {}

    if block.name == "Bash":
        cmd = inp.get("command", "")
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        return f"Running: {cmd}" if cmd else "Running command"

    desc = _TOOL_DESCRIPTIONS.get(block.name)
    if desc:
        key, with_val, without_val = desc
        value = inp.get(key, "")
        return with_val.format(_short_path(value)) if value else without_val

    return f"Using {block.name}"


def _short_path(path: str) -> str:
    """Shorten an absolute path to the last 2-3 components."""
    parts = path.replace("\\", "/").split("/")
    if len(parts) > 3:
        return "/".join(parts[-3:])
    return path


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as Xm Ys."""
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _escape_md(text: str) -> str:
    """Escape MarkdownV2 special characters in plain text."""
    return re.sub(r"([_*\[\]()~`>#\+\-=|{}.!\\])", r"\\\1", text)


class ProgressTracker:
    """Manages a single edit-in-place Telegram message for worker progress.

    All Telegram failures are swallowed — worker execution is never affected.
    """

    def __init__(self, worker_name: str, card_name: str) -> None:
        self._worker_name = worker_name
        self._card_name = card_name
        self._messages: dict[int, int] = {}  # chat_id -> message_id
        self._activities: deque[str] = deque(maxlen=MAX_ACTIVITIES)
        self._dirty = False
        self._last_edit_at: float = 0.0
        self._started_at: float = 0.0
        self._flush_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Send the initial progress message to all allowed users."""
        self._started_at = time.monotonic()
        text = self._render("Starting...")

        for user_id in settings.telegram_allowed_user_ids:
            try:
                resp = await send_message(user_id, text)
                msg_id = resp.get("result", {}).get("message_id")
                if msg_id:
                    self._messages[user_id] = msg_id
            except Exception:
                logger.debug("Progress: failed to send initial message to user %d", user_id, exc_info=True)

        if self._messages:
            self._flush_task = asyncio.create_task(self._flush_loop())

    def record_activity(self, message: object) -> None:
        """Record activity from an SDK message. Call for every yielded message."""
        if not isinstance(message, AssistantMessage):
            return

        for block in message.content:
            desc: str | None = None

            if isinstance(block, ToolUseBlock):
                desc = _describe_tool_use(block)
            elif isinstance(block, TextBlock) and block.text.strip():
                first_line = block.text.strip().splitlines()[0]
                if len(first_line) > 80:
                    first_line = first_line[:77] + "..."
                desc = f"Thinking: {first_line}"

            if desc and (not self._activities or self._activities[-1] != desc):
                self._activities.append(desc)
                self._dirty = True

    async def finish(
        self,
        success: bool,
        pr_url: str = "",
        cost_usd: float | None = None,
        error: str = "",
    ) -> None:
        """Send the final edit with terminal status and cancel the flush loop."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        if not self._messages:
            return

        if success:
            parts = ["Done"]
            if pr_url:
                parts.append(f"PR: {pr_url}")
            if cost_usd is not None:
                parts.append(f"Cost: ${cost_usd:.4f}")
            status = " | ".join(parts)
        else:
            status = f"Failed: {error}" if error else "Failed"

        text = self._render(status)
        await self._edit_all(text)

    async def _flush_loop(self) -> None:
        """Background loop that edits progress messages periodically."""
        try:
            while True:
                await asyncio.sleep(FLUSH_INTERVAL)
                if not self._dirty:
                    continue
                now = time.monotonic()
                if now - self._last_edit_at < MIN_EDIT_GAP:
                    continue
                status = self._activities[-1] if self._activities else "Working..."
                text = self._render(status)
                await self._edit_all(text)
                self._dirty = False
                self._last_edit_at = now
        except asyncio.CancelledError:
            return

    def _render(self, status: str) -> str:
        """Render the progress message in MarkdownV2 format.

        All plain text is escaped for MarkdownV2. Only the bold markers for the
        worker name are added as actual formatting.
        """
        elapsed = _format_elapsed(time.monotonic() - self._started_at) if self._started_at else "0s"

        lines = [
            f"*{_escape_md(self._worker_name)}* \\| {_escape_md(self._card_name)}",
            f"Status: {_escape_md(status)}",
            f"Elapsed: {_escape_md(elapsed)}",
        ]

        if self._activities:
            lines.append("")
            for activity in self._activities:
                lines.append(f"\\- {_escape_md(activity)}")

        return "\n".join(lines)

    async def _edit_all(self, text: str) -> None:
        """Edit the progress message for all users, swallowing errors."""
        for chat_id, message_id in self._messages.items():
            try:
                await edit_message(chat_id, message_id, text)
            except Exception:
                logger.debug(
                    "Progress: failed to edit message %d in chat %d",
                    message_id, chat_id, exc_info=True,
                )
