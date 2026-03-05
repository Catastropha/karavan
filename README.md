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
| `update` | Append section to card description (`---` + `### agent_name`) | Research pipelines, spec enrichment |

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
| Improver | `read` | `update` | Reads code, appends enriched analysis to card |
| Researcher | `none` | `update` | Pure reasoning — each agent appends its section in a pipeline |

All three fields have backward-compatible defaults (`write`, `pr`, full tool list) — existing configs work without changes.

## Launch Guide

### 1. Prerequisites

- Python 3.12+
- A VPS or server with a public HTTPS URL (Trello and Telegram need to reach your webhooks)
- An SSH key on the server with push access to the GitHub repos your agents will work on

### 2. Get API Credentials

You need tokens from four services:

**Trello** — API key, secret, and token:
1. Go to https://trello.com/power-ups/admin
2. Click **New** to create a Power-Up (or use an existing one)
3. Copy the **API Key** → `TRELLO_API_KEY`
4. On the same page, copy the **API Secret** → `TRELLO_API_SECRET` (used for webhook signature verification)
5. Next to the API key there's a **Token** link — click it, authorize, copy the token → `TRELLO_TOKEN`

**Telegram** — bot token and your user ID:
1. Message [@BotFather](https://t.me/BotFather) on Telegram, run `/newbot`, follow the prompts → copy the bot token → `TELEGRAM_BOT_TOKEN`
2. Message [@userinfobot](https://t.me/userinfobot) to get your numeric user ID → `TELEGRAM_ALLOWED_USER_IDS=[your_id]`

**Anthropic** — API key:
1. Go to https://console.anthropic.com/settings/keys and create a key → `ANTHROPIC_API_KEY`
2. Note: this is separate from a claude.ai subscription — you need to add credits on the API console, which is pay-per-use

**GitHub** — personal access token (for creating PRs via the API):
- **Personal repos:** GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → generate with `repo` scope
- **Organization repos:** Use a **Fine-grained token** instead — set the resource owner to your org, select specific repos, and grant **Contents** (read/write) + **Pull requests** (read/write) permissions. Your org admin may need to approve it.
- Copy the token → `GITHUB_TOKEN`

**SSH key** — for git operations (clone, push):
1. Generate on the VPS: `ssh-keygen -t ed25519 -C "karavan" -f ~/.ssh/id_ed25519` (no passphrase)
2. `chmod 600 ~/.ssh/id_ed25519`
3. Add the public key (`cat ~/.ssh/id_ed25519.pub`) to GitHub — either in your account's SSH keys or as a deploy key on each repo (with write access enabled)
4. Test: `ssh -T git@github.com`

### 3. Set Up the Trello Board

1. Create a new Trello board for your project
2. Create three shared lists: `Todo`, `Doing`, `Done` — all workers on the board share them
3. Create one **Failed** list for cards that exhaust retries or bounces
4. Get the **board ID** — the short slug in the URL (`trello.com/b/AbCdEfGh/my-board` → `AbCdEfGh`) is NOT the board ID. You need the full 24-character hex ID. Get it via the API:
   ```bash
   curl "https://api.trello.com/1/boards/AbCdEfGh?key={key}&token={token}&fields=id,name"
   ```
   This returns the full ID:
   ```json
   { "id": "6830abc123def456abc12300", "name": "My Board" }
   ```
   Use the `id` value → `board_id` in your config.
5. Get all **list IDs** using the API:
   ```bash
   curl "https://api.trello.com/1/boards/{board_id}/lists?key={key}&token={token}"
   ```
   This returns each list with its ID:
   ```json
   [
     { "id": "6830abc123def...", "name": "Todo" },
     { "id": "6830abc123def...", "name": "Doing" },
     { "id": "6830abc123def...", "name": "Done" },
     { "id": "6830abc123def...", "name": "Failed" }
   ]
   ```
   Map these to your `config.json` under the board's `lists.todo`, `lists.doing`, `lists.done`, and `failed_list_id`.
6. Create one **label** per worker agent — this is how Karavan routes cards to the right worker. Open the board menu → Labels → create a label for each agent (e.g. "api-coder", "reviewer", "triage").
7. Get all **label IDs** using the API:
   ```bash
   curl "https://api.trello.com/1/boards/{board_id}/labels?key={key}&token={token}"
   ```
   This returns each label with its ID:
   ```json
   [
     { "id": "69a95cfe17445...", "name": "api-coder", "color": "green" },
     { "id": "69a95cd3bb6b3...", "name": "reviewer", "color": "blue" }
   ]
   ```
   Map each label ID to the corresponding worker's `label_id` in `config.json`. When the orchestrator creates a card, it assigns the label to route it to the correct worker.

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

Fill in `.env` with the credentials from step 2:

```bash
# Trello (from power-ups admin page)
TRELLO_API_KEY=
TRELLO_API_SECRET=
TRELLO_TOKEN=

# Anthropic (from console.anthropic.com)
ANTHROPIC_API_KEY=sk-ant-...

# Telegram (from BotFather + userinfobot)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_ALLOWED_USER_IDS=[your_numeric_user_id]

# Telegram webhook auth — generate with: openssl rand -hex 32
TELEGRAM_SECRET=

# Git / GitHub
GIT_SSH_KEY_PATH=/root/.ssh/id_ed25519
GITHUB_TOKEN=ghp_...

# Your server's public HTTPS URL (no trailing slash) — must match your Caddyfile domain
WEBHOOK_BASE_URL=https://agents.yourdomain.com
```

### 6. Configure Agents

Edit `config.json` with your Trello list IDs, repos, and agent definitions. Here are two examples:

#### Simple config — one board, one coder

The minimal setup: one Trello board with a single code worker and an orchestrator that talks to you via Telegram.

```json
{
  "model": "claude-sonnet-4-20250514",
  "boards": {
    "myproject": {
      "board_id": "6830abc123def456abc12300",
      "failed_list_id": "6830abc123def456abc12304",
      "lists": {
        "todo": "6830abc123def456abc12301",
        "doing": "6830abc123def456abc12302",
        "done": "6830abc123def456abc12303"
      },
      "workers": {
        "api": {
          "label_id": "69a95cfe1744507403503d6a",
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

Workers are grouped under `boards`. Each board maps to a Trello board and has its own `board_id`, `failed_list_id`, and shared `lists` (all workers on the board share the same todo/doing/done lists). Each worker has a `label_id` that routes cards to it — the orchestrator assigns the label when creating cards. The orchestrator sits at the top level and works across all boards. The worker uses the defaults (`repo_access: "write"`, `output_mode: "pr"`, full tool list), so you don't need to specify them.

#### Advanced config — multiple boards, mixed agent types

A richer setup: a coding board with a coder and reviewer, plus a research board where agents route cards between each other (triage → deep analysis) with bounce protection.

```json
{
  "model": "claude-sonnet-4-20250514",
  "boards": {
    "backend": {
      "board_id": "6830abc123def456abc12300",
      "failed_list_id": "6830abc123def456abc12310",
      "lists": {
        "todo": "6830abc123def456abc12301",
        "doing": "6830abc123def456abc12302",
        "done": "6830abc123def456abc12303"
      },
      "workers": {
        "api": {
          "label_id": "69a95cfe1744507403503d6a",
          "repo": "git@github.com:you/your-api.git",
          "branch_prefix": "agent/api",
          "base_branch": "main",
          "system_prompt": "You are a FastAPI backend developer. Follow existing patterns in the codebase."
        },
        "reviewer": {
          "label_id": "69a95cd3bb6b371df787ce5a",
          "repo_access": "read",
          "output_mode": "comment",
          "allowed_tools": ["Read", "Glob", "Grep"],
          "repo": "git@github.com:you/your-api.git",
          "base_branch": "main",
          "system_prompt": "You are a senior code reviewer. Read the codebase, analyze the task, and provide detailed feedback as your response."
        }
      }
    },
    "research": {
      "board_id": "6830abc123def456abc12311",
      "failed_list_id": "6830abc123def456abc12318",
      "max_bounces": 5,
      "lists": {
        "todo": "6830abc123def456abc12312",
        "doing": "6830abc123def456abc12313",
        "done": "6830abc123def456abc12314"
      },
      "workers": {
        "triage": {
          "label_id": "69a9421a0835678209dfd72f",
          "repo_access": "none",
          "output_mode": "update",
          "system_prompt": "You are a triage agent. Classify and enrich incoming ideas."
        },
        "deep": {
          "label_id": "69a94284e13a6a976d9dea55",
          "repo_access": "none",
          "output_mode": "update",
          "system_prompt": "You are a deep research agent. Expand on triaged ideas with detailed analysis."
        }
      }
    }
  },
  "orchestrator": {
    "repos": [
      "git@github.com:you/your-api.git"
    ],
    "base_branch": "main",
    "system_prompt": "You are an engineering lead. Route coding tasks to the backend board and research tasks to the research board."
  }
}
```

In this setup:
- **backend** board — has a **coder** (`api`) that writes code and opens PRs, and a **reviewer** that reads code and posts analysis as Trello comments
- **research** board — has a **triage** agent and a **deep** analysis agent. Both use `output_mode: "update"`, so each agent appends its section to the card description (delimited by `---` + `### agent_name`) — prior agents' work is preserved. Agents can route cards to each other via the `route_card` MCP tool. `max_bounces: 5` prevents runaway routing loops — after 5 bounces the card moves to the failed list.
- **orchestrator** — works across all boards, creates cards and routes tasks to the right agent

Worker names must be unique across all boards.

### 7. Deploy to a VPS

Trello and Telegram require HTTPS webhook URLs, so you need a server with a public IP and a domain name pointed at it.

**Prerequisites on the VPS:**
- Docker and Docker Compose installed
- DNS A record pointing your domain (e.g. `agents.yourdomain.com`) to the VPS IP
- Ports 80 and 443 open in your firewall
- An SSH key (`~/.ssh/id_ed25519`) with push access to your GitHub repos

**Deploy:**

```bash
git clone https://github.com/yourusername/karavan.git /opt/karavan
cd /opt/karavan

cp .env.example .env              # fill in all secrets
cp config.json.example config.json # fill in board/worker config
```

Edit `_devops/Caddyfile` — replace `agents.yourdomain.com` with your actual domain:

```
agents.yourdomain.com {
    reverse_proxy karavan:8000
}
```

Make sure `WEBHOOK_BASE_URL` in `.env` matches the domain in your Caddyfile.

Start everything:

```bash
cd _devops
docker compose up -d
```

Caddy automatically provisions Let's Encrypt HTTPS certificates. Karavan starts and on startup automatically:
1. Creates HTTP clients for Trello, Telegram, and GitHub
2. Clones all configured repos into `repos/`
3. Starts agent run loops
4. Registers Trello webhooks on each worker's `todo` list and the orchestrator's board
5. Registers the Telegram webhook with your bot

**Useful commands:**

```bash
docker compose -f _devops/docker-compose.yml build karavan      # rebuild after code changes
docker compose -f _devops/docker-compose.yml up -d karavan      # start (or restart with new image)
docker compose -f _devops/docker-compose.yml logs -f karavan    # follow app logs
docker compose -f _devops/docker-compose.yml restart karavan     # restart after config change
docker compose -f _devops/docker-compose.yml down                # stop everything
```

**Without Docker** (alternative — run directly):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then put Caddy or nginx in front for HTTPS.

### 8. Talk to It

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
