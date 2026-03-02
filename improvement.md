# Karavan Improvements

## 1. Clear orchestrator context via Telegram

**Status:** Open

Can we reset the orchestrator's conversation context through Telegram, similar to `/clear` in Claude Code SDK? This would let the user start a fresh planning session without restarting the server.

**Considerations:**
- `ClaudeSDKClient` may need to be re-instantiated or expose a `clear()` method
- Could be triggered by a Telegram command like `/clear`
- Should confirm to the user that context was cleared
- Decide whether to also clear the orchestrator's async queue or just the SDK conversation history

## 2. Agent roles beyond "worker"

**Status:** Open

Introduce distinct agent roles that go beyond just coding. Different roles would have different system prompts, tool access, and behaviors in the card lifecycle.

**Potential roles:**
- **Coder** — current worker behavior, writes code and opens PRs
- **Critic** — reviews PRs or code on cards, leaves comments with feedback, can request changes or approve
- **Doubter** — challenges assumptions in card descriptions, flags risks, edge cases, and missing requirements before work begins
- **Tester** — writes and runs tests against a coder's branch, reports results on the card
- **Reviewer** — performs code review on open PRs, comments on GitHub, can block merge

**Considerations:**
- Add a `role` field to agent config (e.g. `"role": "coder"`, `"role": "critic"`)
- Each role defines: default system prompt, allowed tools, which lists it watches, what it outputs (code, comments, approvals)
- Roles could chain in a pipeline: coder → critic → reviewer → done
- Orchestrator needs awareness of roles to assign cards appropriately
- Non-coding roles don't need git push/PR access — just read access and comment ability
- Could model as additional Trello lists per pipeline stage (e.g. `review`, `testing`)

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
