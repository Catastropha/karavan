"""WorkerAgent — picks up Trello cards, runs Claude Agent SDK, pushes code, opens PRs."""

import logging
import re
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query

from app.apps.agent.base import BaseAgent
from app.apps.git_manager.crud.create import clone_repo, create_branch
from app.apps.git_manager.crud.update import commit_and_push, create_pr, pull_main
from app.apps.git_manager.model.input import PRCreateIn
from app.apps.trello.crud.read import get_card
from app.apps.trello.crud.update import add_comment, move_card
from app.core.config import BASE_DIR, WorkerAgentConfig

logger = logging.getLogger(__name__)


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
    2. git pull origin main
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

    async def _execute_card(self, card_id: str) -> None:
        """Full card execution lifecycle."""
        card = await get_card(card_id)
        card_id_short = card_id[-6:]
        branch_name = f"{self.config.branch_prefix}/card-{card_id_short}"

        logger.info("Worker %s picking up card '%s' (%s)", self.name, card.name, card_id)

        try:
            # 1. Move to doing
            await move_card(card_id, self.config.lists.doing)

            # 2. Ensure repo is cloned, pull main
            await clone_repo(self.config.repo, self.repo_dir)
            await pull_main(self.repo_dir)

            # 3. Create feature branch
            await create_branch(self.repo_dir, branch_name)

            # 4. Run Claude Agent SDK
            prompt = f"## Card: {card.name}\n\n{card.desc}"
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
            await commit_and_push(self.repo_dir, branch_name, commit_msg)

            # 6. Create PR
            pr = await create_pr(PRCreateIn(
                owner=self.owner,
                repo=self.repo_name,
                title=f"[karavan] {card.name}",
                body=f"Trello card: {card.url}\n\n{result_text[:1000] if result_text else 'Automated by Karavan agent.'}",
                head=branch_name,
                base="main",
            ))

            # 7. Comment PR link on card
            await add_comment(card_id, f"PR opened: {pr.html_url}")

            # 8. Move to done
            await move_card(card_id, self.config.lists.done)
            logger.info("Worker %s completed card '%s' -> PR %s", self.name, card.name, pr.html_url)

        except Exception:
            logger.exception("Worker %s failed on card '%s'", self.name, card.name)
            try:
                await add_comment(card_id, f"Agent {self.name} failed to process this card. Check server logs.")
                await move_card(card_id, self.config.lists.todo)
            except Exception:
                logger.exception("Failed to move card %s back to todo", card_id)
