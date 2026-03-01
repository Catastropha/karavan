"""OrchestratorAgent — manages planning via Telegram, creates Trello cards, monitors done lists."""

import logging
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from app.apps.agent.base import BaseAgent
from app.apps.agent.tools import build_orchestrator_mcp_server
from app.apps.bot.crud.create import send_message, send_typing_action
from app.apps.bot.markdown import escape_markdown_v2
from app.apps.git_manager.crud.create import clone_repo
from app.apps.git_manager.crud.update import pull_dev
from app.common.model.input import BotMessage
from app.core.config import BASE_DIR, OrchestratorAgentConfig, settings

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """Orchestrator agent that bridges Telegram, Claude, and Trello.

    - Receives user messages from Telegram via BotMessage queue
    - Uses ClaudeSDKClient for persistent multi-turn conversation
    - Has read access to all repos
    - Creates Trello cards in workers' todo lists
    - Monitors done lists via board-level webhook
    """

    def __init__(self, name: str, config: OrchestratorAgentConfig) -> None:
        super().__init__(name)
        self.config = config
        self._client: ClaudeSDKClient | None = None
        self._repo_dirs: list[Path] = []

    def should_process_webhook(self, list_id: str) -> bool:
        """Process webhooks when a card enters any known done or failed list."""
        return list_id in settings.done_list_ids or list_id == settings.failed_list_id

    async def start(self) -> None:
        """Clone repos and start the Claude SDK client before the run loop."""
        # Clone all repos for read access
        for repo_url in self.config.repos:
            repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
            repo_dir = BASE_DIR / "repos" / "orchestrator" / repo_name
            await clone_repo(repo_url, repo_dir)
            try:
                await pull_dev(repo_dir)
            except Exception:
                logger.warning("Failed to pull dev for %s, using existing clone", repo_name)
            self._repo_dirs.append(repo_dir)

        # Build MCP server with Trello orchestration tools
        mcp_server = build_orchestrator_mcp_server()

        # Create Claude SDK client with read access to repos + Trello tools
        self._client = ClaudeSDKClient(options=ClaudeAgentOptions(
            add_dirs=[str(d) for d in self._repo_dirs],
            allowed_tools=[
                "Read", "Glob", "Grep",
                "list_workers", "create_trello_card", "get_card_status", "get_worker_cards",
            ],
            mcp_servers={"karavan": mcp_server},
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": self.config.system_prompt,
            },
            permission_mode="bypassPermissions",
            setting_sources=["project"],
        ))
        await self._client.__aenter__()
        logger.info("Orchestrator %s: Claude SDK client started with %d repos", self.name, len(self._repo_dirs))

        await super().start()

    async def stop(self) -> None:
        """Shut down the Claude SDK client."""
        await super().stop()
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
            logger.info("Orchestrator %s: Claude SDK client stopped", self.name)

    async def _process(self, item: object) -> None:
        """Process a queue item — BotMessage, done-list event, or failed-list event."""
        if isinstance(item, BotMessage):
            await self._handle_user_message(item)
        elif isinstance(item, dict) and item.get("action_type"):
            list_after_id = item.get("list_after_id", "")
            if list_after_id == settings.failed_list_id:
                await self._handle_failed_event(item)
            else:
                await self._handle_done_event(item)
        else:
            logger.warning("Orchestrator %s received unknown item type: %s", self.name, type(item))

    async def _handle_user_message(self, msg: BotMessage) -> None:
        """Process a user message from Telegram via Claude SDK."""
        if not self._client:
            logger.error("Orchestrator %s: Claude SDK client not initialized", self.name)
            return

        logger.info("Orchestrator %s processing message from user %d: %s", self.name, msg.user_id, msg.text[:50])

        # Send typing indicator
        await send_typing_action(msg.chat_id)

        try:
            # Pull latest from all repos before processing
            for repo_dir in self._repo_dirs:
                try:
                    await pull_dev(repo_dir)
                except Exception:
                    pass

            # Query Claude with the user's message
            await self._client.query(msg.text)
            response_text = ""
            async for message in self._client.receive_response():
                if hasattr(message, "result"):
                    result = message.result
                    response_text = getattr(result, "text", str(result))

            # Send response back via Telegram
            if response_text:
                escaped = escape_markdown_v2(response_text)
                # Telegram has a 4096 char limit per message
                for i in range(0, len(escaped), 4000):
                    chunk = escaped[i : i + 4000]
                    await send_message(msg.chat_id, chunk)
            else:
                await send_message(msg.chat_id, escape_markdown_v2("Done. No text response generated."))

        except Exception:
            logger.exception("Orchestrator %s failed to process message", self.name)
            try:
                await send_message(
                    msg.chat_id,
                    escape_markdown_v2("Sorry, something went wrong processing your request."),
                )
            except Exception:
                logger.exception("Failed to send error message to Telegram")

    async def _handle_done_event(self, event: dict) -> None:
        """Handle a card-moved-to-done webhook event — notify user via Telegram."""
        card_name = event.get("card_name", "Unknown card")
        card_id = event.get("card_id", "")
        logger.info("Orchestrator %s: card '%s' (%s) moved to done", self.name, card_name, card_id)

        # Notify all allowed users (single-user system, but iterate for safety)
        for user_id in settings.telegram_allowed_user_ids:
            try:
                text = escape_markdown_v2(f"Card completed: {card_name}")
                await send_message(user_id, text)
            except Exception:
                logger.exception("Failed to notify user %d about completed card", user_id)

    async def _handle_failed_event(self, event: dict) -> None:
        """Handle a card-moved-to-failed webhook event — notify user via Telegram."""
        card_name = event.get("card_name", "Unknown card")
        card_id = event.get("card_id", "")
        logger.info("Orchestrator %s: card '%s' (%s) moved to failed", self.name, card_name, card_id)

        for user_id in settings.telegram_allowed_user_ids:
            try:
                text = escape_markdown_v2(f"Card failed: {card_name} — agent produced no code changes.")
                await send_message(user_id, text)
            except Exception:
                logger.exception("Failed to notify user %d about failed card", user_id)
