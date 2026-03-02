# Karavan

A caravan of camels (agents)

Turns Trello boards into a communication protocol between AI agents. You talk to an orchestrator via Telegram, it breaks work into Trello cards, worker agents pick them up and execute them — writing code, analyzing repos, creating sub-tasks, or refining specs — autonomously.

```
You (Telegram) ←→ Orchestrator Agent
                        ↓
                  Trello Board
                        ↓
              ┌─────────┼─────────┐
              ↓         ↓         ↓
          Worker A   Worker B   Worker C
          (coder)   (reviewer) (planner)
           ↓           ↓          ↓
         repo A      repo A     Trello
         (write)     (read)     (cards)
```

## Configurable Agent Behaviors

Workers aren't limited to writing code. Each worker's behavior is defined by three orthogonal config axes that combine freely:

**`repo_access`** — does the agent need a repository?

| Mode | What happens | Use case |
|------|-------------|----------|
| `write` | Clone, pull, branch, commit, push | Coders — write code, open PRs |
| `read` | Clone, pull (read-only context) | Reviewers — analyze code |
| `none` | No git operations | Planners — pure reasoning |

**`output_mode`** — what does the agent produce?

| Mode | What happens on completion | Use case |
|------|---------------------------|----------|
| `pr` | Commit, push, open GitHub PR | Code changes |
| `comment` | Post analysis as a Trello card comment | Reviews, feedback |
| `cards` | Create new Trello cards via MCP tools | Task breakdown, planning |
| `update` | Rewrite the card's description | Spec refinement |

**`allowed_tools`** — what the agent can do during execution

| Profile | Tools | Use case |
|---------|-------|----------|
| Full coding | `Read, Write, Edit, Bash, Glob, Grep` | Code workers (default) |
| Read-only | `Read, Glob, Grep` | Reviewers, analysts |
| MCP-only | `list_workers, create_trello_card, ...` | Orchestrator, card creators |

These combine into different agent personas:

| Agent | repo_access | output_mode | Description |
|-------|-------------|-------------|-------------|
| Coder | `write` | `pr` | Writes code, opens PRs |
| Reviewer | `read` | `comment` | Reads code, posts analysis |
| Critic | `read` | `comment` | Evaluates architecture, design, and quality |
| Improver | `read` | `update` | Refines vague card specs into detailed ones |

All three fields have backward-compatible defaults (`write`, `pr`, full tool list) — existing configs work without changes.

## Launch Guide

### 1. Prerequisites

- Python 3.12+
- A VPS or server with a public HTTPS URL (Trello and Telegram need to reach your webhooks)
- An SSH key on the server with push access to the GitHub repos your agents will work on

### 2. Get API Credentials

You need tokens from four services:

| Service | What to get | Where |
|---------|-------------|-------|
| **Trello** | API key + token | https://trello.com/power-ups/admin — generate a key, then click the token link to authorize |
| **Telegram** | Bot token | Message [@BotFather](https://t.me/BotFather) on Telegram, run `/newbot` |
| **Anthropic** | API key | https://console.anthropic.com/settings/keys |
| **GitHub** | Personal access token | GitHub → Settings → Developer settings → Personal access tokens (needs `repo` scope) |

You also need your **Telegram user ID** — message [@userinfobot](https://t.me/userinfobot) to get it.

### 3. Set Up the Trello Board

1. Create a new Trello board for your project
2. For **each worker agent** you want, create three lists: `Todo`, `Doing`, `Done`
   - Example: `API Todo`, `API Doing`, `API Done` for a backend worker
3. Create one **Failed** list shared across all agents
4. Copy each list's ID — open a list, add `.json` to the Trello URL in your browser to find IDs, or use the Trello API:
   ```
   curl "https://api.trello.com/1/boards/{board_id}/lists?key={key}&token={token}"
   ```
5. Copy the **board ID** (visible in the board URL: `trello.com/b/{board_id}/...`)

### 4. Clone and Install

```bash
git clone https://github.com/yourusername/karavan.git
cd karavan
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. Configure Environment

Copy the example files:

```bash
cp .env.example .env
cp config.json.example config.json
```

Fill in `.env` with your secrets:

```bash
TRELLO_API_KEY=your_trello_api_key
TRELLO_API_SECRET=your_trello_api_secret
TRELLO_TOKEN=your_trello_token
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_SECRET=any-random-string-you-make-up
TELEGRAM_ALLOWED_USER_IDS=[your_telegram_user_id]
GIT_SSH_KEY_PATH=/home/you/.ssh/id_ed25519
WEBHOOK_BASE_URL=https://agents.yourdomain.com
GITHUB_TOKEN=ghp_...
```

- `TELEGRAM_SECRET` — any random string. It becomes part of the webhook URL so only Telegram can reach it.
- `WEBHOOK_BASE_URL` — your server's public HTTPS URL, no trailing slash.
- `GIT_SSH_KEY_PATH` — path to the SSH private key that has push access to your repos.

### 6. Configure Agents

Edit `config.json` with your Trello list IDs, repos, and agent definitions. Here are two examples:

#### Simple config — one board, one coder

The minimal setup: one Trello board with a single code worker and an orchestrator that talks to you via Telegram.

```json
{
  "boards": {
    "myproject": {
      "board_id": "6830abc123def456abc12300",
      "failed_list_id": "6830abc123def456abc12304",
      "workers": {
        "api": {
          "lists": {
            "todo": "6830abc123def456abc12301",
            "doing": "6830abc123def456abc12302",
            "done": "6830abc123def456abc12303"
          },
          "repo": "git@github.com:you/your-api.git",
          "branch_prefix": "agent/api",
          "base_branch": "main",
          "system_prompt": "You are a FastAPI backend developer. Follow existing patterns in the codebase."
        }
      }
    }
  },
  "orchestrator": {
    "repos": [
      "git@github.com:you/your-api.git"
    ],
    "base_branch": "main",
    "system_prompt": "You are an engineering lead. Break features into clear tasks for worker agents."
  }
}
```

Workers are grouped under `boards`. Each board maps to a Trello board and has its own `board_id`, `failed_list_id`, and `workers`. The orchestrator sits at the top level and works across all boards. The worker uses the defaults (`repo_access: "write"`, `output_mode: "pr"`, full tool list), so you don't need to specify them.

#### Advanced config — multiple boards, mixed agent types

A richer setup across multiple Trello boards with specialized agents: coders, a reviewer, and a critic.

```json
{
  "boards": {
    "backend": {
      "board_id": "6830abc123def456abc12300",
      "failed_list_id": "6830abc123def456abc12310",
      "workers": {
        "api": {
          "lists": {
            "todo": "6830abc123def456abc12301",
            "doing": "6830abc123def456abc12302",
            "done": "6830abc123def456abc12303"
          },
          "repo": "git@github.com:you/your-api.git",
          "branch_prefix": "agent/api",
          "base_branch": "main",
          "system_prompt": "You are a FastAPI backend developer. Follow existing patterns in the codebase."
        },
        "reviewer": {
          "repo_access": "read",
          "output_mode": "comment",
          "allowed_tools": ["Read", "Glob", "Grep"],
          "lists": {
            "todo": "6830abc123def456abc12304",
            "doing": "6830abc123def456abc12305",
            "done": "6830abc123def456abc12306"
          },
          "repo": "git@github.com:you/your-api.git",
          "base_branch": "main",
          "system_prompt": "You are a senior code reviewer. Read the codebase, analyze the task, and provide detailed feedback as your response. Focus on correctness, edge cases, and adherence to existing patterns."
        }
      }
    },
    "frontend": {
      "board_id": "6830abc123def456abc12311",
      "failed_list_id": "6830abc123def456abc12318",
      "workers": {
        "static": {
          "lists": {
            "todo": "6830abc123def456abc12312",
            "doing": "6830abc123def456abc12313",
            "done": "6830abc123def456abc12314"
          },
          "repo": "git@github.com:you/your-frontend.git",
          "branch_prefix": "agent/static",
          "base_branch": "main",
          "system_prompt": "You are a frontend developer. Use the existing component library."
        },
        "critic": {
          "repo_access": "read",
          "output_mode": "comment",
          "allowed_tools": ["Read", "Glob", "Grep"],
          "lists": {
            "todo": "6830abc123def456abc12315",
            "doing": "6830abc123def456abc12316",
            "done": "6830abc123def456abc12317"
          },
          "repo": "git@github.com:you/your-frontend.git",
          "base_branch": "main",
          "system_prompt": "You are a frontend architecture critic. Evaluate component design, accessibility, performance patterns, and consistency with the design system."
        }
      }
    }
  },
  "orchestrator": {
    "repos": [
      "git@github.com:you/your-api.git",
      "git@github.com:you/your-frontend.git"
    ],
    "base_branch": "main",
    "system_prompt": "You are an engineering lead. You have workers across two boards: 'api' writes backend code, 'reviewer' analyzes backend code and posts feedback, 'static' writes frontend code, and 'critic' evaluates frontend architecture. Route work to the right agent."
  }
}
```

In this setup:
- **backend** board — has a **coder** (`api`) that writes code and opens PRs, and a **reviewer** that reads code and posts analysis as Trello comments
- **frontend** board — has a **coder** (`static`) working on a separate repo, and a **critic** that evaluates architecture and design patterns
- **orchestrator** — works across all boards, has read access to all repos, creates cards and routes tasks to the right agent

The orchestrator can chain them: assign a feature to the coder, and after the coder finishes, send a review card to the reviewer or a critique card to the critic. Worker names must be unique across all boards.

### 7. Set Up HTTPS

Trello and Telegram require HTTPS webhook URLs. The simplest option is [Caddy](https://caddyserver.com/), which handles certificates automatically:

```
# /etc/caddy/Caddyfile
agents.yourdomain.com {
    reverse_proxy localhost:8000
}
```

Or use nginx with Let's Encrypt, a cloud load balancer, or any other reverse proxy that terminates TLS.

### 8. Start Karavan

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

On startup, Karavan automatically:
1. Creates HTTP clients for Trello, Telegram, and GitHub
2. Clones all configured repos into `repos/`
3. Starts agent run loops
4. Registers Trello webhooks on each worker's `todo` list and the orchestrator's board
5. Registers the Telegram webhook with your bot

### 9. Talk to It

Open Telegram, find your bot, and send a message:

> Add a health check endpoint that returns the app version

The orchestrator will:
1. Read the relevant repos for context
2. Propose a plan
3. On your approval, create Trello cards in worker `todo` lists
4. Workers pick up cards, execute them (write code, analyze, plan, etc.)
5. Results get reported back to you in Telegram

## How It Works

- **Trello is the message bus.** Cards move between lists (`todo` → `doing` → `done`) as agents process them.
- **Workers are stateless.** Each card is a self-contained task. The agent picks it up, executes based on its config, and moves it to done.
- **Workers are composable.** The same `WorkerAgent` class handles coders, reviewers, planners, and more — behavior is driven by config, not code.
- **The orchestrator has memory.** It maintains a multi-turn conversation with you via Telegram and has read access to all repos for planning context.
- **Webhooks drive everything.** Trello notifies Karavan when cards move. Telegram notifies Karavan when you send a message. No polling.

## Tech Stack

- **Python 3.12+** / **FastAPI** / **uvicorn**
- **Claude Agent SDK** — gives each agent full Claude Code capabilities
- **Trello API** — state store and task queue
- **Telegram Bot API** — chat interface
- **GitHub API** — PR creation
- **httpx** — async HTTP client for all external APIs

## License

MIT
