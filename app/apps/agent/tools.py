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
from app.core.config import BoardConfig, WorkerAgentConfig, settings

logger = logging.getLogger(__name__)


def _text_result(text: str, is_error: bool = False) -> dict:
    """Build an MCP tool result."""
    result = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


def _get_worker(name: str) -> tuple[WorkerAgentConfig, BoardConfig] | None:
    """Look up a worker config and its parent board by name."""
    for board in settings.boards.values():
        if name in board.workers:
            return board.workers[name], board
    return None


def _worker_not_found(name: str) -> dict:
    """Build an error result for an unknown worker name."""
    available = list(settings.all_workers.keys())
    return _text_result(f"Worker '{name}' not found. Available: {available}", is_error=True)


def _resolve_list(list_id: str) -> tuple[str, str] | None:
    """Resolve a Trello list ID to (board_name, list_type) or None."""
    for board_name, board in settings.boards.items():
        lists = {"todo": board.lists.todo, "doing": board.lists.doing, "done": board.lists.done}
        for list_type, lid in lists.items():
            if lid == list_id:
                return board_name, list_type
    return None


def _resolve_worker_from_labels(id_labels: list[str]) -> tuple[str, str] | None:
    """Resolve worker name and board name from a card's label IDs."""
    for board_name, board in settings.boards.items():
        for worker_name, config in board.workers.items():
            if config.label_id in id_labels:
                return worker_name, board_name
    return None


# --- Tool definitions ---

@tool(
    "list_workers",
    "List all available worker agents, their label IDs, and board list IDs. "
    "Use this to find the correct worker name when creating cards.",
    {},
)
async def list_workers_tool(args: dict) -> dict:
    """Return all worker agents with their configs and board context."""
    workers = []
    for board_name, board in settings.boards.items():
        for name, config in board.workers.items():
            workers.append({
                "name": name,
                "board": board_name,
                "board_description": board.description or "",
                "label_id": config.label_id,
                "next_stage": config.next_stage,
                "repo": config.repo or "(none)",
                "repo_access": config.repo_access,
                "output_mode": config.output_mode,
                "lists": {"todo": board.lists.todo, "doing": board.lists.doing, "done": board.lists.done},
                "system_prompt_preview": config.system_prompt[:100] if config.system_prompt else "",
            })
    if not workers:
        return _text_result("No worker agents configured.")
    return _text_result(json.dumps(workers, indent=2))


@tool(
    "create_trello_card",
    "Create a Trello card for a worker agent. "
    "The card is placed in the board's todo list with the worker's label. "
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
    """Create a Trello card in the board's todo list with the worker's label."""
    worker_name = args["worker_name"]
    result = _get_worker(worker_name)
    if not result:
        return _worker_not_found(worker_name)

    config, board = result

    try:
        card_data = {
            "name": args["name"],
            "desc": args["description"],
            "id_list": board.lists.todo,
            "id_labels": [config.label_id],
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

        resolved_list = _resolve_list(card.id_list)
        if resolved_list:
            result["board"], result["status"] = resolved_list
        else:
            result["list_id"] = card.id_list
            result["status"] = "unknown"

        resolved_worker = _resolve_worker_from_labels(card.id_labels)
        if resolved_worker:
            result["worker"], _ = resolved_worker

        return _text_result(json.dumps(result, indent=2))
    except Exception as e:
        logger.exception("Failed to get card %s", args["card_id"])
        return _text_result(f"Failed to get card: {e}", is_error=True)


@tool(
    "get_worker_cards",
    "List all cards currently assigned to a worker in the board's todo, doing, or done list.",
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
    """Fetch cards from the board's list, filtered by the worker's label."""
    worker_name = args["worker_name"]
    result = _get_worker(worker_name)
    if not result:
        return _worker_not_found(worker_name)

    config, board = result

    try:
        lists = {"todo": board.lists.todo, "doing": board.lists.doing, "done": board.lists.done}
        list_id = lists[args["list_type"]]
        all_cards = await get_list_cards(list_id)
        worker_cards = [c for c in all_cards if config.label_id in c.id_labels]
        cards_out = [{"id": c.id, "name": c.name, "url": c.url} for c in worker_cards]
        return _text_result(json.dumps({
            "worker": worker_name,
            "list": args["list_type"],
            "count": len(cards_out),
            "cards": cards_out,
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
