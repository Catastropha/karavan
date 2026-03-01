# CLAUDE.md — Karavan

## Project Overview

**Karavan** is an open-source framework that turns Trello boards into a communication protocol between AI coding agents powered by the Claude Agent SDK.

One sentence: You talk to an orchestrator via Telegram, it breaks work into Trello cards, worker agents pick them up, write code, push branches, and open PRs — autonomously.

```
You (Telegram) ←→ Orchestrator Agent
                        ↓
                  Trello Board
                 (the message bus)
                        ↓
              ┌─────────┼─────────┐
              ↓         ↓         ↓
          Worker A   Worker B   Worker C
          (api)      (static)   (infra)
           ↓           ↓          ↓
         repo A      repo B     repo C
```

---

## Tech Stack

- **Python 3.12+**
- **FastAPI** + uvicorn
- **Claude Agent SDK** (`claude-agent-sdk`, `from claude_agent_sdk import ...`) — gives each agent full Claude Code powers (file edit, bash, git, agent loop)
- **Telegram Bot API** — orchestrator chat interface (custom integration via httpx, no external bot library)
- **httpx** — async HTTP client for Trello API, Telegram API, and GitHub API
- **pydantic-settings** — config from env + json
- **Git** — agents clone, branch, commit, push via subprocess

---

## Architecture

### Core Concepts

| Concept    | What it is                                              |
|------------|---------------------------------------------------------|
| **Board**  | The project — all agents share visibility               |
| **Card**   | A task — the unit of work passed between agents         |
| **Lists**  | Agent state — `todo`, `doing`, `done` per agent         |

### Agent Types

**Orchestrator (1 per project):**
- User talks to it via Telegram
- Clones all repos into `repos/orchestrator/{repo_name}/` on startup, pulls before each planning session
- Uses `ClaudeSDKClient` for persistent multi-turn conversation context with the user
- Has read access to all repos via `add_dirs` on `ClaudeAgentOptions`
- Breaks features into tasks, creates Trello cards in worker agents' `todo` lists
- Monitors `done` lists via a single board-level Trello webhook (filters by known `done` list IDs)
- Validates work, reports back via Telegram
- Can request revisions by moving cards back to `todo` with a comment

**Worker (N per project):**
- Watches its own `todo` list via a list-level Trello webhook
- Picks up a card → moves to `doing`
- Uses `query()` (one-shot, stateless) scoped to its cloned repo directory via `cwd`
- Commits to a branch, pushes, opens PR via GitHub API
- Comments result/PR link on the Trello card
- Moves card to `done`

### Event Flow

```
1. User → Telegram: "Add appointment reminders"
2. Telegram POSTs to /telegram/{secret} → BotMessage pushed to orchestrator's asyncio.Queue
3. Orchestrator reads repos, proposes plan → sends response via Telegram sendMessage
4. User approves (or adjusts) via inline keyboard → another webhook POST
5. Orchestrator creates Trello cards in workers' todo lists
6. Trello webhook fires → POST /webhook/{agent_name}
7. Worker agent:
   a. Moves card to doing
   b. git pull origin main
   c. git checkout -b {branch_prefix}/card-{id}
   d. Claude Agent SDK query() executes with card description as prompt
   e. git commit + push
   f. Opens GitHub PR via API
   g. Comments PR link on Trello card
   h. Moves card to done
8. Orchestrator board webhook detects card moved to done → notifies user via Telegram
```

### Webhook Strategy

- **Workers** register a list-level webhook on their `todo` list. Only fires when cards enter that list.
- **Orchestrator** registers a single board-level webhook. Filters incoming events by `action.data.listAfter.id` matching any known `done` list ID. One webhook instead of N — simpler to manage, fewer API calls on startup, automatically picks up new lists.

### Dependency Handling

Cards reference dependencies via convention in the card description:

```markdown
## Dependencies
- Requires: card_id_xyz (api agent) to be in Done
```

Orchestrator holds dependent cards until the dependency clears. No complex DAG — just linear or parallel with simple "wait for X" blocks.

### What We Intentionally Don't Build

- No auth system — single user, your VPS
- No database — Trello is the state store
- No message queue — Trello is the queue
- No web UI — Trello is the UI
- No agent memory between tasks — each card is stateless, context is in the card description + repo

---

## Card Schema (The Protocol)

A Trello card IS the task contract between agents. Workers must parse this format from the card description:

```markdown
## Task
Short description of what to do

## Context
- Relevant file paths in the repo
- Constraints and preferences
- Patterns to follow

## Dependencies
- Requires: card_id (agent_name) to be in Done (optional)

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Tests pass
- [ ] No breaking changes
```

---

## Configuration

### Secrets — `.env` (never committed)

```bash
TRELLO_API_KEY=
TRELLO_TOKEN=
ANTHROPIC_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_SECRET=              # random string, used as webhook URL path suffix for auth
TELEGRAM_ALLOWED_USER_IDS=[123456789]
GIT_SSH_KEY_PATH=/root/.ssh/id_ed25519
WEBHOOK_BASE_URL=https://agents.yourdomain.com
GITHUB_TOKEN=
```

### Topology — `config.json` (safe to commit, no secrets)

```json
{
  "agents": {
    "api": {
      "type": "worker",
      "lists": {
        "todo": "trello_list_id",
        "doing": "trello_list_id",
        "done": "trello_list_id"
      },
      "repo": "git@github.com:user/myproject-api.git",
      "branch_prefix": "agent/api",
      "system_prompt": "You are a FastAPI backend developer. Follow existing patterns in the codebase."
    },
    "static": {
      "type": "worker",
      "lists": {
        "todo": "trello_list_id",
        "doing": "trello_list_id",
        "done": "trello_list_id"
      },
      "repo": "git@github.com:user/myproject-static.git",
      "branch_prefix": "agent/static",
      "system_prompt": "You are a frontend developer. Use the existing component library."
    },
    "orchestrator": {
      "type": "orchestrator",
      "board_id": "trello_board_id",
      "repos": [
        "git@github.com:user/myproject-api.git",
        "git@github.com:user/myproject-static.git"
      ],
      "system_prompt": "You are an engineering lead. Break features into clear tasks for worker agents."
    }
  }
}
```

`config.py` uses `pydantic-settings` to load secrets from environment and topology from `config.json`.

---

## Feature Roadmap

### v0.1 — MVP

- FastAPI webhook server receiving Trello events
- Trello async client (cards, lists, move, comment, webhook registration)
- Worker agent: webhook → Claude Agent SDK → git branch → push → PR → comment on card
- Orchestrator agent: Telegram bot → plan features → create Trello cards
- Config from `.env` + `config.json`
- Logging to stdout

### v0.2 — Usable

- Card dependency tracking (orchestrator holds cards until deps clear)
- Orchestrator watches `done` lists and reports progress via Telegram
- Retry logic: on agent failure, comment error on card, move back to `todo`
- Agent system prompts loaded from config
- GitHub PR creation via API with card link in PR body

### v0.3 — Polish

- Docker + docker-compose
- Caddy HTTPS setup guide
- Multiple projects/boards support
- Card templates
- Cost tracking (log Claude API token usage per card)

### v1.0 — Community

- Plugin system for other boards (Linear, GitHub Issues, Jira)
- Plugin system for other LLMs (OpenAI, local models)
- Plugin system for other chat interfaces (Slack, Discord)
- CI/CD integration (trigger deploys when cards reach `done`)

---

## Apps Breakdown

### `trello` app
- Trello domain models (card schemas, webhook payloads) and Trello-specific CRUD operations
- The raw httpx client for Trello lives in `core/resource.py` as a shared singleton (infrastructure, not domain)
- CRUD wraps the shared client with domain methods: get_card, get_list_cards, create_card, move_card, add_comment, add_label, register_webhook, delete_webhook
- Webhook payload parsing and validation via Pydantic models

### `agent` app
- BaseAgent class: async queue, lifecycle (start/stop), card pickup logic
- WorkerAgent: inherits BaseAgent, uses `query()` (one-shot) scoped to a repo via `cwd`, handles the full card lifecycle (todo → doing → done)
- OrchestratorAgent: inherits BaseAgent, uses `ClaudeSDKClient` (multi-turn) for persistent conversation, connected to Telegram, creates/monitors cards, handles dependency tracking
- Agent registry: loads agents from config.json, starts them on app lifespan

### `git_manager` app
- Git operations via async subprocess: clone, pull, checkout, commit, push
- GitHub API client: create PR, link PR to Trello card
- SSH key configuration via GIT_SSH_COMMAND env var
- Repo management: clone on first run, pull on subsequent tasks

### `bot` app
- Telegram webhook route: receives POSTs at `/telegram/{secret}`, parses into Pydantic models, pushes `BotMessage` to orchestrator's queue
- Telegram send helpers: `send_message`, `send_typing_action` via shared httpx client
- MarkdownV2 escaping utility for LLM output
- Webhook registration on app startup via `setWebhook` API call
- Allowed user ID filtering from config
- Inline keyboard for approve/reject plan confirmation

### `hook` app
- Route: `HEAD /webhook/{agent_name}` — Trello verification
- Route: `POST /webhook/{agent_name}` — receives Trello events, filters for card moves to `todo` lists, pushes to the correct agent's async queue
- Route: `GET /health` — basic health check

### `common` app
- Shared Pydantic models used across apps
- Shared utilities (logging helpers, async helpers)
- Shared exceptions

---

## Implementation Notes

### Trello Client
- Shared httpx async client lives in `core/resource.py` as a singleton with base URL `https://api.trello.com/1/`
- All requests include `key` and `token` query params from config
- Rate limit: 100 requests per 10 seconds per token — implement simple rate limiting
- Register webhooks on app startup, pointing to `{WEBHOOK_BASE_URL}/webhook/{agent_name}`
- Workers register list-level webhooks on their `todo` list
- Orchestrator registers a single board-level webhook, filters events by known `done` list IDs

### Claude Agent SDK Integration

**Package:** `claude-agent-sdk` — `from claude_agent_sdk import query, ClaudeSDKClient, ClaudeAgentOptions, ...`

**Workers use `query()` (one-shot, stateless):**
```python
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(
    prompt=card_description,
    options=ClaudeAgentOptions(
        cwd="/path/to/repos/agent_name",
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": agent_system_prompt_from_config,
        },
        permission_mode="bypassPermissions",
        setting_sources=["project"],  # loads CLAUDE.md from the repo
        max_turns=50,
    ),
):
    # process messages, collect ResultMessage at end
```

**Orchestrator uses `ClaudeSDKClient` (multi-turn, persistent context):**
```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

client = ClaudeSDKClient(options=ClaudeAgentOptions(
    add_dirs=["/path/to/repos/orchestrator/repo-a", "/path/to/repos/orchestrator/repo-b"],
    allowed_tools=["Read", "Glob", "Grep"],  # read-only access to repos
    system_prompt={
        "type": "preset",
        "preset": "claude_code",
        "append": orchestrator_system_prompt,
    },
    permission_mode="bypassPermissions",
    setting_sources=["project"],
))
async with client:
    await client.query(user_message_from_telegram)
    async for message in client.receive_response():
        # stream response back to Telegram
```

**Key SDK notes:**
- System prompt is blank by default — always set it explicitly
- `setting_sources=["project"]` required to load CLAUDE.md files from repos (not loaded by default)
- `ResultMessage` provides `total_cost_usd` and `usage` (token counts) for free — use for cost tracking
- The SDK spawns the Claude Code CLI as a subprocess (CLI is bundled with the pip package)

### Git Operations
- All git operations use `GIT_SSH_COMMAND` env var for SSH key
- Worker repos cloned to `repos/{agent_name}/` directory (one repo per worker)
- Orchestrator repos cloned to `repos/orchestrator/{repo_name}/` directory (all repos, read-only for context)
- Branch naming: `{branch_prefix}/card-{card_id_short}` (last 6 chars of card ID)
- Always pull main before creating a new branch
- Commit message: `[karavan] {card_name}` with card URL in commit body

### Telegram Bot

**Receiving messages — webhook mode (not long-polling):**
- Telegram POSTs updates to `{WEBHOOK_BASE_URL}/telegram/{TELEGRAM_SECRET}`
- The `{TELEGRAM_SECRET}` path parameter is the primary auth — only Telegram knows the URL
- Validated with `secrets.compare_digest` for constant-time comparison
- Route lives in the `bot` app, hidden from OpenAPI (`include_in_schema=False`)
- Always returns `200 OK` to Telegram (even for ignored updates) to prevent retries
- Webhook registered automatically on app startup via `setWebhook` API call

**Incoming payload handling:**
- Telegram payload parsed into Pydantic models with `extra='ignore'` and `Field(alias='from')` for the reserved keyword
- Normalized into a `BotMessage` model (lives in `common` since both `bot` and `agent` apps reference it)
- Pushed to the orchestrator agent's `asyncio.Queue` (no Redis — Trello is our only external state store)
- Filter by `TELEGRAM_ALLOWED_USER_IDS` before queuing

**Sending messages — async httpx:**
- All outbound calls use the shared httpx client from `core/resource.py` against `https://api.telegram.org/bot{token}/`
- `sendMessage` with `parse_mode=MarkdownV2` for formatted responses
- MarkdownV2 escaping: split on `**bold**` markers, convert to Telegram's `*bold*`, escape all special chars in the rest
- `sendChatAction` (typing indicator) while orchestrator is thinking
- Inline keyboard via `reply_markup` for approve/reject plan confirmation

**Pydantic models (bot app):**
```python
# model/input.py — Telegram webhook payload
class TelegramUser(BaseModel):
    id: int
    is_bot: bool = False
    first_name: str = ''
    model_config = {'extra': 'ignore'}

class TelegramChat(BaseModel):
    id: int
    type: str = 'private'
    model_config = {'extra': 'ignore'}

class TelegramMessage(BaseModel):
    message_id: int
    from_: TelegramUser = Field(alias='from')
    chat: TelegramChat
    text: Annotated[str, Field(min_length=1, max_length=4096)] = ''
    date: int = 0
    model_config = {'extra': 'ignore', 'populate_by_name': True}

class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None
    model_config = {'extra': 'ignore'}
```

```python
# common/model/input.py — normalized message (shared across apps)
class BotMessage(BaseModel):
    tp: Literal['telegram'] = 'telegram'
    chat_id: int
    user_id: int
    username: str
    text: str
    message_id: int
```

### Webhook Server
- Trello sends HEAD first to verify URL — must return 200
- On POST, extract `action.type` and `action.data.listAfter.id`
- For worker webhooks: only process events where a card enters that worker's `todo` list
- For orchestrator webhook (board-level): only process events where a card enters any known `done` list
- Push relevant action data into the correct agent's asyncio.Queue

---

---
---

# Coding Conventions

> **These conventions are project-agnostic. Apply them to all FastAPI projects.**

---

## Project Structure

```
_devops/
    buildspec.yml
    Dockerfile

app/
    core/
        __init__.py
        config.py          # pydantic-settings, env + config.json loading
        middleware.py       # CORS, logging, error handling middleware
        resource.py         # shared resources (Trello httpx client, Telegram httpx client, GitHub httpx client)
        security.py         # auth utilities, token validation

    common/
        crud/
            create.py
            read.py
            update.py
            delete.py
        model/
            input.py
            output.py
        route.py
        __init__.py

    apps/
        trello/
            crud/
                create.py
                read.py
                update.py
                delete.py
            model/
                input.py
                output.py
            route.py          # main views
            webhooks.py       # additional views in separate files
            __init__.py

        agent/
            crud/
                create.py
                read.py
                update.py
                delete.py
            model/
                input.py
                output.py
            route.py
            __init__.py

        git_manager/
            crud/
                create.py
                read.py
                update.py
                delete.py
            model/
                input.py
                output.py
            route.py
            __init__.py

        bot/
            crud/
                create.py
                read.py
                update.py
                delete.py
            model/
                input.py
                output.py
            route.py
            __init__.py

        hook/
            crud/
                create.py
                read.py
                update.py
                delete.py
            model/
                input.py
                output.py
            route.py
            __init__.py

    main.py                 # FastAPI app creation, lifespan, router includes

repos/                      # cloned repos (gitignored)
config.json
config.json.example
.env
.env.example
requirements.txt
README.md
CLAUDE.md
LICENSE
.gitignore
```

---

## App Rules

1. **The project is built using FastAPI.**

2. **Separate code into apps.** Each app lives in `app/apps/{app_name}/`.

3. **An app has domain-driven content.** Each app owns one bounded context. An app does NOT reach into another app's internals.

4. **Every app has this internal structure:**

    ```
    app_name/
        crud/
            create.py       # create operations
            read.py         # read/query operations
            update.py       # update operations
            delete.py       # delete operations
        model/
            input.py        # Pydantic models for incoming data
            output.py       # Pydantic models for outgoing data
        route.py            # main app views (router)
        other_views.py      # additional views in separate .py files
        __init__.py
    ```

5. **App contents are private to the app.** No app imports from another app. Shared resources go in the `common` app (`app/common/`), which has the same structure as a regular app but its contents are shared among all apps.

6. **`app/core/` contains framework-level concerns:**
    - `config.py` — pydantic-settings, all env and config.json loading
    - `middleware.py` — CORS, request logging, error handling middleware
    - `resource.py` — shared resources (Trello httpx client, Telegram httpx client, GitHub httpx client, connection pools, singletons)
    - `security.py` — authentication utilities, token validation, guards

7. **`_devops/` contains deployment files:**
    - `buildspec.yml` — CI/CD build specification
    - `Dockerfile` — container build instructions

---

## Pydantic Model Conventions

All Pydantic models follow strict naming and typing conventions:

### Naming

| Direction | Suffix | Example               |
|-----------|--------|-----------------------|
| Input     | `In`   | `CardIn`              |
| Output    | `Out`  | `CardOut`             |

### HTTP-Bound Models (used directly in route signatures)

Models used in views for **request validation** end with **HTTP method + `In`**:

```python
class CardPostIn(BaseModel):     # POST request body
    ...

class CardPutIn(BaseModel):      # PUT request body
    ...

class CardPatchIn(BaseModel):    # PATCH request body
    ...
```

Models used in views for **response validation** end with **HTTP method + `Out`**:

```python
class CardPostOut(BaseModel):    # POST response
    ...

class CardGetOut(BaseModel):     # GET response
    ...

class CardDeleteOut(BaseModel):  # DELETE response
    ...
```

### Annotated Types

**All Pydantic models MUST use `Annotated` for defining fields** instead of bare `int`, `str`, `Decimal`, etc.

```python
# ✅ CORRECT — always use Annotated
from typing import Annotated
from pydantic import BaseModel, Field

class CardPostIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255, description="Card title")]
    description: Annotated[str, Field(default="", max_length=5000, description="Task specification in markdown")]
    list_id: Annotated[str, Field(min_length=1, description="Target Trello list ID")]
    label_ids: Annotated[list[str], Field(default_factory=list, description="Trello label IDs")]

class CardGetOut(BaseModel):
    id: Annotated[str, Field(description="Trello card ID")]
    name: Annotated[str, Field(description="Card title")]
    url: Annotated[str, Field(description="Card URL on Trello")]
```

```python
# ❌ WRONG — never use bare types
class CardPostIn(BaseModel):
    name: str
    description: str = ""
    list_id: str
```

This applies to every single field in every single Pydantic model across the entire project, without exception.

---

## Additional Conventions

- **Async everywhere.** All route handlers, CRUD functions, and external API calls must be `async def`.
- **Type hints on everything.** All function signatures must have full type hints for arguments and return values.
- **No star imports.** Always import explicitly.
- **Docstrings on all public functions.** One-line summary minimum.
- **Constants in UPPER_SNAKE_CASE.** Defined at module level or in config.
- **Errors raise HTTPException** in routes, or custom exceptions defined in `common`.
- **Logging via `structlog` or stdlib `logging`.** No print statements.
