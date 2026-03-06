# Karavan

Turn Trello boards into autonomous AI agent workflows. Talk to an orchestrator via Telegram, it breaks work into Trello cards, worker agents pick them up and execute — writing code, reviewing PRs, researching ideas, or planning tasks.

```
You (Telegram) ←→ Orchestrator Agent
                        ↓
                  Trello Boards
          ┌─────────┼──────────┐
     api-bot    static-bot   research
         ↓          ↓           ↓
  scout→coder    static-    triage→deep
  →tester→       coder      →factory→
  elegance→                 validation→
  reviewer                  verdict
```

## One Framework, Many Workflows

Karavan isn't just for code. The same worker engine handles coding, reviewing, research, planning, and anything in between — configured per agent, not hardcoded.

Three config axes define what each worker does:

| Axis                | Options                               | Controls                                                                 |
|---------------------|---------------------------------------|--------------------------------------------------------------------------|
| **`repo_access`**   | `write` · `read` · `none`             | Whether the agent clones a repo, and if it can push changes              |
| **`output_mode`**   | `pr` · `comment` · `cards` · `update` | What the agent produces — a PR, analysis, new tasks, or enriched content |
| **`allowed_tools`** | Any subset of SDK tools               | What the agent can do during execution                                   |

Mix and match to create any agent type:

| Agent      | repo_access  | output_mode  | What it does                                            |
|------------|--------------|--------------|---------------------------------------------------------|
| Scout      | `read`       | `update`     | Reads code, maps the codebase, plans the approach       |
| Coder      | `write`      | `pr`         | Writes code, opens GitHub PRs                           |
| Tester     | `write`      | `pr`         | Writes tests, pushes to the same branch                 |
| Reviewer   | `read`       | `update`     | Reads code, posts analysis on the card                  |
| Planner    | `none`       | `cards`      | Breaks work into sub-tasks as new Trello cards          |
| Researcher | `none`       | `update`     | Enriches cards with analysis — chains with other agents |

### Work Across Multiple Boards

Each Trello board is an independent workspace with its own workers, lists, and rules. The orchestrator works across all of them, routing tasks to the right board based on the type of work.

A coding board can have a full pipeline — scout analyzes the codebase, coder implements, tester writes tests, elegance refactors, reviewer validates. A research board can have agents that triage ideas, do deep research, generate concepts, validate feasibility, and render a final verdict. A frontend board can be a single coder. Each board has its own `max_bounces` to control pipeline depth.

Boards are isolated but connected through the orchestrator — you describe what you need, and work flows to the right place.

### Agent Routing

Workers route cards to other workers on the same board using the `route_card` tool. This enables pipelines: scout → coder → tester → reviewer. Each hop adds a `[karavan:bounce]` comment; a per-board `max_bounces` limit (default 3) prevents runaway loops.

## Quick Start

### Prerequisites

- Python 3.12+, a VPS with HTTPS, an SSH key with GitHub push access
- API credentials: Trello (key + secret + token), Anthropic, Telegram (bot token), GitHub (PAT)

### Setup

```bash
git clone https://github.com/yourusername/karavan.git && cd karavan
cp .env.example .env          # fill in API credentials
cp config.json.example config.json  # configure boards and workers
```

### Trello Board Setup

1. Create a board with four lists: **Todo**, **Doing**, **Done**, **Failed**
2. Create one **label** per worker agent (used for routing cards)
3. Get the board ID, list IDs, and label IDs via the Trello API:
   ```bash
   # Board ID (need the full 24-char hex, not the short URL slug)
   curl "https://api.trello.com/1/boards/SHORT_ID?key={key}&token={token}&fields=id"

   # List IDs
   curl "https://api.trello.com/1/boards/{board_id}/lists?key={key}&token={token}"

   # Label IDs
   curl "https://api.trello.com/1/boards/{board_id}/labels?key={key}&token={token}"
   ```

### Config

Simple `config.json` — one board, one coder:

```json
{
  "model": "claude-opus-4-6",
  "boards": {
    "static-bot": {
      "board_id": "...",
      "description": "Static site development board.",
      "failed_list_id": "...",
      "lists": { "todo": "...", "doing": "...", "done": "..." },
      "workers": {
        "static-coder": {
          "label_id": "...",
          "repo": "git@github.com:you/your-site.git",
          "branch_prefix": "static-coder",
          "base_branch": "dev",
          "system_prompt": "You are a frontend developer. Follow CLAUDE.md coding conventions."
        }
      }
    }
  },
  "orchestrator": {
    "repos": ["git@github.com:you/your-site.git"],
    "base_branch": "dev",
    "system_prompt": "@prompts/orchestrator.md"
  }
}
```

Multi-board setup — coding pipeline + research pipeline:

```json
{
  "model": "claude-opus-4-6",
  "boards": {
    "api-bot": {
      "board_id": "...",
      "description": "API development board. Pipeline: scout → coder → tester → elegance → reviewer.",
      "failed_list_id": "...",
      "max_bounces": 20,
      "lists": { "todo": "...", "doing": "...", "done": "..." },
      "workers": {
        "api-scout": {
          "label_id": "...",
          "repo": "git@github.com:you/your-api.git",
          "base_branch": "dev",
          "repo_access": "read",
          "output_mode": "update",
          "allowed_tools": ["Read", "Glob", "Grep", "Bash"],
          "system_prompt": "@prompts/api-bot/api-scout.md",
          "sdk_timeout": 600,
          "max_turns": 20
        },
        "api-coder": {
          "label_id": "...",
          "repo": "git@github.com:you/your-api.git",
          "branch_prefix": "agent/api",
          "base_branch": "dev",
          "system_prompt": "@prompts/api-bot/api-coder.md"
        },
        "api-tester": {
          "label_id": "...",
          "repo": "git@github.com:you/your-api.git",
          "branch_prefix": "agent/api",
          "base_branch": "dev",
          "output_mode": "pr",
          "system_prompt": "@prompts/api-bot/api-tester.md",
          "sdk_timeout": 1200
        },
        "api-elegance": {
          "label_id": "...",
          "repo": "git@github.com:you/your-api.git",
          "branch_prefix": "agent/api",
          "base_branch": "dev",
          "output_mode": "pr",
          "system_prompt": "@prompts/api-bot/api-elegance.md",
          "sdk_timeout": 900,
          "max_turns": 30
        },
        "api-reviewer": {
          "label_id": "...",
          "repo": "git@github.com:you/your-api.git",
          "base_branch": "dev",
          "repo_access": "read",
          "output_mode": "update",
          "allowed_tools": ["Read", "Glob", "Grep", "Bash", "WebFetch"],
          "system_prompt": "@prompts/api-bot/api-reviewer.md",
          "sdk_timeout": 900,
          "max_turns": 20
        }
      }
    },
    "research": {
      "board_id": "...",
      "description": "Research board for ideation and brainstorming.",
      "failed_list_id": "...",
      "max_bounces": 10,
      "lists": { "todo": "...", "doing": "...", "done": "..." },
      "workers": {
        "triage": {
          "label_id": "...",
          "repo_access": "none",
          "output_mode": "update",
          "system_prompt": "@prompts/research/triage.md",
          "sdk_timeout": 900,
          "max_turns": 10
        },
        "deep": {
          "label_id": "...",
          "repo_access": "none",
          "output_mode": "update",
          "system_prompt": "@prompts/research/deep.md",
          "sdk_timeout": 900,
          "max_turns": 10
        },
        "factory": {
          "label_id": "...",
          "repo_access": "none",
          "output_mode": "update",
          "system_prompt": "@prompts/research/factory.md",
          "sdk_timeout": 900,
          "max_turns": 10
        },
        "validation": {
          "label_id": "...",
          "repo_access": "none",
          "output_mode": "update",
          "system_prompt": "@prompts/research/validation.md",
          "sdk_timeout": 900,
          "max_turns": 10
        },
        "verdict": {
          "label_id": "...",
          "repo_access": "none",
          "output_mode": "update",
          "system_prompt": "@prompts/research/verdict.md",
          "sdk_timeout": 900,
          "max_turns": 10
        }
      }
    }
  },
  "orchestrator": {
    "repos": ["git@github.com:you/your-api.git"],
    "base_branch": "dev",
    "system_prompt": "@prompts/orchestrator.md"
  }
}
```

System prompts support `@path/to/file.md` syntax to load from file. Worker names must be unique across all boards.

### Deploy

```bash
# Edit _devops/Caddyfile with your domain
cd _devops && docker compose up -d
```

Caddy handles HTTPS automatically. On startup, Karavan clones repos, starts agents, and registers all webhooks.

Or run directly:

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Use It

Message your bot on Telegram:

> Add a health check endpoint that returns the app version

The orchestrator reads your repos, proposes a plan, and on approval creates Trello cards. Workers pick them up, execute, and report results back to you in Telegram.

## How It Works

- **Trello is the message bus.** Cards move `todo → doing → done` as agents process them. No database, no message queue.
- **Workers are stateless and composable.** One `WorkerAgent` class handles all agent types — behavior is driven by config.
- **The orchestrator has memory.** Multi-turn conversation via Telegram with read access to all repos.
- **Webhooks drive everything.** No polling. Trello and Telegram push events to Karavan.
- **Built-in resilience.** Failed cards retry up to 3 times. Routing loops are killed by bounce limits.

## Tech Stack

Python 3.12+ · FastAPI · Claude Agent SDK · Trello API · Telegram Bot API · GitHub API · httpx

## License

MIT
