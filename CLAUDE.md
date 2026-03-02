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
- Creates Trello cards via custom MCP tools (`create_trello_card`, `list_workers`, `get_card_status`, `get_worker_cards`) exposed to the SDK agent through `create_sdk_mcp_server`
- Monitors `done` lists via a single board-level Trello webhook (filters by known `done` list IDs)
- On card completion: extracts PR link from card comments, checks for newly unblocked dependent cards, sends rich Telegram notification with PR URL
- Tracks `chat_id` from actual conversations (not just `user_id`) for correct Telegram notifications in both private and group chats
- Can request revisions by moving cards back to `todo` with a comment

**Worker (N per project):**
- Watches its own `todo` list via a list-level Trello webhook
- Deduplicates cards via an in-memory `_processed_cards` set — skips cards already being worked on
- Picks up a card → moves to `doing`
- Uses `query()` (one-shot, stateless) scoped to its cloned repo directory via `cwd`, with a rich prompt template including repo/branch context, explicit rules (no git commands, write code don't explain), and completion instructions
- Validates agent output: if no code changes produced, comments failure on card and moves to `failed` list instead of creating an empty PR
- Commits to a branch, pushes, opens PR via GitHub API
- Comments PR link and cost (`$X.XXXX`) on the Trello card
- Sends real-time progress updates to Telegram via edit-in-place messages (tool use summaries every 10s)
- Moves card to `done`
- On failure: tracks retry count via `[karavan:fail]` comment prefix, retries up to `MAX_RETRIES=3`, then moves to `failed` list

### Event Flow

```
1. User → Telegram: "Add appointment reminders"
2. Telegram POSTs to /telegram/{secret} → BotMessage pushed to orchestrator's asyncio.Queue
3. Orchestrator reads repos, proposes plan → sends response via Telegram sendMessage
4. User approves (or adjusts) via inline keyboard → another webhook POST
5. Orchestrator creates Trello cards via MCP tools (create_trello_card) in workers' todo lists
6. Trello webhook fires → POST /webhook/{agent_name} (verified via HMAC-SHA1 signature)
7. Worker agent:
   a. Checks dedup set — skips if card already in progress
   b. Moves card to doing
   c. Sends initial progress message to Telegram (edit-in-place)
   d. git pull origin {base_branch}
   e. git checkout -B {branch_prefix}/card-{id} (idempotent, handles retries)
   f. Claude Agent SDK query() with rich prompt (repo context, rules, card description)
   g. Streams progress updates to Telegram every 10s (tool use summaries)
   h. Validates changes — if no diff, comments failure, moves to failed list
   i. git commit + push
   j. Opens GitHub PR via API
   k. Comments PR link + cost on Trello card
   l. Moves card to done
   m. On failure: increments retry counter (via comments), retries up to 3x, then moves to failed list
8. Orchestrator board webhook detects card moved to done → extracts PR link from comments → checks for unblocked dependent cards → notifies user via Telegram with PR URL
```

### Webhook Strategy

- **Workers** register a list-level webhook on their `todo` list. Only fires when cards enter that list.
- **Orchestrator** registers a single board-level webhook. Filters incoming events by `action.data.listAfter.id` matching any known `done` list ID. One webhook instead of N — simpler to manage, fewer API calls on startup, automatically picks up new lists.
- **Deduplication on startup:** On startup, fetches all existing webhooks for the Trello token. Skips registration if an identical webhook exists. Deletes stale `karavan-*` webhooks (old URLs, removed agents). Prevents duplicate webhooks from accumulating across restarts.
- **Payload verification:** All incoming webhook POSTs are verified via `HMAC-SHA1(trello_api_secret, body + callback_url)` against the `x-trello-webhook` header. Invalid signatures are logged and silently accepted (return 200 to prevent Trello retries).

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
TRELLO_API_SECRET=            # Trello OAuth secret, used for webhook HMAC-SHA1 signature verification
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
      "base_branch": "main",
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
      "base_branch": "main",
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

### v0.1 — MVP (done)

- FastAPI webhook server receiving Trello events
- Trello async client (cards, lists, move, comment, webhook registration)
- Worker agent: webhook → Claude Agent SDK → git branch → push → PR → comment on card
- Orchestrator agent: Telegram bot → plan features → create Trello cards
- Config from `.env` + `config.json`
- Logging to stdout

### v0.2 — Usable (done)

- Card dependency tracking (orchestrator parses `## Dependencies` sections, unblocks cards when deps complete)
- Orchestrator watches `done` lists and reports progress via Telegram (with PR links)
- Retry logic: on agent failure, comment `[karavan:fail]` on card, retry up to 3x, then move to `failed` list
- Agent system prompts loaded from config
- GitHub PR creation via API with card link in PR body
- Orchestrator MCP tools for card creation (`create_trello_card`, `list_workers`, `get_card_status`, `get_worker_cards`)
- Worker change validation (no empty PRs)
- Card deduplication via in-memory processed set
- Webhook deduplication on startup (reconcile existing, delete stale)
- Trello API rate limiting (sliding-window + 429 retry with backoff)
- Trello webhook payload HMAC-SHA1 signature verification
- Rich worker prompt template (repo context, rules, completion instructions)
- Configurable `base_branch` per agent (default: `main`)
- Idempotent branch creation (`git checkout -B`)
- Real-time worker progress feedback via Telegram edit-in-place messages
- Cost tracking per card/agent, exposed via health endpoint
- Rich health endpoint (per-agent status, queue depth, cost summaries)
- Improved MarkdownV2 escaping (code blocks, inline code, links, bold)
- Chat ID tracking from conversations for correct Telegram notifications in groups

### v0.3 — Polish

- Docker + docker-compose
- Caddy HTTPS setup guide
- Multiple projects/boards support
- Card templates

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
- BaseAgent class: async queue, lifecycle (start/stop), card pickup logic, per-agent status tracking (running, queue depth, last activity, cards processed)
- WorkerAgent: inherits BaseAgent, uses `query()` (one-shot) scoped to a repo via `cwd`, handles the full card lifecycle (todo → doing → done), validates agent output, retries with counter (max 3), deduplicates via `_processed_cards` set, sends real-time progress to Telegram
- OrchestratorAgent: inherits BaseAgent, uses `ClaudeSDKClient` (multi-turn) for persistent conversation, connected to Telegram, creates/monitors cards via MCP tools, handles dependency tracking (parses `## Dependencies`, unblocks cards), extracts PR links from comments, tracks `chat_id` from conversations
- `tools.py`: MCP tool definitions (`create_trello_card`, `list_workers`, `get_card_status`, `get_worker_cards`) exposed to orchestrator SDK via `create_sdk_mcp_server`
- Agent registry: loads agents from config.json, starts them on app lifespan

### `git_manager` app
- Git operations via async subprocess: clone, pull, checkout, commit, push
- GitHub API client: create PR, link PR to Trello card
- SSH key configuration via GIT_SSH_COMMAND env var
- Repo management: clone on first run, pull on subsequent tasks

### `bot` app
- Telegram webhook route: receives POSTs at `/telegram/{secret}`, parses into Pydantic models, pushes `BotMessage` to orchestrator's queue
- Telegram send helpers: `send_message`, `edit_message`, `send_typing_action` via shared httpx client
- MarkdownV2 conversion: tokenizer-based approach handling fenced code blocks, inline code, links, bold, with proper escaping per context; `strip_markdown_v2` fallback for when Telegram rejects the formatted message
- Webhook registration on app startup via `setWebhook` API call
- Allowed user ID filtering from config

### `hook` app
- Route: `HEAD /webhook/{agent_name}` — Trello verification
- Route: `POST /webhook/{agent_name}` — receives Trello events, verifies HMAC-SHA1 signature via `x-trello-webhook` header, filters for card moves to `todo`/`done` lists, pushes to the correct agent's async queue
- Route: `GET /health` — returns per-agent status (running, queue depth, last activity, cards processed), per-agent cost summaries (cost, tokens, executions), and aggregate cost totals

### `common` app
- Shared Pydantic models used across apps (`BotMessage`, etc.)
- `cost.py`: `CostTracker` singleton — records per-agent cost/token usage from `ResultMessage`, exposes summaries for the health endpoint
- `progress.py`: `ProgressTracker` — edit-in-place Telegram messages during worker execution, streams tool use summaries (Read/Edit/Bash/Glob/Grep), flushes every 10s with 10s minimum gap between edits
- Shared utilities (logging helpers, async helpers)
- Shared exceptions

---

## Implementation Notes

### Trello Client
- Shared httpx async client lives in `core/resource.py` as a singleton with base URL `https://api.trello.com/1/`
- All requests include `key` and `token` query params from config
- Rate limiting via `RateLimitedTransport` (custom `httpx.AsyncBaseTransport`): proactive sliding-window (90 requests per 10s, under Trello's 100 limit), reactive 429 retry with exponential backoff (respects `retry-after` header, up to 3 retries)
- Webhook reconciliation on startup: fetches existing webhooks, skips already-registered ones, deletes stale `karavan-*` webhooks, registers missing ones
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

**Orchestrator uses `ClaudeSDKClient` (multi-turn, persistent context) with MCP tools:**
```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, create_sdk_mcp_server

# MCP server exposes Trello operations as tools
mcp_server = create_sdk_mcp_server("karavan_orchestrator", tools=[
    create_trello_card, list_workers, get_card_status, get_worker_cards
])

client = ClaudeSDKClient(options=ClaudeAgentOptions(
    add_dirs=["/path/to/repos/orchestrator/repo-a", "/path/to/repos/orchestrator/repo-b"],
    allowed_tools=["Read", "Glob", "Grep",
                   "create_trello_card", "list_workers", "get_card_status", "get_worker_cards"],
    system_prompt={
        "type": "preset",
        "preset": "claude_code",
        "append": orchestrator_system_prompt,
    },
    permission_mode="bypassPermissions",
    setting_sources=["project"],
    mcp_servers={"karavan": mcp_server},
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
- Always pull `base_branch` (configurable per agent, default `main`) before creating a new branch
- Branch creation uses `git checkout -B` (idempotent — resets branch if it already exists from a previous failed run)
- Change validation: after agent runs, checks `git diff --cached --quiet` — if no changes, skips commit/push/PR and reports failure
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
- MarkdownV2 conversion via regex tokenizer: handles fenced code blocks (preserves language tag, only escapes `` ` `` and `\` inside), inline code, markdown links (`[text](url)`), bold (`**text**` → `*text*`), and plain text (escapes all special chars). Falls back to `strip_markdown_v2` (plain text) if Telegram rejects the formatted message.
- `editMessageText` for in-place progress updates during worker execution
- `sendChatAction` (typing indicator) while orchestrator is thinking

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
- On POST, verify HMAC-SHA1 signature from `x-trello-webhook` header using `trello_api_secret` against `body + callback_url`. Invalid signatures are logged as warnings but still return 200 (to prevent Trello retries).
- Extract `action.type` and `action.data.listAfter.id`
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
