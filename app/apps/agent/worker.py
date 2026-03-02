"""WorkerAgent — picks up Trello cards and executes them based on configurable behavior axes."""

import logging
import re
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query

from app.apps.agent.base import BaseAgent
from app.apps.agent.tools import build_worker_mcp_server
from app.apps.git_manager.crud.create import clone_repo, create_branch
from app.apps.git_manager.crud.update import commit_and_push, create_pr, pull_base
from app.apps.git_manager.model.input import PRCreateIn
from app.apps.trello.crud.read import get_card, get_card_actions
from app.apps.trello.crud.update import add_comment, move_card, update_card_description
from app.common.cost import cost_tracker
from app.common.progress import ProgressTracker
from app.core.config import BASE_DIR, WorkerAgentConfig, settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
FAIL_PREFIX = "[karavan:fail]"


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

    def __init__(self, name: str, config: WorkerAgentConfig) -> None:
        super().__init__(name)
        self.config = config
        self.repo_dir = BASE_DIR / "repos" / name
        self._processed_cards: set[str] = set()

        if config.repo_access in ("write", "read") and config.repo:
            self.owner, self.repo_name = _parse_repo_url(config.repo)
        else:
            self.owner = ""
            self.repo_name = ""

    def should_process_webhook(self, list_id: str) -> bool:
        """Process webhooks when a card enters this worker's todo list."""
        return list_id == self.config.lists.todo

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
        return sum(
            1 for a in actions
            if a.get("data", {}).get("text", "").startswith(FAIL_PREFIX)
        )

    # --- Stage methods ---

    async def _setup_repo(self, branch_name: str) -> None:
        """Clone/pull repo and optionally create a branch based on repo_access."""
        if self.config.repo_access == "none":
            return

        await clone_repo(self.config.repo, self.repo_dir)
        await pull_base(self.repo_dir, self.config.base_branch)

        if self.config.repo_access == "write":
            await create_branch(self.repo_dir, branch_name)

    def _build_prompt(self, card: object, branch_name: str) -> str:
        """Build the SDK prompt based on output_mode and repo_access."""
        mode = self.config.output_mode
        parts = [f"# Task: {card.name}\n"]

        if mode == "pr":
            parts.append(
                "You are a worker agent in the Karavan system. Your job is to **write code** that fulfills the task below.\n"
            )
        elif mode == "comment":
            parts.append(
                "You are a worker agent in the Karavan system. Your job is to **analyze the task below and provide a detailed written response**.\n"
            )
        elif mode == "cards":
            parts.append(
                "You are a worker agent in the Karavan system. Your job is to **break down the task below into concrete, actionable sub-tasks** and create Trello cards for each using the available MCP tools.\n"
                "\n"
                "Use `list_workers` to discover available workers and their todo list IDs, then use `create_trello_card` to create cards.\n"
            )
        elif mode == "update":
            parts.append(
                "You are a worker agent in the Karavan system. Your job is to **produce an improved version of the card description** below.\n"
                "\n"
                "Output ONLY the updated card description in markdown. Do not include any preamble or explanation — just the new description content.\n"
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

        # Rules (mode-specific)
        parts.append("## Rules")
        if mode == "pr":
            parts.extend([
                "- **DO** read existing code to understand patterns before making changes.",
                "- **DO** write clean, production-quality code that fits the existing codebase style.",
                "- **DO** create or modify tests if the project has a test suite.",
                "- **DO NOT** run any git commands (no `git add`, `git commit`, `git push`, `git checkout`, etc.). The harness handles all git operations after you finish.",
                "- **DO NOT** just explain what to do — actually write the code.",
                "- **DO NOT** modify files unrelated to this task.",
            ])
        elif mode == "comment":
            parts.extend([
                "- **DO** provide thorough, actionable analysis.",
                "- **DO** reference specific files and line numbers when relevant.",
                "- **DO NOT** modify any files — this is a read-only analysis task.",
            ])
        elif mode == "cards":
            parts.extend([
                "- **DO** use `list_workers` to find available workers before creating cards.",
                "- **DO** follow the card schema format (## Task, ## Context, ## Acceptance Criteria).",
                "- **DO** set dependencies between cards when order matters.",
                "- **DO NOT** modify any files — use only the MCP tools to create cards.",
            ])
        elif mode == "update":
            parts.extend([
                "- **DO** preserve the card schema structure (## Task, ## Context, etc.).",
                "- **DO** make the description clearer, more detailed, and more actionable.",
                "- **DO NOT** modify any files — your text output IS the deliverable.",
            ])
        parts.append("")

        # Card description
        parts.append("## Card Description")
        parts.append(card.desc)
        parts.append("")

        # Completion instructions
        parts.append("## Completion")
        if mode == "pr":
            parts.append("When you are done, briefly summarize what files you changed and why. The harness will commit, push, and open a PR automatically.")
        elif mode == "comment":
            parts.append("When you are done, provide your complete analysis. It will be posted as a comment on the Trello card.")
        elif mode == "cards":
            parts.append("When you are done creating cards, briefly summarize what cards you created and why.")
        elif mode == "update":
            parts.append("Output the complete updated card description now.")

        return "\n".join(parts)

    async def _run_sdk(self, card: object, branch_name: str, tracker: ProgressTracker) -> tuple[str, float | None, dict | None]:
        """Run the Claude Agent SDK query with config-driven options."""
        prompt = self._build_prompt(card, branch_name)
        result_text = ""
        execution_cost: float | None = None
        execution_usage: dict | None = None

        # Build SDK options based on config axes
        sdk_kwargs: dict = {
            "allowed_tools": list(self.config.allowed_tools),
            "system_prompt": {
                "type": "preset",
                "preset": "claude_code",
                "append": self.config.system_prompt,
            },
            "permission_mode": "bypassPermissions",
            "setting_sources": ["project"],
            "max_turns": 50,
        }

        if self.config.repo_access == "write":
            sdk_kwargs["cwd"] = str(self.repo_dir)
        elif self.config.repo_access == "read":
            sdk_kwargs["add_dirs"] = [str(self.repo_dir)]

        if self.config.output_mode == "cards":
            mcp_server = build_worker_mcp_server()
            sdk_kwargs["mcp_servers"] = {"karavan": mcp_server}
            # Add MCP tool names to allowed_tools
            mcp_tool_names = ["list_workers", "create_trello_card", "get_card_status", "get_worker_cards"]
            for tool_name in mcp_tool_names:
                if tool_name not in sdk_kwargs["allowed_tools"]:
                    sdk_kwargs["allowed_tools"].append(tool_name)

        async for message in query(prompt=prompt, options=ClaudeAgentOptions(**sdk_kwargs)):
            tracker.record_activity(message)
            if hasattr(message, "total_cost_usd"):
                execution_cost = message.total_cost_usd
                execution_usage = message.usage
                result_text = getattr(message, "result", "") or ""

        return result_text, execution_cost, execution_usage

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
            summary = f"Card creation completed."
            if result_text:
                summary = result_text[:500]
            if cost is not None:
                summary += f"\n\nCost: ${cost:.4f}"
            await add_comment(card_id, summary)
            return True
        elif mode == "update":
            if result_text:
                await update_card_description(card_id, result_text)
            if cost is not None:
                await add_comment(card_id, f"Description updated. Cost: ${cost:.4f}")
            return True

        return True

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
            await move_card(card_id, settings.failed_list_id)
            await tracker.finish(success=False, error="No code changes produced")
            return False

        pr = await create_pr(PRCreateIn(
            owner=self.owner,
            repo=self.repo_name,
            title=f"[karavan] {card.name}",
            body=f"Trello card: {card.url}\n\n{result_text[:1000] if result_text else 'Automated by Karavan agent.'}",
            head=branch_name,
            base=self.config.base_branch,
        ))

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

        if card.id_list != self.config.lists.todo:
            logger.info(
                "Worker %s skipping card '%s' — not in todo list",
                self.name, card.name,
            )
            return

        self._processed_cards.add(card_id)
        card_id_short = card_id[-6:]
        branch_name = f"{self.config.branch_prefix}/card-{card_id_short}" if self.config.branch_prefix else ""

        logger.info("Worker %s picking up card '%s' (%s)", self.name, card.name, card_id)
        tracker = ProgressTracker(worker_name=self.name, card_name=card.name)

        try:
            # 1. Move to doing
            await move_card(card_id, self.config.lists.doing)
            await tracker.start()

            # 2. Setup repo (conditional on repo_access)
            await self._setup_repo(branch_name)

            # 3. Run Claude Agent SDK
            result_text, execution_cost, execution_usage = await self._run_sdk(card, branch_name, tracker)

            # 4. Record cost
            cost_tracker.record(self.name, execution_cost, execution_usage, card_id=card_id)

            # 5. Deliver output (conditional on output_mode)
            should_move_done = await self._deliver_output(
                card, card_id, branch_name, result_text, execution_cost, tracker,
            )

            # 6. Move to done (if not already handled by deliver)
            if should_move_done:
                await move_card(card_id, self.config.lists.done)
                if self.config.output_mode != "pr":
                    await tracker.finish(success=True, cost_usd=execution_cost)
                logger.info("Worker %s completed card '%s'", self.name, card.name)

        except Exception:
            logger.exception("Worker %s failed on card '%s'", self.name, card.name)
            await tracker.finish(success=False, error="Agent execution failed")
            try:
                failure_count = await self._count_failures(card_id) + 1
                attempt_msg = f"Attempt {failure_count}/{MAX_RETRIES} failed"

                if failure_count >= MAX_RETRIES:
                    await add_comment(
                        card_id,
                        f"{FAIL_PREFIX} {attempt_msg} (max retries reached). "
                        f"Agent {self.name} cannot process this card. Check server logs.",
                    )
                    await move_card(card_id, settings.failed_list_id)
                    logger.warning("Worker %s: card '%s' moved to Failed after %d attempts", self.name, card.name, failure_count)
                else:
                    await add_comment(
                        card_id,
                        f"{FAIL_PREFIX} {attempt_msg}, will retry. "
                        f"Agent {self.name} failed to process this card. Check server logs.",
                    )
                    self._processed_cards.discard(card_id)
                    await move_card(card_id, self.config.lists.todo)
            except Exception:
                logger.exception("Failed to handle failure for card %s", card_id)
