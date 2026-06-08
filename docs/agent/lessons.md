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
| 2026-06-07 | app.py `__init__` accessing `_status_item` | `AttributeError: 'ClaudemonApp' has no attribute '_status_item'` — NSStatusItem is created in `run()` → `initializeStatusBar()`, not `__init__` | Use `rumps_events.before_start.register(callback)` to run code after `initializeStatusBar()`. Access via `self._nsapp.nsstatusitem` (not `self._status_item`). |
| 2026-06-07 | app.py `@rumps.clicked("claudemon")` | Creates a dropdown *menu item* named "claudemon", not a status bar click handler. Clicking it passed a `rumps.MenuItem` as sender — no `_status_item` → popover never anchored | Remove `@rumps.clicked`. Use `_ClickHandler(NSObject)` with `button.setAction_("handleClick:")` + `button.setTarget_(handler)` + `nsstatusitem.setMenu_(None)` |
| 2026-06-07 | server.py static files | `style.css` and `app.js` returned 404 — server only matched `/` and `/api/*`. Dashboard loaded as unstyled HTML with no JavaScript | Add a static file handler for any path that resolves to a file inside `dashboard_dir`. Validate with `.relative_to()` to prevent path traversal. |
| 2026-06-07 | statusitem.py colored dots | Plain `self._app.title = "◆ 18k ●"` can't have per-character color — all text is one color in dark/light menu bar | Use `NSMutableAttributedString` + `setAttributedTitle_` on the `NSStatusBarButton`. Dispatch via `NSOperationQueue.mainQueue().addOperationWithBlock_()` for thread safety. |
| 2026-06-07 | popover.py NSPanel for LSUIElement app | `makeKeyAndOrderFront_` silently does nothing for background-only (LSUIElement) apps — the app is never the active frontmost application. Also, `NSPanel` created in `__init__` before run loop may not behave correctly. | Use `orderFrontRegardless()` to show the panel, preceded by `NSApplication.sharedApplication().activateIgnoringOtherApps_(True)`. Defer panel + webview construction to the first `toggle()` call (lazy `_ensure_panel()`), not `__init__`. |
| 2026-06-07 | app.js renderQueryChart | Per-day query bars were estimates: `Math.round((b.output_tokens / totalOut) * stats.queries)`. The tok/query line was flat: `timeline.map(() => stats.tokens_per_query)` (global average). Both produced misleading charts. | Never estimate per-bucket stats from a global aggregate. Add `COUNT(DISTINCT query_id)` and per-bucket `tokens_per_query` to the timeline DB query. Chart callbacks with `pointRadius: 0` also prevent hovering — always set a visible radius. |
| 2026-06-07 | server.py / db.py "today" range | `datetime.now(timezone.utc).replace(hour=0, ...)` gives UTC midnight. For a UTC-7 user, work done after 5 PM local time counted as "yesterday." Menu bar token counter had the same bug. | Use `datetime.now()` (no timezone) for local midnight. `datetime.now(timezone.utc)` is the wrong anchor for "today" in a single-user desktop app. |
| 2026-06-07 | app.js Chart.js tooltip closure | Tooltip callbacks set in `initCharts()` at startup don't have access to data loaded later. Task chart needed session titles from `tasksData` inside the tooltip, but `tasksData` wasn't in scope. | Update `chart.options.plugins.tooltip.callbacks` inside the render function each time data changes, capturing the current data array in a closure over the render call. |
| 2026-06-07 | app.js Chart.js click drill-down | Clicking a chart bar needs the bucket timestamp for that bar. Chart.js gives `elements[0].index`; the timestamp must come from a module-level padded data array (`_paddedTimeline[idx].date`), not from the chart's own dataset (which contains token counts, not timestamps). | Store padded data arrays at module level. Click handler reads the timestamp from `_paddedTimeline[idx]?.date ?? _paddedTasks[idx]?.date`. Guard with `isDayView()` so clicks in the day view don't recurse. |
| 2026-06-07 | server.py day drill-down range | Computing the end of a specific calendar day as `day_start_ms + 86400000` is wrong during DST transitions (±1h). | Use `datetime.fromtimestamp(day_start_ms/1000).replace(h=0,m=0,s=0) + timedelta(days=1)` then `.timestamp()*1000`. Python adds one calendar day, not 24 hours. |
| 2026-06-07 | app.js gap-filling for multi-day charts | Timeline API only returns buckets that have data — missing days make the chart look like a 2-day view inside a 7-day range. | Pad client-side with `d.setHours(0,0,0,0)` to generate every expected bucket, merge with real data via a `Map`. Browser's `setHours(0,0,0,0)` matches the server's local-midnight bucket timestamps exactly (both use the same local timezone). |


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
- **rumps NSStatusItem lifecycle**: `self._nsapp.nsstatusitem` exists only after `run()` → `initializeStatusBar()`. Use `rumps_events.before_start` to run code that needs it. `self._nsapp` is set during `run()`, not `__init__`.
- **`@rumps.clicked("name")` is a menu item decorator**: It adds a dropdown entry, not a status bar click handler. For direct click → popover: use a `_ClickHandler(NSObject)` with `setAction_`/`setTarget_` on the button and `setMenu_(None)` to suppress the dropdown.
- **rumps server static files**: `http.server` only handles explicitly matched paths. Requests for `style.css`, `app.js`, etc. need an explicit static file handler — they are NOT served automatically.
- **rumps handles NSStatusItem**: Only drop to raw PyObjC for NSPopover and NSStatusItem actions. Don't fight rumps for title/icon management.
- **`pyobjc-framework-WebKit`**: Must be explicitly installed even if other PyObjC frameworks are present. Provides `WKWebView`.
- **session_id source of truth**: The indexer reads `sessionId` from JSONL record content. Filename stem is fallback only. In production they always match (Claude Code names files by UUID).
- **venv required**: Homebrew Python is externally managed. All tooling must be invoked via `.venv/bin/` prefixes or with an activated venv.
- **SQLite WAL mode + threading**: `check_same_thread=False` disables Python's ownership check but does NOT serialise access. Wrap all write functions (`upsert_session`, `insert_message`, `update_cursor`) with a `threading.Lock`. Read functions are safe without a lock under WAL mode for a single writer.
- **Timezone-aware daily bucketing**: `_local_trunc(bucket_ms, tz_offset_ms)` in db.py applies `((ts+tz)/bucket)*bucket - tz` to produce local-calendar-day boundaries in UTC ms. Both `query_timeline` and `query_tasks` accept `tz_offset_ms`. Server computes it via `datetime.now().astimezone().utcoffset().total_seconds()*1000` (DST-aware). Gap-filling in the browser uses `d.setHours(0,0,0,0)` which produces the same bucket keys because browser and server share the same local timezone.
- **DB data corruption from incremental indexer + early bugs**: If the indexer ran with buggy code early on (wrong query_ids, no UNIQUE constraint), the resulting DB has corrupt task/query counts that won't self-heal because `INSERT OR IGNORE` skips re-insertion. Tell the user to delete `~/.claudemon/claudemon.db` and restart to trigger a full re-index with current code.


## Non-Negotiable Before "Done"

- All tests pass (`just test`)
- Coverage ≥ 80% (`just coverage`) — macOS-only files excluded via `pyproject.toml omit`
- Lint clean (`just lint`)
- No silent data corruption paths: `messages` table must have `UNIQUE(session_id, query_id, timestamp)` + `INSERT OR IGNORE`
