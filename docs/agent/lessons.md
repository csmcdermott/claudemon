# Lessons

## Correction Log

| Date | Context | What went wrong | Rule learned |
| --- | --- | --- | --- |
| 2026-06-07 | server.py `do_POST` | Compared `self.path == "/api/quit"` — but `self.path` includes query string (e.g. `/api/quit?x=1`), so POST with any param silently falls to 404 | Always parse `urlparse(self.path).path` before comparing paths in `do_GET` and `do_POST` |
| 2026-06-07 | server.py port=0 | Used a temp socket to find a free port, closed it, then bound HTTPServer — TOCTOU race; another process could steal the port between close and bind | Pass `port=0` directly to `HTTPServer`; read `server.server_address[1]` for the bound port |
| 2026-06-07 | indexer.py query_id fallback | When no user message seen yet (`task_num == 0`), fallback was `f"{short_id}:{task_num}:1"` → `abc:0:1` while task_id was `abc:1` — inconsistent IDs | Fallback must be `f"{short_id}:1:1"` — hardcode `:1:` not `:task_num:` |
| 2026-06-07 | indexer.py `_is_new_query` | `record.get("isSidechain") is False` silently drops records where field is absent (returns None, not False) | Use `not record.get("isSidechain", True)` — treats missing as `True` (is a sidechain) to fail safe |
| 2026-06-07 | db.py messages table | No UNIQUE constraint → replayed JSONL files insert duplicate rows, silently doubling all token sums | Add `UNIQUE (session_id, query_id, timestamp)` to messages + use `INSERT OR IGNORE` |
| 2026-06-07 | db.py `query_sessions` | WHERE only had `s.started_at <= end_ms` — sessions from months ago appear in "last 7 days" | Use `s.started_at BETWEEN start_ms AND end_ms` with both bounds |
| 2026-06-07 | justfile / pre-push.sh | Bare `ruff` and `pytest` commands failed — Homebrew-managed Python is externally locked, packages only in `.venv/` | Always use `.venv/bin/ruff` and `.venv/bin/pytest` in `justfile` and `pre-push.sh` |
| 2026-06-07 | test conftest `conn` fixture | In-memory SQLite created with default `check_same_thread=True` — server tests run queries from a daemon thread and got ProgrammingError | Add `check_same_thread=False` to `sqlite3.connect(":memory:")` in the test `conn` fixture |


## Patterns to Follow

_Promoted from Correction Log after applying in a second session._


## Anti-Patterns to Avoid

_Promoted from Correction Log after applying in a second session._


## Project-Specific Gotchas

- **Claude Code JSONL record types**: `assistant`, `user`, `system`, `ai-title`, `attachment`, `last-prompt`, `mode`, `permission-mode`, `file-history-snapshot`. Only `assistant` records have token usage data.
- **Token usage location**: `message.usage` inside assistant records — not top-level. Fields: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`.
- **Cache reads not split by tier**: `cache_read_input_tokens` is a total. Only writes are split: `cache_creation.ephemeral_1h_input_tokens` and `cache_creation.ephemeral_5m_input_tokens`.
- **`gitBranch` field**: Present on `assistant`, `user`, and `attachment` records. Reliable for task boundary detection.
- **Session state file**: `~/.claude/sessions/{pid}.json` — `status == "busy"` means Claude is actively processing. File updates frequently.
- **Anthropic Admin API unavailable for subscription users**: Requires `sk-ant-admin...` key (org admin only). Claude Code subscription usage is only accessible via local JSONL files.
- **macOS-only modules**: `app.py`, `popover.py`, `statusitem.py`, `watcher.py` cannot be unit-tested without a running macOS event loop. Exclude them from coverage with `[tool.coverage.run] omit`.
- **rumps handles NSStatusItem**: Only drop to raw PyObjC for NSPopover. Don't fight rumps for what it handles well.
- **`pyobjc-framework-WebKit`**: Must be explicitly installed even if other PyObjC frameworks are present. Provides `WKWebView`.
- **session_id source of truth**: The indexer reads `sessionId` from JSONL record content. Filename stem is fallback only. In production they always match (Claude Code names files by UUID).
- **venv required**: Homebrew Python is externally managed. All tooling must be invoked via `.venv/bin/` prefixes or with an activated venv.
- **SQLite WAL mode + threading**: `check_same_thread=False` disables Python's ownership check but does NOT serialise access. Wrap all write functions (`upsert_session`, `insert_message`, `update_cursor`) with a `threading.Lock`. Read functions are safe without a lock under WAL mode for a single writer.


## Non-Negotiable Before "Done"

- All tests pass (`just test`)
- Coverage ≥ 80% (`just coverage`) — macOS-only files excluded via `pyproject.toml omit`
- Lint clean (`just lint`)
- No silent data corruption paths: `messages` table must have `UNIQUE(session_id, query_id, timestamp)` + `INSERT OR IGNORE`
