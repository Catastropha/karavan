"""Custom MCP tools exposed to the orchestrator's and workers' Claude SDK sessions.

These tools let agents create Trello cards, inspect worker agents,
check card status, and route cards to other workers.
"""

import json
import logging

from claude_agent_sdk import create_sdk_mcp_server, tool

from app.apps.trello.crud.create import create_card
from app.apps.trello.crud.read import get_card, get_list_cards
from app.apps.trello.model.input import CardCreateIn
from app.core.config import BoardConfig, WorkerAgentConfig, settings

logger = logging.getLogger(__name__)

# --- Routing decisions ---
# Workers store routing decisions here during SDK execution via the route_card tool.
# After execution, the worker reads and pops the decision to determine card transition.
_routing_decisions: dict[str, str] = {}


def get_routing_decision(card_id: str) -> str | None:
    """Pop and return the routing decision for a card, or None if no decision was made."""
    return _routing_decisions.pop(card_id, None)


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


def _get_board(name: str) -> BoardConfig | None:
    """Look up a board config by name."""
    return settings.boards.get(name)


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
    "list_boards",
    "List all boards, their descriptions, and their worker agents. "
    "Use this to find the correct board_name when creating cards.",
    {},
)
async def list_boards_tool(args: dict) -> dict:
    """Return all boards with their workers."""
    boards = []
    for board_name, board in settings.boards.items():
        workers = []
        for name, config in board.workers.items():
            workers.append({
                "name": name,
                "repo": config.repo or "(none)",
                "repo_access": config.repo_access,
                "output_mode": config.output_mode,
                "system_prompt_preview": config.system_prompt[:100] if config.system_prompt else "",
            })
        boards.append({
            "name": board_name,
            "description": board.description or "",
            "workers": workers,
        })
    if not boards:
        return _text_result("No boards configured.")
    return _text_result(json.dumps(boards, indent=2))


@tool(
    "create_trello_card",
    "Create a Trello card on a board or for a specific worker. "
    "Provide board_name (card goes to first worker's label) OR worker_name (card goes to that worker's label). "
    "Exactly one of board_name/worker_name is required. "
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
            "board_name": {
                "type": "string",
                "description": "Name of the board to create the card on (first worker picks it up)",
            },
            "worker_name": {
                "type": "string",
                "description": "Name of a specific worker agent to assign this card to",
            },
        },
        "required": ["name", "description"],
    },
)
async def create_trello_card_tool(args: dict) -> dict:
    """Create a Trello card in a board's todo list with the appropriate label."""
    board_name = args.get("board_name")
    worker_name = args.get("worker_name")

    if not board_name and not worker_name:
        return _text_result("Either board_name or worker_name is required.", is_error=True)
    if board_name and worker_name:
        return _text_result("Provide board_name or worker_name, not both.", is_error=True)

    if board_name:
        board = _get_board(board_name)
        if not board:
            available = list(settings.boards.keys())
            return _text_result(f"Board '{board_name}' not found. Available: {available}", is_error=True)
        first_worker_name = next(iter(board.workers))
        config = board.workers[first_worker_name]
        display_target = board_name
    else:
        result = _get_worker(worker_name)
        if not result:
            return _worker_not_found(worker_name)
        config, board = result
        display_target = worker_name

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
            "board": board_name or display_target,
            "list": "todo",
        }, indent=2))
    except Exception as e:
        logger.exception("Failed to create Trello card for %s", display_target)
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
    "get_board_cards",
    "List all cards in a board's todo, doing, or done list.",
    {
        "type": "object",
        "properties": {
            "board_name": {"type": "string", "description": "Name of the board"},
            "list_type": {"type": "string", "enum": ["todo", "doing", "done"], "description": "Which list to check"},
        },
        "required": ["board_name", "list_type"],
    },
)
async def get_board_cards_tool(args: dict) -> dict:
    """Fetch all cards from a board's list."""
    board_name = args["board_name"]
    board = _get_board(board_name)
    if not board:
        available = list(settings.boards.keys())
        return _text_result(f"Board '{board_name}' not found. Available: {available}", is_error=True)

    try:
        lists = {"todo": board.lists.todo, "doing": board.lists.doing, "done": board.lists.done}
        list_id = lists[args["list_type"]]
        all_cards = await get_list_cards(list_id)
        cards_out = [{"id": c.id, "name": c.name, "url": c.url} for c in all_cards]
        return _text_result(json.dumps({
            "board": board_name,
            "list": args["list_type"],
            "count": len(cards_out),
            "cards": cards_out,
        }, indent=2))
    except Exception as e:
        logger.exception("Failed to get cards for board %s/%s", board_name, args["list_type"])
        return _text_result(f"Failed to get cards: {e}", is_error=True)


MCP_TOOL_NAMES: list[str] = [
    "list_boards", "create_trello_card", "get_card_status", "get_board_cards", "route_card",
]


def build_mcp_server(name: str = "karavan"):
    """Create an MCP server with Trello card management tools (orchestrator)."""
    return create_sdk_mcp_server(
        name=name,
        version="0.1.0",
        tools=[list_boards_tool, create_trello_card_tool, get_card_status_tool, get_board_cards_tool],
    )


def build_worker_mcp_server(name: str, card_id: str):
    """Create an MCP server for a worker, including route_card with card_id baked in."""

    @tool(
        "route_card",
        "Route the current card to another worker on the same board. "
        "Use this to hand off work — e.g. send a card back to a coder after review, "
        "or forward to a reviewer after coding. If you don't call this tool, "
        "the card moves to done (terminal).",
        {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Name of the worker agent to route this card to (use list_boards to find names)",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason for routing (posted as a comment on the card)",
                },
            },
            "required": ["target", "reason"],
        },
    )
    async def route_card_tool(args: dict) -> dict:
        """Store a routing decision for the current card."""
        target = args["target"]
        reason = args["reason"]

        # Validate target exists
        result = _get_worker(target)
        if not result:
            return _worker_not_found(target)

        _routing_decisions[card_id] = target
        return _text_result(
            f"Card will be routed to '{target}' after completion. Reason: {reason}"
        )

    return create_sdk_mcp_server(
        name=name,
        version="0.1.0",
        tools=[list_boards_tool, create_trello_card_tool, get_card_status_tool, get_board_cards_tool, route_card_tool],
    )
