"""WorkerAgent — picks up Trello cards and executes them based on configurable behavior axes."""

import asyncio
import logging
import os
import re
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from app.apps.agent.base import BaseAgent
from app.apps.agent.tools import MCP_TOOL_NAMES, build_mcp_server, build_worker_mcp_server, get_routing_decision
from app.apps.git_manager.crud.create import clone_repo, create_branch
from app.apps.git_manager.crud.update import commit_and_push, create_pr, pull_base
from app.apps.git_manager.model.input import PRCreateIn
from app.apps.trello.crud.read import get_card, get_card_actions, get_list_cards
from app.apps.trello.crud.update import add_comment, add_label, remove_label, update_card
from app.common.cost import cost_tracker
from app.common.progress import ProgressTracker
from app.core.config import BASE_DIR, BoardConfig, WorkerAgentConfig, settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
FAIL_PREFIX = "[karavan:fail]"
BOUNCE_PREFIX = "[karavan:bounce]"
OUTPUT_PREFIX = "[karavan:output:"
OUTPUT_MAX_CHARS = 16000  # safe limit under Trello's 16384 per comment


def _parse_repo_url(repo_url: str) -> tuple[str, str]:
    """Extract owner/repo from a git SSH URL like git@github.com:user/repo.git."""
    match = re.match(r"git@github\.com:(.+?)/(.+?)(?:\.git)?$", repo_url)
    if not match:
        raise ValueError(f"Cannot parse repo URL: {repo_url}")
    return match.group(1), match.group(2)


class WorkerAgent(BaseAgent):
    """Worker agent that processes Trello cards via Claude Agent SDK.

    Behavior is driven by three config axes:
    - repo_access: write (clone+branch+commit), read (clone for context), none
    - output_mode: pr (code+PR), comment (card comment), cards (create sub-cards), update (rewrite description)
    - allowed_tools: which SDK tools are available to the agent
    """

    def __init__(self, name: str, config: WorkerAgentConfig, board: BoardConfig) -> None:
        super().__init__(name)
        self.config = config
        self.board = board
        self.repo_dir = BASE_DIR / "repos" / name
        self._processed_cards: set[str] = set()
        self._current_card_id: str | None = None

        if config.repo_access in ("write", "read") and config.repo:
            self.owner, self.repo_name = _parse_repo_url(config.repo)
        else:
            self.owner = ""
            self.repo_name = ""

    def get_status(self) -> dict[str, Any]:
        """Return worker status including current card being processed."""
        status = super().get_status()
        status["current_card_id"] = self._current_card_id
        return status

    async def start(self) -> None:
        """Start the worker, recovering any orphaned cards from a previous run."""
        await super().start()
        await self._recover_cards()

    async def _recover_cards(self) -> None:
        """Move own cards from doing back to todo and re-queue all own todo cards."""
        # Recover cards stuck in doing (from crash/restart)
        try:
            doing_cards = await get_list_cards(self.board.lists.doing)
        except Exception:
            logger.exception("Worker %s: failed to fetch doing list", self.name)
            doing_cards = []

        for card in doing_cards:
            if self.config.label_id not in card.id_labels:
                continue
            try:
                await update_card(card.id, id_list=self.board.lists.todo)
                logger.info("Worker %s: recovered card '%s' from doing to todo", self.name, card.name)
            except Exception:
                logger.exception("Worker %s: failed to recover card '%s'", self.name, card.id)

        # Re-queue all own cards in todo
        try:
            todo_cards = await get_list_cards(self.board.lists.todo)
        except Exception:
            logger.exception("Worker %s: failed to fetch todo list", self.name)
            todo_cards = []

        for card in todo_cards:
            if self.config.label_id not in card.id_labels:
                continue
            await self.queue.put({
                "action_type": "addLabelToCard",
                "card_id": card.id,
                "card_name": card.name,
                "label_id": self.config.label_id,
            })
            logger.info("Worker %s: re-queued card '%s' from todo", self.name, card.name)

    async def stop(self) -> None:
        """Stop the agent, moving any in-flight card back to todo for retry on restart."""
        card_id = self._current_card_id
        await super().stop()

        if card_id:
            logger.info("Worker %s: moving in-flight card %s back to todo on shutdown", self.name, card_id)
            try:
                await update_card(card_id, id_list=self.board.lists.todo)
                self._processed_cards.discard(card_id)
            except Exception:
                logger.exception(
                    "Worker %s: failed to move in-flight card %s back to todo",
                    self.name, card_id,
                )

    def should_process_webhook(self, list_id: str) -> bool:
        """Not used for label-based routing — hook handler routes by label directly."""
        return False

    async def _process(self, item: object) -> None:
        """Process a webhook event — pick up and execute a Trello card."""
        if not isinstance(item, dict):
            logger.warning("Worker %s received non-dict item: %s", self.name, type(item))
            return

        card_id = item.get("card_id")
        if not card_id:
            logger.warning("Worker %s received item without card_id", self.name)
            return

        if card_id in self._processed_cards:
            logger.debug("Worker %s skipping duplicate event for card %s", self.name, card_id)
            return

        await self._execute_card(card_id)

    async def _count_failures(self, card_id: str) -> int:
        """Count failure comments on a card by looking for the fail prefix."""
        actions = await get_card_actions(card_id)
        count = 0
        for action in actions:
            data = action.get("data", {})
            text = data.get("text", "")
            if text.startswith(FAIL_PREFIX):
                count += 1
        return count

    async def _count_bounces(self, card_id: str) -> int:
        """Count bounce comments on a card by looking for the bounce prefix."""
        actions = await get_card_actions(card_id)
        count = 0
        for action in actions:
            data = action.get("data", {})
            text = data.get("text", "")
            if text.startswith(BOUNCE_PREFIX):
                count += 1
        return count

    # --- Stage methods ---

    async def _setup_repo(self, branch_name: str) -> None:
        """Clone/pull repo and optionally create a branch based on repo_access."""
        if self.config.repo_access == "none":
            return

        await clone_repo(self.config.repo, self.repo_dir)
        await pull_base(self.repo_dir, self.config.base_branch)

        if self.config.repo_access == "write":
            await create_branch(self.repo_dir, branch_name)

    async def _get_output_comments(self, card_id: str) -> list[tuple[str, str]]:
        """Fetch agent output comments from a card, in chronological order.

        Returns (agent_name, text) tuples.
        """
        actions = await get_card_actions(card_id)
        outputs: list[tuple[str, str]] = []
        for action in reversed(actions):  # API returns newest first
            text = action.get("data", {}).get("text", "")
            if not text.startswith(OUTPUT_PREFIX):
                continue
            first_nl = text.find("\n")
            if first_nl == -1:
                continue
            header = text[:first_nl]
            if not header.endswith("]"):
                continue
            agent_name = header[len(OUTPUT_PREFIX):-1]
            body = text[first_nl + 1:]
            outputs.append((agent_name, body))
        return outputs

    async def _build_prompt(self, card: object, card_id: str, branch_name: str) -> str:
        """Build the SDK prompt based on output_mode and repo_access."""
        mode = self.config.output_mode
        parts: list[str] = [f"# Task: {card.name}\n"]

        # Intro — what is this agent's role?
        if mode == "pr":
            parts.append("You are a worker agent in the Karavan system. Your job is to **write code** that fulfills the task below.\n")
        elif mode == "comment":
            parts.append("You are a worker agent in the Karavan system. Your job is to **analyze the task below and provide a detailed written response**.\n")
        elif mode == "cards":
            parts.append(
                "You are a worker agent in the Karavan system. Your job is to **break down the task below into concrete, actionable sub-tasks** and create Trello cards for each using the available MCP tools.\n\n"
                "Use `list_boards` to discover available boards and their workers, then use `create_trello_card` to create cards.\n"
            )
        elif mode == "update":
            parts.append(
                "You are a worker agent in the Karavan system. Your job is to **analyze the task and produce your section of the card**.\n\n"
                "Your output will be posted as a comment on the card — do NOT repeat or rewrite previous agents' output.\n"
                "Your FINAL TEXT RESPONSE is what gets saved. Follow the exact format and word limits in your system prompt. Be dense and precise, not verbose.\n"
            )

        # Repo context (when applicable)
        if self.config.repo_access != "none" and self.owner:
            parts.append("## Environment")
            parts.append(f"- **Repository:** `{self.owner}/{self.repo_name}`")
            if self.config.repo_access == "write":
                parts.append(f"- **Working directory:** `{self.repo_dir}`")
                parts.append(f"- **Branch:** `{branch_name}` (already checked out)")
            else:
                parts.append(f"- **Directory:** `{self.repo_dir}` (read-only context)")
            parts.append("")

        # Rules — what to do and not do
        parts.append("## Rules")
        if mode == "pr":
            parts.append("- **DO** read existing code to understand patterns before making changes.")
            parts.append("- **DO** write clean, production-quality code that fits the existing codebase style.")
            parts.append("- **DO** create or modify tests if the project has a test suite.")
            parts.append("- **DO NOT** run any git commands (no `git add`, `git commit`, `git push`, `git checkout`, etc.). The harness handles all git operations after you finish.")
            parts.append("- **DO NOT** just explain what to do — actually write the code.")
            parts.append("- **DO NOT** modify files unrelated to this task.")
        elif mode == "comment":
            parts.append("- **DO** provide thorough, actionable analysis.")
            parts.append("- **DO** reference specific files and line numbers when relevant.")
            parts.append("- **DO NOT** modify any files — this is a read-only analysis task.")
        elif mode == "cards":
            parts.append("- **DO** use `list_boards` to find available boards before creating cards.")
            parts.append("- **DO** follow the card schema format (## Task, ## Context, ## Acceptance Criteria).")
            parts.append("- **DO** set dependencies between cards when order matters.")
            parts.append("- **DO NOT** modify any files — use only the MCP tools to create cards.")
        elif mode == "update":
            parts.append("- **DO** read the full card and prior agent output to understand context.")
            parts.append("- **DO** produce only YOUR section — do not repeat or rewrite previous agents' output.")
            parts.append("- **DO** include all required sections from your system prompt format.")
            parts.append("- **DO** respect the word limits specified in your system prompt — 1-2 sentences means 1-2 sentences, not more.")
            parts.append("- **DO NOT** pad your output. Be dense and evidence-rich, not verbose.")
            parts.append("- **DO NOT** modify any files.")
        parts.append("")

        # Card description
        parts.append("## Card Description")
        parts.append(card.desc)
        parts.append("")

        # Prior agent output from comments
        output_comments = await self._get_output_comments(card_id)
        if output_comments:
            parts.append("## Prior Agent Output")
            for agent_name, body in output_comments:
                parts.append(f"### {agent_name}\n{body}")
            parts.append("")

        # Completion — what to output when done
        parts.append("## Completion")
        if mode == "pr":
            parts.append("When you are done, briefly summarize what files you changed and why. The harness will commit, push, and open a PR automatically.")
        elif mode == "comment":
            parts.append("When you are done, provide your complete analysis. It will be posted as a comment on the Trello card.")
        elif mode == "cards":
            parts.append("When you are done creating cards, briefly summarize what cards you created and why.")
        elif mode == "update":
            parts.append(
                "Your final text response will be posted as a comment on the card.\n"
                "Follow the structured format from your system prompt. Include all required sections but respect the word limits — be concise.\n"
                "No preamble, no commentary. Just output the structured content directly."
            )

        return "\n".join(parts)

    async def _run_sdk(self, card: object, card_id: str, branch_name: str, tracker: ProgressTracker) -> tuple[str, float | None, dict | None]:
        """Run the Claude Agent SDK query with config-driven options."""
        prompt = await self._build_prompt(card, card_id, branch_name)

        # Build SDK options
        sdk_kwargs: dict = {
            "allowed_tools": list(self.config.allowed_tools),
            "system_prompt": {
                "type": "preset",
                "preset": "claude_code",
                "append": self.config.system_prompt,
            },
            "permission_mode": "bypassPermissions",
            "setting_sources": ["project"],
            "max_turns": self.config.max_turns,
        }
        if settings.model:
            sdk_kwargs["model"] = settings.model

        if self.config.repo_access == "write":
            sdk_kwargs["cwd"] = str(self.repo_dir)
        elif self.config.repo_access == "read":
            sdk_kwargs["add_dirs"] = [str(self.repo_dir)]

        # All workers get MCP tools (route_card for routing, plus cards-mode tools)
        if self.config.output_mode == "cards":
            sdk_kwargs["mcp_servers"] = {"karavan": build_mcp_server("karavan_worker")}
        else:
            sdk_kwargs["mcp_servers"] = {"karavan": build_worker_mcp_server("karavan_worker", self._current_card_id or "")}
        sdk_kwargs["allowed_tools"] = list({*sdk_kwargs["allowed_tools"], *MCP_TOOL_NAMES})

        # Keep the MCP bidirectional channel open for the full SDK timeout.
        # The SDK defaults CLAUDE_CODE_STREAM_CLOSE_TIMEOUT to 60s — after that
        # it closes stdin and MCP tool calls fail with "Stream closed".
        os.environ["CLAUDE_CODE_STREAM_CLOSE_TIMEOUT"] = str(self.config.sdk_timeout * 1000)

        # Shared state — survives timeout so partial work is not lost
        collected: dict = {"text": "", "cost": None, "usage": None}

        async def _consume() -> tuple[str, float | None, dict | None]:
            async for message in query(prompt=prompt, options=ClaudeAgentOptions(**sdk_kwargs)):
                tracker.record_activity(message)
                if isinstance(message, AssistantMessage):
                    blocks = [b.text for b in message.content if isinstance(b, TextBlock)]
                    if blocks:
                        text = "\n\n".join(blocks)
                        # Keep the longest assistant message — the structured output,
                        # not the brief "card routed" confirmation after tool calls.
                        if len(text) > len(collected["text"]):
                            collected["text"] = text
                if hasattr(message, "total_cost_usd"):
                    collected["cost"] = message.total_cost_usd
                    collected["usage"] = message.usage
            return collected["text"], collected["cost"], collected["usage"]

        # Two-phase timeout: 80% for main work, 20% reserved for wrap-up
        main_timeout = int(self.config.sdk_timeout * 0.8)
        wrapup_timeout = self.config.sdk_timeout - main_timeout

        try:
            return await asyncio.wait_for(_consume(), timeout=main_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "Worker %s: SDK timed out after %ds, running wrap-up query (%ds remaining)",
                self.name, main_timeout, wrapup_timeout,
            )
            return await self._run_wrapup(collected, sdk_kwargs, wrapup_timeout)

    async def _run_wrapup(
        self,
        collected: dict,
        sdk_kwargs: dict,
        timeout: int,
    ) -> tuple[str, float | None, dict | None]:
        """Run a short follow-up query to finalize partial output after timeout."""
        partial = collected["text"] or "(no output captured)"
        wrapup_prompt = (
            "You ran out of time. Below is your work so far.\n\n"
            "---\n\n"
            f"{partial}\n\n"
            "---\n\n"
            "Produce your COMPLETE final output NOW following the exact format in your system prompt. "
            "Use ONLY what you already have — do not search or fetch anything new. "
            "Every numbered section must be present. Output the structured content directly."
        )

        # Strip tools and MCP — wrap-up is pure text generation
        wrapup_kwargs = {**sdk_kwargs}
        wrapup_kwargs["allowed_tools"] = []
        wrapup_kwargs.pop("mcp_servers", None)
        wrapup_kwargs["max_turns"] = 1

        wrapup_text = ""
        try:
            async for message in query(prompt=wrapup_prompt, options=ClaudeAgentOptions(**wrapup_kwargs)):
                if isinstance(message, AssistantMessage):
                    blocks = [b.text for b in message.content if isinstance(b, TextBlock)]
                    if blocks:
                        wrapup_text = "\n\n".join(blocks)
                if hasattr(message, "total_cost_usd"):
                    cost = collected["cost"]
                    if message.total_cost_usd:
                        cost = (cost or 0) + message.total_cost_usd
                    collected["cost"] = cost
                    collected["usage"] = message.usage
        except Exception:
            logger.exception("Worker %s: wrap-up query failed, using partial output", self.name)

        return wrapup_text or collected["text"], collected["cost"], collected["usage"]

    async def _deliver_output(
        self,
        card: object,
        card_id: str,
        branch_name: str,
        result_text: str,
        cost: float | None,
        tracker: ProgressTracker,
    ) -> bool:
        """Deliver the agent's output based on output_mode. Returns True if card should move to done."""
        mode = self.config.output_mode

        if mode == "pr":
            return await self._deliver_pr(card, card_id, branch_name, result_text, cost, tracker)
        elif mode == "comment":
            comment_parts = [result_text or "Agent completed but produced no text output."]
            if cost is not None:
                comment_parts.append(f"\nCost: ${cost:.4f}")
            await add_comment(card_id, "\n".join(comment_parts))
            return True
        elif mode == "cards":
            summary = "Card creation completed."
            if result_text:
                summary = result_text[:500]
            if cost is not None:
                summary += f"\n\nCost: ${cost:.4f}"
            await add_comment(card_id, summary)
            return True
        elif mode == "update":
            if result_text:
                # Split into multiple comments if output exceeds Trello's per-comment limit
                remaining = result_text
                while remaining:
                    chunk = remaining[:OUTPUT_MAX_CHARS]
                    remaining = remaining[OUTPUT_MAX_CHARS:]
                    comment_text = f"{OUTPUT_PREFIX}{self.name}]\n{chunk}"
                    await add_comment(card_id, comment_text)
            if cost is not None:
                await add_comment(card_id, f"Output posted by {self.name}. Cost: ${cost:.4f}")
            return True
        else:
            raise ValueError(f"Unknown output_mode: {mode}")

    async def _deliver_pr(
        self,
        card: object,
        card_id: str,
        branch_name: str,
        result_text: str,
        cost: float | None,
        tracker: ProgressTracker,
    ) -> bool:
        """Handle PR output mode — commit, push, create PR, comment link."""
        commit_msg = f"[karavan] {card.name}\n\n{card.url}"
        has_changes = await commit_and_push(self.repo_dir, branch_name, commit_msg)

        if not has_changes:
            logger.warning("Worker %s: agent produced no changes for card '%s'", self.name, card.name)
            await add_comment(card_id, f"{FAIL_PREFIX} Agent completed but produced no code changes.")
            await update_card(card_id, id_list=self.board.failed_list_id)
            await tracker.finish(success=False, error="No code changes produced")
            return False

        pr_data = {
            "owner": self.owner,
            "repo": self.repo_name,
            "title": f"[karavan] {card.name}",
            "body": f"Trello card: {card.url}\n\n{result_text[:1000] if result_text else 'Automated by Karavan agent.'}",
            "head": branch_name,
            "base": self.config.base_branch,
        }
        pr = await create_pr(PRCreateIn.model_validate(pr_data))

        comment_parts = [f"PR opened: {pr.html_url}"]
        if cost is not None:
            comment_parts.append(f"Cost: ${cost:.4f}")
        await add_comment(card_id, "\n".join(comment_parts))

        await tracker.finish(success=True, pr_url=pr.html_url, cost_usd=cost)
        return True

    # --- Main execution ---

    async def _execute_card(self, card_id: str) -> None:
        """Full card execution lifecycle — delegates to stage methods based on config."""
        card = await get_card(card_id)

        if card.id_list != self.board.lists.todo:
            logger.info(
                "Worker %s skipping card '%s' — not in todo list",
                self.name, card.name,
            )
            return

        if self.config.label_id not in card.id_labels:
            logger.warning(
                "Worker %s skipping card '%s' — label removed before pickup",
                self.name, card.name,
            )
            return

        self._processed_cards.add(card_id)
        self._current_card_id = card_id
        card_id_short = card_id[-6:]
        branch_name = f"{self.config.branch_prefix}/card-{card_id_short}" if self.config.branch_prefix else ""

        logger.info("Worker %s picking up card '%s' (%s)", self.name, card.name, card_id)
        tracker = ProgressTracker(worker_name=self.name, card_name=card.name)

        try:
            # 1. Move to doing
            await update_card(card_id, id_list=self.board.lists.doing)
            await tracker.start()

            # 2. Setup repo (conditional on repo_access)
            await self._setup_repo(branch_name)

            # 3. Run Claude Agent SDK
            result_text, execution_cost, execution_usage = await self._run_sdk(card, card_id, branch_name, tracker)

            # 4. Record cost
            cost_tracker.record(self.name, execution_cost, execution_usage, card_id=card_id)

            # 5. Deliver output (conditional on output_mode)
            should_move_done = await self._deliver_output(
                card, card_id, branch_name, result_text, execution_cost, tracker,
            )

            # 6. Move to done or pipeline next stage
            if should_move_done:
                if self.config.output_mode != "pr":
                    await tracker.finish(success=True, cost_usd=execution_cost)
                await self._transition_card(card_id, card.name)

        except Exception:
            logger.exception("Worker %s failed on card '%s'", self.name, card.name)
            await tracker.finish(success=False, error="Agent execution failed")
            await self._handle_failure(card_id, card.name)
        finally:
            self._current_card_id = None

    async def _transition_card(self, card_id: str, card_name: str) -> None:
        """Move card to done or route to another worker via route_card decision."""
        try:
            target_name = get_routing_decision(card_id)
            if target_name:
                # Validate target worker exists on the same board
                if target_name not in self.board.workers:
                    logger.error(
                        "Worker %s: route_card target '%s' not on board, moving to done",
                        self.name, target_name,
                    )
                    await add_comment(
                        card_id,
                        f"route_card target '{target_name}' not found on this board. Card moved to done instead.",
                    )
                    target_name = None

            if target_name:
                # Check bounce count before routing
                bounce_count = await self._count_bounces(card_id)
                if bounce_count >= self.board.max_bounces:
                    await add_comment(
                        card_id,
                        f"{BOUNCE_PREFIX} Max bounces reached ({bounce_count}/{self.board.max_bounces}). "
                        f"Card killed by {self.name} instead of routing to '{target_name}'.",
                    )
                    await update_card(card_id, id_list=self.board.failed_list_id)
                    logger.warning(
                        "Worker %s: card '%s' moved to Failed after %d bounces",
                        self.name, card_name, bounce_count,
                    )
                    return

                await add_comment(card_id, f"{BOUNCE_PREFIX} {self.name} → {target_name}")
                next_worker = self.board.workers[target_name]
                await update_card(card_id, id_list=self.board.lists.todo)
                # Add next label BEFORE removing ours — card briefly has two
                # labels but is never orphaned without any label.
                await add_label(card_id, next_worker.label_id)
                try:
                    await remove_label(card_id, self.config.label_id)
                except Exception:
                    logger.warning("Worker %s: failed to remove old label from card %s", self.name, card_id)
            else:
                # Terminal: move to done first, then clean up label.
                # A card in done with a stale label is harmless;
                # a card in todo with no label is orphaned.
                await update_card(card_id, id_list=self.board.lists.done)
                try:
                    await remove_label(card_id, self.config.label_id)
                except Exception:
                    logger.warning("Worker %s: failed to remove label from done card %s", self.name, card_id)
            logger.info("Worker %s completed card '%s'", self.name, card_name)
        except Exception:
            # Output was already delivered — don't re-run the card, just flag for manual review
            logger.exception(
                "Worker %s: card transition failed after successful delivery for '%s'",
                self.name, card_name,
            )
            try:
                await add_comment(
                    card_id,
                    f"{FAIL_PREFIX} Output was delivered successfully but the card could not be "
                    f"moved to the next stage. Manual intervention needed.",
                )
            except Exception:
                logger.warning("Worker %s: failed to comment on card %s after transition failure", self.name, card_id)

    async def _handle_failure(self, card_id: str, card_name: str) -> None:
        """Handle a card execution failure — retry or move to failed list."""
        try:
            failure_count = await self._count_failures(card_id) + 1
            attempt_msg = f"Attempt {failure_count}/{MAX_RETRIES} failed"

            if failure_count >= MAX_RETRIES:
                await add_comment(
                    card_id,
                    f"{FAIL_PREFIX} {attempt_msg} (max retries reached). "
                    f"Agent {self.name} cannot process this card. Check server logs.",
                )
                await update_card(card_id, id_list=self.board.failed_list_id)
                logger.warning("Worker %s: card '%s' moved to Failed after %d attempts", self.name, card_name, failure_count)
            else:
                await add_comment(
                    card_id,
                    f"{FAIL_PREFIX} {attempt_msg}, will retry. "
                    f"Agent {self.name} failed to process this card. Check server logs.",
                )
                self._processed_cards.discard(card_id)
                await update_card(card_id, id_list=self.board.lists.todo)
                await remove_label(card_id, self.config.label_id)
                try:
                    await add_label(card_id, self.config.label_id)
                except Exception:
                    logger.exception(
                        "Worker %s: re-add label failed for card %s, card may be orphaned",
                        self.name, card_id,
                    )
                    try:
                        await add_comment(
                            card_id,
                            f"{FAIL_PREFIX} Retry label re-add failed. Manual re-label needed.",
                        )
                    except Exception:
                        logger.warning("Worker %s: failed to comment after label re-add failure for %s", self.name, card_id)
        except Exception:
            logger.exception("Failed to handle failure for card %s", card_id)
