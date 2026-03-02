# Karavan Improvements

## 1. Clear orchestrator context via Telegram

**Status:** Done

Implemented `/clear` Telegram command that resets the orchestrator's conversation context by switching to a new `session_id` (SDK supports per-session conversation isolation). The command flows through the existing queue so it's processed in order — no race conditions with in-flight queries.

## 2. Configurable agent behaviors (not just coders)

**Status:** Done

Implemented three orthogonal config axes on `WorkerAgentConfig` — `repo_access` (`write`/`read`/`none`), `output_mode` (`pr`/`comment`/`cards`/`update`), and `allowed_tools` — so agent behavior is composable through configuration. Existing configs work unchanged (defaults match prior hardcoded behavior).

Key changes:
- `repo` and `branch_prefix` are now optional (only required when `repo_access == "write"`)
- Model validator enforces cross-field constraints (e.g. `output_mode: "pr"` requires `repo_access: "write"`)
- `WorkerAgent._execute_card()` decomposed into four stage methods (`_setup_repo`, `_build_prompt`, `_run_sdk`, `_deliver_output`) that dispatch on config
- Workers with `output_mode: "cards"` get MCP tools (`create_trello_card`, `list_workers`, etc.) via `build_worker_mcp_server()`
- Added `update_card_description()` Trello CRUD for the `update` output mode
- Orchestrator failure message generalized (no longer assumes code-only agents)

## 3. Per-agent LLM model assignment (LLM agnostic)

**Status:** Open

Allow each agent to be configured with a different LLM model/provider, making Karavan fully LLM agnostic. A worker could use Claude Sonnet for simple tasks, Opus for complex ones, or even a non-Anthropic model.

**Considerations:**
- Add a `model` field to agent config in `config.json` (e.g. `"model": "claude-sonnet-4-6"`, `"model": "openai/gpt-4o"`)
- Currently tightly coupled to Claude Agent SDK — need an abstraction layer between agents and LLM providers
- Define a common interface (prompt in, result out) that different backends implement
- Backends to support: Claude Agent SDK, OpenAI, local models (ollama), etc.
- Cost tracking needs to generalize across providers
- Tool availability may vary by provider — need capability detection or per-provider tool mapping
- Aligns with the v1.0 roadmap item: "Plugin system for other LLMs"

## 4. Multi-board orchestrator

**Status:** Open

Allow a single orchestrator to manage multiple Trello boards, each with its own agents and lists. For example, a backend board with API workers and a frontend board with UI workers, all coordinated by one orchestrator.

**Considerations:**
- Currently `board_id` is a single value on the orchestrator config — needs to become a list or a map of boards
- Each board has its own set of agents, lists, and webhooks
- Orchestrator needs one board-level webhook per board (watching `done` lists on each)
- Cross-board dependencies: a frontend card could depend on a backend card from a different board
- MCP tools (`create_trello_card`, `list_workers`) need a `board` parameter so the orchestrator knows where to create cards
- The orchestrator's system prompt should describe all boards and their purpose so it can route tasks correctly
- Config shape could look like:
  ```json
  {
    "boards": {
      "backend": { "board_id": "...", "agents": ["api", "infra"] },
      "frontend": { "board_id": "...", "agents": ["static", "mobile"] }
    }
  }
  ```
- Aligns with the v0.3 roadmap item: "Multiple projects/boards support"
