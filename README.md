# Karavan

A caravan of camels (agents)

Turns Trello boards into a communication protocol between AI coding agents. You talk to an orchestrator via Telegram, it breaks work into Trello cards, worker agents pick them up, write code, push branches, and open PRs — autonomously.

```
You (Telegram) ←→ Orchestrator Agent
                        ↓
                  Trello Board
                        ↓
              ┌─────────┼─────────┐
              ↓         ↓         ↓
          Worker A   Worker B   Worker C
           ↓           ↓          ↓
         repo A      repo B     repo C
```

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
3. Copy each list's ID — open a list, add `.json` to the Trello URL in your browser to find IDs, or use the Trello API:
   ```
   curl "https://api.trello.com/1/boards/{board_id}/lists?key={key}&token={token}"
   ```
4. Copy the **board ID** (visible in the board URL: `trello.com/b/{board_id}/...`)

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

Edit `config.json` with your Trello list IDs, repos, and agent system prompts:

```json
{
  "agents": {
    "api": {
      "type": "worker",
      "lists": {
        "todo": "paste_trello_list_id",
        "doing": "paste_trello_list_id",
        "done": "paste_trello_list_id"
      },
      "repo": "git@github.com:you/your-api.git",
      "branch_prefix": "agent/api",
      "system_prompt": "You are a FastAPI backend developer. Follow existing patterns in the codebase."
    },
    "frontend": {
      "type": "worker",
      "lists": {
        "todo": "paste_trello_list_id",
        "doing": "paste_trello_list_id",
        "done": "paste_trello_list_id"
      },
      "repo": "git@github.com:you/your-frontend.git",
      "branch_prefix": "agent/frontend",
      "system_prompt": "You are a frontend developer. Use the existing component library."
    },
    "orchestrator": {
      "type": "orchestrator",
      "board_id": "paste_trello_board_id",
      "repos": [
        "git@github.com:you/your-api.git",
        "git@github.com:you/your-frontend.git"
      ],
      "system_prompt": "You are an engineering lead. Break features into clear tasks for worker agents."
    }
  }
}
```

**Key points:**
- Each worker gets **one repo** — it clones, branches, and pushes to it automatically
- The orchestrator gets **all repos** as read-only context so it can plan across the full codebase
- `branch_prefix` controls branch names: `agent/api/card-abc123`
- `system_prompt` tells the Claude agent its role and conventions
- You can have as many workers as you want — one per repo, or multiple workers on the same repo

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
4. Workers pick up cards, write code, push branches, and open PRs
5. Results get reported back to you in Telegram

## How It Works

- **Trello is the message bus.** Cards move between lists (`todo` → `doing` → `done`) as agents process them.
- **Workers are stateless.** Each card is a self-contained task. The agent clones fresh, branches, does the work, pushes, and opens a PR.
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
