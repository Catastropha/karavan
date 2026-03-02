"""Custom MCP tools exposed to the orchestrator's Claude SDK session.

These tools let the orchestrator create Trello cards, inspect worker agents,
and check card status — the actions it needs to actually orchestrate work.
"""

import json
import logging

from claude_agent_sdk import create_sdk_mcp_server, tool

from app.apps.trello.crud.create import create_card
from app.apps.trello.crud.read import get_card, get_list_cards
from app.apps.trello.model.input import CardCreateIn
from app.core.config import settings

logger = logging.getLogger(__name__)


def _text_result(text: str, is_error: bool = False) -> dict:
    """Build an MCP tool result."""
    result = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


def _get_worker(name: str):
    """Look up a worker config by name."""
    return settings.all_workers.get(name)


def _worker_not_found(name: str) -> dict:
    """Build an error result for an unknown worker name."""
    available = list(settings.all_workers.keys())
    return _text_result(f"Worker '{name}' not found. Available: {available}", is_error=True)


def _resolve_list_id(list_id: str) -> tuple[str, str] | None:
    """Resolve a Trello list ID to (worker_name, list_type) or None."""
    for name, config in settings.all_workers.items():
        for list_type in ("todo", "doing", "done"):
            if getattr(config.lists, list_type) == list_id:
                return name, list_type
    return None


# --- Tool definitions ---

@tool(
    "list_workers",
    "List all available worker agents and their Trello list IDs. "
    "Use this to find the correct todo list ID when creating cards.",
    {},
)
async def list_workers_tool(args: dict) -> dict:
    """Return all worker agents with their list IDs and board context."""
    workers = []
    for board_name, board in settings.boards.items():
        for name, config in board.workers.items():
            workers.append({
                "name": name,
                "board": board_name,
                "repo": config.repo or "(none)",
                "repo_access": config.repo_access,
                "output_mode": config.output_mode,
                "lists": {"todo": config.lists.todo, "doing": config.lists.doing, "done": config.lists.done},
                "system_prompt_preview": config.system_prompt[:100] if config.system_prompt else "",
            })
    if not workers:
        return _text_result("No worker agents configured.")
    return _text_result(json.dumps(workers, indent=2))


@tool(
    "create_trello_card",
    "Create a Trello card in a worker's todo list. "
    "The card description MUST follow the card schema: "
    "## Task, ## Context, ## Dependencies (optional), ## Acceptance Criteria.",
    {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Card title — short, imperative (e.g. 'Add appointment reminder endpoint')",
            },
            "description": {
                "type": "string",
                "description": "Card description in the card schema format with ## Task, ## Context, ## Acceptance Criteria sections",
            },
            "worker_name": {
                "type": "string",
                "description": "Name of the worker agent to assign this card to (use list_workers to find names)",
            },
        },
        "required": ["name", "description", "worker_name"],
    },
)
async def create_trello_card_tool(args: dict) -> dict:
    """Create a Trello card in the specified worker's todo list."""
    worker_name = args["worker_name"]
    config = _get_worker(worker_name)
    if not config:
        return _worker_not_found(worker_name)

    try:
        card_data = {
            "name": args["name"],
            "desc": args["description"],
            "id_list": config.lists.todo,
        }
        card = await create_card(CardCreateIn.model_validate(card_data))
        return _text_result(json.dumps({
            "status": "created",
            "card_id": card.id,
            "card_name": card.name,
            "card_url": card.url,
            "worker": worker_name,
            "list": "todo",
        }, indent=2))
    except Exception as e:
        logger.exception("Failed to create Trello card for worker %s", worker_name)
        return _text_result(f"Failed to create card: {e}", is_error=True)


@tool(
    "get_card_status",
    "Check the current status of a Trello card by its ID.",
    {
        "type": "object",
        "properties": {
            "card_id": {"type": "string", "description": "The Trello card ID"},
        },
        "required": ["card_id"],
    },
)
async def get_card_status_tool(args: dict) -> dict:
    """Fetch a card and return its current state."""
    try:
        card = await get_card(args["card_id"])
        result = {"id": card.id, "name": card.name, "description": card.desc, "url": card.url}
        resolved = _resolve_list_id(card.id_list)
        if resolved:
            result["worker"], result["status"] = resolved
        else:
            result["list_id"] = card.id_list
            result["status"] = "unknown"
        return _text_result(json.dumps(result, indent=2))
    except Exception as e:
        logger.exception("Failed to get card %s", args["card_id"])
        return _text_result(f"Failed to get card: {e}", is_error=True)


@tool(
    "get_worker_cards",
    "List all cards currently in a worker's todo, doing, or done list.",
    {
        "type": "object",
        "properties": {
            "worker_name": {"type": "string", "description": "Name of the worker agent"},
            "list_type": {"type": "string", "enum": ["todo", "doing", "done"], "description": "Which list to check"},
        },
        "required": ["worker_name", "list_type"],
    },
)
async def get_worker_cards_tool(args: dict) -> dict:
    """Fetch all cards in a worker's specified list."""
    worker_name = args["worker_name"]
    config = _get_worker(worker_name)
    if not config:
        return _worker_not_found(worker_name)

    try:
        cards = await get_list_cards(getattr(config.lists, args["list_type"]))
        result = [{"id": c.id, "name": c.name, "url": c.url} for c in cards]
        return _text_result(json.dumps({
            "worker": worker_name,
            "list": args["list_type"],
            "count": len(result),
            "cards": result,
        }, indent=2))
    except Exception as e:
        logger.exception("Failed to get cards for %s/%s", worker_name, args["list_type"])
        return _text_result(f"Failed to get cards: {e}", is_error=True)


MCP_TOOL_NAMES: list[str] = [
    "list_workers", "create_trello_card", "get_card_status", "get_worker_cards",
]


def build_mcp_server(name: str = "karavan"):
    """Create an MCP server with Trello card management tools."""
    return create_sdk_mcp_server(
        name=name,
        version="0.1.0",
        tools=[list_workers_tool, create_trello_card_tool, get_card_status_tool, get_worker_cards_tool],
    )
