# Karavan — TODO

Tracked items to bring the project to good standing.

## 1. Sync CLAUDE.md with implementation

**Status:** Done

The documentation has drifted from the code in three areas:

- **Config schema**: CLAUDE.md still shows the flat `agents:` structure with `"type": "worker"/"orchestrator"` discriminators. The actual code uses `boards:` (workers nested under boards) + top-level `orchestrator:`.
- **Function names**: CLAUDE.md references `build_orchestrator_mcp_server()` and `build_worker_mcp_server()` — the code has a single `build_mcp_server(name)`.
- **CRUD references**: CLAUDE.md mentions `update_card_description()` as a standalone function — the code uses `update_card(card_id, desc=...)`.

**Files:** `CLAUDE.md`

## 2. Add missing return type hint on `_get_worker`

**Status:** Done

`_get_worker(name: str)` in `tools.py` is missing its return type annotation. Should be `-> WorkerAgentConfig | None`. Violates the project's "type hints on everything" convention.

**Files:** `app/apps/agent/tools.py:28`

## 3. Add exhaustive guard in `_deliver_output`

**Status:** Done

The method handles `pr`, `comment`, `cards`, `update` via elif chains but has no final `else`. If `output_mode` were somehow invalid, it would silently return `None`. Add a trailing `raise ValueError(f"Unknown output_mode: {mode}")`.

**Files:** `app/apps/agent/worker.py:213-246`

## 4. Remove unnecessary f-string prefix

**Status:** Done

`f"Card creation completed."` has no interpolation. Should be a plain string literal.

**Files:** `app/apps/agent/worker.py:234`

## 5. Type the module-level globals in route modules

**Status:** Done

`_agent_registry` and `_orchestrator_queue` are untyped module globals set via setter functions. They should have proper type annotations (e.g., `_agent_registry: AgentRegistry | None = None`) so the type checker can catch misuse.

**Files:** `app/apps/hook/route.py:19`, `app/apps/bot/route.py`

## 6. Add graceful shutdown for in-flight cards

**Status:** Open

`stop()` cancels the task but doesn't handle in-progress cards. If a worker is mid-execution when shutdown fires, the card stays in `doing` forever. The shutdown path should move any in-progress card back to `todo` (and discard it from `_processed_cards`) so it gets retried on restart.

**Files:** `app/apps/agent/worker.py`, `app/apps/agent/base.py`

## 7. Commit untracked test files

**Status:** Open

`tests/hook/` is untracked in git. These tests should be committed.

## 8. Add `.idea/` to `.gitignore`

**Status:** Open

JetBrains IDE config directory is showing as untracked. Should be gitignored.

**Files:** `.gitignore`

## 9. Clean up `improvement.md`

**Status:** Done

Replaced with this file. Completed items removed. Multi-board (#4) was already implemented. LLM-agnostic (#3) belongs in the CLAUDE.md v1.0 roadmap, not a standalone tracking file.
