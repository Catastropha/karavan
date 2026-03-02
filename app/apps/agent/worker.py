"""WorkerAgent — picks up Trello cards, runs Claude Agent SDK, pushes code, opens PRs."""

import logging
import re
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query

from app.apps.agent.base import BaseAgent
from app.apps.git_manager.crud.create import clone_repo, create_branch
from app.apps.git_manager.crud.update import commit_and_push, create_pr, pull_base
from app.apps.git_manager.model.input import PRCreateIn
from app.apps.trello.crud.read import get_card, get_card_actions
from app.apps.trello.crud.update import add_comment, move_card
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

    Lifecycle per card:
    1. Move card to doing
    2. git pull origin {base_branch}
    3. git checkout -b {branch_prefix}/card-{id}
    4. Claude Agent SDK query() with card description
    5. git commit + push
    6. Open GitHub PR
    7. Comment PR link on card
    8. Move card to done
    """

    def __init__(self, name: str, config: WorkerAgentConfig) -> None:
        super().__init__(name)
        self.config = config
        self.repo_dir = BASE_DIR / "repos" / name
        self.owner, self.repo_name = _parse_repo_url(config.repo)

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

        await self._execute_card(card_id)

    async def _count_failures(self, card_id: str) -> int:
        """Count failure comments on a card by looking for the fail prefix."""
        actions = await get_card_actions(card_id)
        return sum(
            1 for a in actions
            if a.get("data", {}).get("text", "").startswith(FAIL_PREFIX)
        )

    async def _execute_card(self, card_id: str) -> None:
        """Full card execution lifecycle."""
        card = await get_card(card_id)
        card_id_short = card_id[-6:]
        branch_name = f"{self.config.branch_prefix}/card-{card_id_short}"

        logger.info("Worker %s picking up card '%s' (%s)", self.name, card.name, card_id)

        try:
            # 1. Move to doing
            await move_card(card_id, self.config.lists.doing)

            # 2. Ensure repo is cloned, pull dev
            await clone_repo(self.config.repo, self.repo_dir)
            await pull_base(self.repo_dir, self.config.base_branch)

            # 3. Create feature branch
            await create_branch(self.repo_dir, branch_name)

            # 4. Run Claude Agent SDK
            prompt = (
                f"# Task: {card.name}\n"
                f"\n"
                f"You are a worker agent in the Karavan system. Your job is to **write code** that fulfills the task below.\n"
                f"\n"
                f"## Environment\n"
                f"- **Repository:** `{self.owner}/{self.repo_name}`\n"
                f"- **Working directory:** `{self.repo_dir}`\n"
                f"- **Branch:** `{branch_name}` (already checked out)\n"
                f"\n"
                f"## Rules\n"
                f"- **DO** read existing code to understand patterns before making changes.\n"
                f"- **DO** write clean, production-quality code that fits the existing codebase style.\n"
                f"- **DO** create or modify tests if the project has a test suite.\n"
                f"- **DO NOT** run any git commands (no `git add`, `git commit`, `git push`, `git checkout`, etc.). The harness handles all git operations after you finish.\n"
                f"- **DO NOT** just explain what to do — actually write the code.\n"
                f"- **DO NOT** modify files unrelated to this task.\n"
                f"\n"
                f"## Card Description\n"
                f"{card.desc}\n"
                f"\n"
                f"## Completion\n"
                f"When you are done, briefly summarize what files you changed and why. The harness will commit, push, and open a PR automatically.\n"
            )
            result_text = ""
            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    cwd=str(self.repo_dir),
                    allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
                    system_prompt={
                        "type": "preset",
                        "preset": "claude_code",
                        "append": self.config.system_prompt,
                    },
                    permission_mode="bypassPermissions",
                    setting_sources=["project"],
                    max_turns=50,
                ),
            ):
                if hasattr(message, "result"):
                    result_text = getattr(message.result, "text", str(message.result))

            # 5. Commit and push
            commit_msg = f"[karavan] {card.name}\n\n{card.url}"
            has_changes = await commit_and_push(self.repo_dir, branch_name, commit_msg)

            if not has_changes:
                logger.warning("Worker %s: agent produced no changes for card '%s'", self.name, card.name)
                await add_comment(card_id, f"{FAIL_PREFIX} Agent completed but produced no code changes.")
                await move_card(card_id, settings.failed_list_id)
                return

            # 6. Create PR
            pr = await create_pr(PRCreateIn(
                owner=self.owner,
                repo=self.repo_name,
                title=f"[karavan] {card.name}",
                body=f"Trello card: {card.url}\n\n{result_text[:1000] if result_text else 'Automated by Karavan agent.'}",
                head=branch_name,
                base=self.config.base_branch,
            ))

            # 7. Comment PR link on card
            await add_comment(card_id, f"PR opened: {pr.html_url}")

            # 8. Move to done
            await move_card(card_id, self.config.lists.done)
            logger.info("Worker %s completed card '%s' -> PR %s", self.name, card.name, pr.html_url)

        except Exception:
            logger.exception("Worker %s failed on card '%s'", self.name, card.name)
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
                    await move_card(card_id, self.config.lists.todo)
            except Exception:
                logger.exception("Failed to handle failure for card %s", card_id)
