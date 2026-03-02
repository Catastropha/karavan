# Karavan Improvement Tracker

Weaknesses and improvements identified from a full codebase analysis. Work through these one by one, checking them off as completed.

---

## P0 — Critical (Core loop is broken or agents produce bad output)

### 1. Orchestrator cannot create Trello cards
- **Status:** DONE
- **File(s):** `app/apps/agent/orchestrator.py`
- **Problem:** The orchestrator's Claude SDK session has `allowed_tools=["Read", "Glob", "Grep"]` — read-only. The entire premise is that it "creates Trello cards in workers' todo lists," but it has no way to actually call `create_card()`. It's a chatbot with repo access, not an orchestrator.
- **Fix:** Expose Trello card creation (and status checking, worker listing, etc.) as custom tools the SDK agent can invoke, or parse structured output from the orchestrator and create cards programmatically in the harness.

### 2. Worker prompt lacks operational context
- **Status:** DONE
- **File(s):** `app/apps/agent/worker.py:85`
- **Problem:** The prompt is just `## Card: {card.name}\n\n{card.desc}`. The agent doesn't know: it should write code (not explain), what repo it's in, what branch it's on, that it must NOT commit/push (the harness does that), or how to interpret acceptance criteria.
- **Fix:** Build a rich prompt template that includes: role framing, repo/branch context, explicit instructions on what to do and what not to do (no git operations), and how to signal completion.

### 3. No validation that the agent produced changes
- **Status:** DONE
- **File(s):** `app/apps/agent/worker.py:107`, `app/apps/git_manager/crud/update.py`
- **Problem:** After the SDK returns, `commit_and_push` silently skips commit if there are no changes (`git diff --cached --quiet`), then still tries to push and create a PR. Results in empty PRs or errors.
- **Fix:** Check for changes after the agent runs. If none, comment on the card that the agent made no changes and move to a review/failed state instead of blindly proceeding.

---

## P1 — Significant (Will cause failures under real usage)

### 4. Infinite retry loop on failure
- **Status:** DONE
- **File(s):** `app/apps/agent/worker.py:126-132`
- **Problem:** On any exception, the card moves back to `todo`, which triggers the webhook, which picks it up again, which fails again. Poison cards loop forever.
- **Fix:** Add a retry counter (tracked via Trello card labels or comments). After N failures (e.g., 3), move the card to a `failed` list or leave it in `doing` with an error comment instead of returning to `todo`.

### 5. Base branch hardcoded to `dev`
- **Status:** DONE
- **File(s):** `app/apps/git_manager/crud/update.py:pull_dev()`, `app/apps/agent/worker.py:116`
- **Problem:** `pull_dev()` checks out `dev` and PRs target `dev`. Projects using `main` (or any other branch) as their primary branch will break entirely.
- **Fix:** Add a `base_branch` field to `WorkerAgentConfig` (defaulting to `main`). Pass it through to `pull_dev()` and PR creation.

### 6. Duplicate webhook accumulation on restart
- **Status:** DONE
- **File(s):** `app/main.py:51-72`, `app/apps/trello/crud/create.py`
- **Problem:** Every startup calls `register_webhook()` without checking for existing ones. Trello doesn't deduplicate. After a few restarts, the same event fires N webhooks, causing duplicate card processing.
- **Fix:** On startup, list existing webhooks via the Trello API. Delete stale ones or skip registration if an identical webhook already exists.

### 7. No Trello API rate limiting
- **Status:** TODO
- **File(s):** `app/core/resource.py`, all Trello CRUD files
- **Problem:** Trello enforces 100 requests per 10 seconds per token. Multiple workers processing cards simultaneously (6-8 Trello calls each) can easily exceed this. A 429 response raises `HTTPStatusError` and crashes card processing.
- **Fix:** Implement a token-bucket or sliding-window rate limiter on the shared Trello httpx client. Alternatively, add retry-with-backoff on 429 responses.

---

## P2 — Moderate (Degrades quality and visibility)

### 8. No card deduplication
- **Status:** TODO
- **File(s):** `app/apps/agent/worker.py`, `app/apps/agent/base.py`
- **Problem:** Nothing prevents the same card from being queued and processed multiple times concurrently (from duplicate webhooks, retries, or race conditions).
- **Fix:** Maintain an in-progress set of card IDs per agent. Skip processing if the card is already being worked on. Clear on completion or failure.

### 9. Orchestrator done-event handling is minimal
- **Status:** TODO
- **File(s):** `app/apps/agent/orchestrator.py:133-145`
- **Problem:** Done notification is just "Card completed: {name}". Doesn't include the PR link, doesn't summarize what was done, doesn't check if all cards for a feature are complete, doesn't trigger dependent cards.
- **Fix:** Fetch the card's comments to find the PR link. Include it in the Telegram notification. Implement basic dependency checking — when a card completes, check if any blocked cards can now be unblocked.

### 10. No cost tracking
- **Status:** TODO
- **File(s):** `app/apps/agent/worker.py`, `app/apps/agent/orchestrator.py`
- **Problem:** `ResultMessage` provides `total_cost_usd` and token usage but neither agent captures it. Running autonomous agents without tracking spend is risky.
- **Fix:** Log cost per card execution. Optionally comment cost on the Trello card. Accumulate totals in memory and expose via the health endpoint.

### 11. MarkdownV2 escaping is fragile
- **Status:** TODO
- **File(s):** `app/apps/bot/markdown.py`
- **Problem:** Only handles `**bold**` conversion. Doesn't handle code blocks (``` or \`inline\`), links, lists, or other markdown the LLM will inevitably produce. Complex responses break Telegram rendering.
- **Fix:** Implement proper markdown-to-MarkdownV2 conversion covering: code blocks (preserve as-is, only escape inside), inline code, links, bullet lists. Or fall back to `parse_mode=None` for plain text when escaping fails.

### 12. Branch creation fails on retry
- **Status:** TODO
- **File(s):** `app/apps/git_manager/crud/create.py:create_branch()`
- **Problem:** Uses `git checkout -b` which fails if the branch already exists (e.g., when retrying a failed card). The error crashes the card execution.
- **Fix:** Use `git checkout -B` (force-create) or check if the branch exists first and delete/reset it.

---

## P3 — Nice to Have (Operational polish)

### 13. Health endpoint lacks agent status
- **Status:** TODO
- **File(s):** `app/apps/hook/route.py:74-77`
- **Problem:** `/health` returns `{"status": "ok"}` regardless of whether agents are running, queues are backed up, or the last activity was hours ago.
- **Fix:** Include per-agent status: running (bool), queue depth, last activity timestamp, cards processed count.

### 14. No progress feedback during long worker tasks
- **Status:** TODO
- **File(s):** `app/apps/agent/worker.py`
- **Problem:** Worker tasks can take several minutes. The user gets no feedback between "card picked up" and the done notification (or silence on failure).
- **Fix:** Send periodic Telegram updates or Trello card comments during execution (e.g., "Agent started working on card...", progress from SDK stream messages).

### 15. No Trello webhook payload verification
- **Status:** TODO
- **File(s):** `app/apps/hook/route.py:30-71`
- **Problem:** Any POST to `/webhook/{agent_name}` with valid-looking JSON is accepted. No source verification.
- **Fix:** Verify the webhook source using the `x-trello-webhook` header or by checking that the callback URL matches what was registered.

### 16. `answer_callback_query` is never called
- **Status:** TODO
- **File(s):** `app/apps/bot/crud/create.py`, `app/apps/bot/route.py`
- **Problem:** `answer_callback_query()` is implemented but never invoked. When a user taps an inline keyboard button, Telegram shows a perpetual loading spinner because the callback is never acknowledged.
- **Fix:** Call `answer_callback_query(callback_query_id)` in the bot route after processing a `callback_query` event.

### 17. Orchestrator uses `user_id` as `chat_id` for notifications
- **Status:** TODO
- **File(s):** `app/apps/agent/orchestrator.py:140`
- **Problem:** Done-event notifications iterate over `telegram_allowed_user_ids` and use them as `chat_id`. This works for private chats (where user_id == chat_id) but will fail in group chats.
- **Fix:** Track the `chat_id` from the original conversation and notify that chat. For single-user this is cosmetic, but matters if the bot is ever used in a group.
