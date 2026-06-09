## Project Overview

| Field | Value |
| --- | --- |
| **Project name** | claudemon |
| **Purpose** | macOS menu bar app to monitor Claude Code usage in real time — token counts, cache hit rates, query/task analytics, active session state |
| **Target release** | v1.0 (personal use) |
| **Last updated** | 2026-06-08 (dashboard enhancements: p50/max lines, stacked queries chart, hourly day views, section reorder) |

## Tech Stack

| Layer | Technology | Notes |
| --- | --- | --- |
| Menu bar | rumps | Wraps AppKit NSStatusItem |
| Popup panel | PyObjC NSPanel + WKWebView | Resizable floating panel (replaced NSPopover); lazy-init via `_ensure_panel()` on first click |
| Dashboard UI | HTML / CSS / Chart.js | Fetches JSON from local server |
| Local HTTP server | Python stdlib http.server | Random localhost port; 127.0.0.1 only |
| File watching | watchdog | Watches ~/.claude/projects/**/*.jsonl and ~/.claude/sessions/*.json |
| Data index | SQLite in-memory (stdlib sqlite3) | Ephemeral; full re-index on startup, incremental within session via in-memory file_cursors |
| Config | JSON | ~/.claudemon/config.json |
| Distribution | py2app | Builds `dist/claudemon.app` via `just build`; `just install-app` copies to /Applications/ |
| Testing | pytest | >80% coverage required |

## Architecture Overview

```
macOS layer (rumps + PyObjC)  →  Data layer (watchdog + indexer + SQLite)  →  Dashboard layer (http.server + HTML)
                                              ↑
                              ~/.claude/projects/**/*.jsonl  (source of truth, read-only)
                              ~/.claude/sessions/*.json      (session state)
```

**Key design decisions:**
- All data is local — no Anthropic API calls required
- **In-memory SQLite**: `db.connect()` always returns `":memory:"`. Full re-index on every startup; byte-offset cursors tracked in-memory for incremental O(new bytes) indexing during the session. No persistent DB file — eliminates DB corruption and stale data.
- Task boundary detection uses multi-signal heuristic: 30-min gap OR git branch change OR /clear command OR new session
- NSPanel (not NSPopover) for resizable popup — requires `orderFrontRegardless()` + `activateIgnoringOtherApps_` for LSUIElement apps; panel is lazy-created on first click
- Local HTTP server allows full Chart.js dashboard inside WKWebView
- All time bucketing uses local-timezone offsets (`_tz_offset_ms()` in server.py, `_local_trunc()` in db.py) so day/hour chart labels match the user's clock
- "Today" view shows stat counters instead of charts; `day:TIMESTAMP` range enables drill-down from multi-day chart click
- **py2app bundle**: `setup.py` with `LSUIElement: True` plist. `app.py` uses `sys.frozen` + `NSBundle.mainBundle().resourcePath()` to find dashboard in bundled mode. `just build` → `dist/claudemon.app`; `just install-app` → /Applications/.

## Directory Structure

```
claudemon/
├── claudemon/           # Python package
│   ├── app.py           # Entry point, rumps.App subclass
│   ├── statusitem.py    # Menu bar icon, token count, state dot
│   ├── popover.py       # PyObjC NSPopover + WKWebView
│   ├── watcher.py       # watchdog Observer
│   ├── indexer.py       # JSONL parser, task ID assigner
│   ├── db.py            # SQLite schema + all queries
│   ├── server.py        # Local HTTP server + API handlers
│   └── dashboard/       # index.html, app.js, style.css
├── tests/
├── docs/
│   ├── agent/           # This file + lessons.md
│   └── superpowers/specs/2026-06-07-claudemon-design.md
├── setup.py             # py2app bundle configuration
├── scripts/
├── CLAUDE.md
├── justfile
└── pyproject.toml
```

## Core Components

| Component | Location | Description |
| --- | --- | --- |
| App entry | claudemon/app.py | Initialises all components, runs full index on startup |
| Status item | claudemon/statusitem.py | Menu bar display: icon + today output tokens + state dot |
| Popover | claudemon/popover.py | NSPopover with WKWebView loading localhost dashboard |
| File watcher | claudemon/watcher.py | watchdog observer dispatching events to indexer + statusitem |
| Indexer | claudemon/indexer.py | Parses JSONL deltas, assigns task_ids, writes to SQLite |
| Database | claudemon/db.py | Schema (sessions, messages, file_cursors) + query API |
| HTTP server | claudemon/server.py | /api/stats, /api/timeline, /api/tasks, /api/sessions, /api/config, /api/usage |
| Keychain | claudemon/keychain.py | Reads Claude Code OAuth token from macOS Keychain via `security` CLI |

## Data Flow

1. Startup → indexer scans all JSONL, builds SQLite (~100-200ms for ~370 sessions)
2. watchdog detects JSONL write → indexer parses delta → updates SQLite → statusitem refreshes token count
3. watchdog detects sessions/*.json change → statusitem checks status field → updates state dot
4. User clicks icon → NSPopover shown → WKWebView loads http://localhost:{port}/
5. Dashboard JS fetches /api/stats + /api/timeline + /api/tasks → Chart.js renders
6. Active session banner polls /api/sessions?active=true every 5 seconds

## External Integrations

| Integration | Purpose | Docs location |
| --- | --- | --- |
| None | All data is local | — |

## Key Interfaces / API Surface

```
GET  /api/stats?range=today|7d|30d|all|day:MS
GET  /api/timeline?range=...&bucket=1h|1d          ← returns queries + tokens_per_query per bucket
GET  /api/tasks?range=...&bucket=1h|1d             ← returns p50/max/avg tokens per task + per-bucket tasks list
GET  /api/queries?range=...&bucket=1h|1d           ← returns top-10 queries by token volume + other + p50/max per bucket
GET  /api/sessions?range=...&limit=10&active=false
GET  /api/usage                                    ← live rate-limit utilization from Anthropic OAuth API; 115s cache
GET  /api/config
POST /api/config
POST /api/quit   → sends SIGTERM to process (used by dashboard Quit button)
```

`range=day:MS` is a specific local calendar day (MS = local midnight UTC ms as returned by chart bucket data). Server computes end as `datetime.fromtimestamp(MS/1000) + timedelta(days=1)` (DST-safe).

`/api/tasks` and `/api/queries` both accept `bucket=1h|1d`; the JS passes `1h` for day views and `1d` otherwise.

Full spec: `docs/superpowers/specs/2026-06-07-claudemon-design.md`
Dashboard enhancements spec: `docs/superpowers/specs/2026-06-08-dashboard-enhancements-design.md`
Implementation plan: `docs/superpowers/plans/2026-06-07-claudemon.md`

**Error shape:** HTTP 500 with `{"error": "message"}` JSON body.

## Known Issues / Technical Debt

| Date | Area | Description |
| --- | --- | --- |
| 2026-06-08 | Distribution | .app bundle is unsigned — first launch requires right-click → Open (Gatekeeper). For wider distribution, code signing + notarization would be needed. |
| 2026-06-07 | Task detection | Heuristic-based; very long uninterrupted sessions may produce unexpectedly large tasks |
| 2026-06-07 | SQLite reads | Read functions (query_stats etc.) don't hold _LOCK. Concurrent read+write is safe for a single user with in-memory DB but not fully serialised. |
| 2026-06-08 | Startup time | Full re-index on every launch. Currently ~100-200ms for ~370 sessions; will grow linearly with history. |

## Versioning

Version is defined in **two files that must stay in sync** — always use `just bump-patch/minor/major` (never edit manually):
- `pyproject.toml` — packaging metadata
- `claudemon/_version.py` — runtime import (`from claudemon._version import __version__`)

The pre-commit hook (`scripts/pre-commit.sh`) auto-bumps patch on every commit. Run `just bump-minor` before committing a new feature. The version is served via `/api/config` as `_version` and displayed in the dashboard footer.

## Implementation Notes

- **venv required**: System Python is Homebrew-managed and externally locked. All `just` recipes use `.venv/bin/` prefixes. Always `source .venv/bin/activate` or use `just` to run tools.
- **macOS-only modules excluded from coverage**: `app.py`, `popover.py`, `statusitem.py`, `watcher.py` are omitted from coverage measurement (require macOS event loop). Covered modules target ≥80%.
- **session_id from JSONL content, not filename**: The indexer reads `sessionId` from JSONL records; the filename stem is the fallback. In production they always match (Claude Code names files by UUID), but tests use fixture filenames like `abc123.jsonl`.
- **`/api/quit` fires SIGTERM in a daemon thread**: Ensures the HTTP response is sent before the process exits.
- **In-memory DB**: `db.connect()` always returns `sqlite3.connect(":memory:")`. No `DB_PATH` constant exists. The `file_cursors` table lives in the same in-memory DB — byte-offset cursors survive within a session but are discarded on quit, triggering a full re-index on next launch.
- **Timezone bucketing**: `_tz_offset_ms()` in server.py = `datetime.now().astimezone().utcoffset().total_seconds() * 1000`. `_local_trunc(bucket_ms, tz_offset_ms)` in db.py applies it as `((ts+tz)/bucket)*bucket - tz`. Both `query_timeline` and `query_tasks` accept `tz_offset_ms`.
- **Day drill-down**: Clicking a chart bar sets `currentRange = "day:<local_midnight_ms>"`. JS stores last padded data in `_paddedTimeline`/`_paddedTasks`/`_paddedQueries` module vars; `onChartClick` resolves the timestamp via `_paddedTimeline[idx]?.date ?? _paddedTasks[idx]?.date ?? _paddedQueries[idx]?.date`.
- **Gap filling**: `padTimeline`, `padTasks`, `padQueries` in app.js generate all expected buckets (24 hourly for day views, 7/30 daily for multi-day, raw for 'all'). Day-view start anchored via `dayViewStart(range)` helper — returns local midnight for 'today' or `parseInt(range.split(':')[1])` for 'day:X'. Works because server and browser share the same timezone.
- **Stacked queries chart**: `/api/queries` returns top-10 queries per bucket sorted descending by total_tokens; remainder collapsed into `other_count`/`other_tokens`. p50/max computed over ALL queries (not just top 10). Frontend uses `queryIndex` property on each dataset to resolve tooltip labels stably regardless of dataset array position.
- **p50 computation**: Uses lower-median formula `sorted_list[(n-1)//2]`. SQLite has no native MEDIAN so computed in Python after fetching per-entity token sums.
- **Hour-view detection**: `isHourView(range)` (delegates to `isHourBucket`) returns true for `today`, `day:X`, and sub-24h `custom:` ranges. Governs `#today-summary` visibility, hourly bucket labels, and pad function routing. `isHourBucket` also drives `bucket=1h` vs `bucket=1d` in API calls.
- **`viewBuckets(range)`**: Returns ordered timestamp list for a range: `today` (12h rolling), `day:X` (24 hours from midnight), `custom:≤24h` (hourly), `custom:>24h` (daily), `[]` for unknown. Pad functions use it for `isHourView || custom:` ranges.
- **Custom range format**: `custom:START_MS:END_MS`. Split by `:` → 3 parts. Threshold: ≤ 86_400_000 ms → 1h bucket, else 1d.
- **Custom picker toggle**: `customPicker.style.display = 'none'` set in JS immediately after element capture; CSS-set display shows as `''` not `'none'` in inline style. Opening the picker sets `display = 'block'` (not `''`, which defers back to CSS).
- **Day view shows charts**: `setViewMode` only shows/hides `#today-summary`; `.chart-section` elements are always visible. Day view shows stat counters + all three hourly charts. `bucketLabel` uses `isHourView(range)` for hourly labels.
- **`bucketLabel(ts, range, prevTs)`**: Hour views use `fmtHour(ts)` (locale-independent: `h % 12 || 12` + `'am'`/`'pm'`). Day views use `String(new Date(ts).getDate())` for the day-of-month number. Midnight crossings in hour views prepend `"Jun 8 "` via `toLocaleDateString`. `prevTs` is the previous bucket's timestamp; pass `padded[i-1].date` in map callbacks.
- **`SCALE_X` must include `type: 'category'`**: Without it, Chart.js auto-detects scale type from label content. Numeric-looking strings (e.g. `"8"`) cause it to infer a linear scale and generate index ticks (0, 1, 2, …) instead of using `chart.data.labels`.
- **WKWebView caching**: Default data store persists HTTP cache across app launches. Fix: `WKWebsiteDataStore.nonPersistentDataStore()` in `WKWebViewConfiguration`, plus `NSURLRequestReloadIgnoringLocalCacheData` policy on `loadRequest_`. Server also sends `Cache-Control: no-store` on all responses.
- **py2app bundle**: `setup.py` subclasses `py2app.build_app.py2app` to clear `install_requires` before `finalize_options` (py2app 0.28 rejects it; setuptools populates it from pyproject.toml). Dashboard path in bundled mode: `Path(NSBundle.mainBundle().resourcePath()) / "dashboard"` (guarded by `sys.frozen`). `just setup` installs py2app into the venv. First launch of unsigned bundle requires right-click → Open.

## Recently Changed Areas

| Date | File / Area | What changed |
| --- | --- | --- |
| 2026-06-09 | claudemon/keychain.py (new) | Reads Claude Code OAuth token from macOS Keychain; `pwd.getpwuid` (not `os.getlogin`); timeout=5 |
| 2026-06-09 | server.py | Added `/api/usage` route + `_usage_cache` (115s TTL) + `_call_usage_api()` |
| 2026-06-09 | dashboard/index.html | Added `#usage-strip` compact bar between tabs and stats |
| 2026-06-09 | dashboard/style.css | Added `.usage-*` classes + color state classes (green/yellow/orange/red) |
| 2026-06-09 | dashboard/app.js | Added `fmtResetsAt`, `colorClass`, `renderUsageStrip`, `fetchUsage`; polls every 120s |
| 2026-06-08 | popover.py | WKWebView now uses `nonPersistentDataStore` + `NSURLRequestReloadIgnoringLocalCacheData`; no stale cache across reinstalls |
| 2026-06-08 | server.py | Added `Cache-Control: no-store` to all responses via `_respond` |
| 2026-06-08 | dashboard/app.js | `SCALE_X` gains `type: 'category'`; `fmtHour` replaces `toLocaleTimeString`; `bucketLabel` uses day-of-month for day views, midnight-crossing date prefix for hour views; custom picker open uses `display='block'` |
| 2026-06-08 | claudemon/_version.py (new) | Runtime version source of truth; auto-bumped by pre-commit hook |
| 2026-06-08 | scripts/bump_version.py (new) | Bumps version in both pyproject.toml and _version.py |
| 2026-06-08 | scripts/pre-commit.sh (new) | Auto-bumps patch version on every commit (skips merge commits) |
| 2026-06-08 | justfile | Added install-hooks, bump-patch/minor/major recipes |
| 2026-06-08 | server.py | Added `_APP_VERSION` from `_version.py`; injected as `_version` into `/api/config` response |
| 2026-06-08 | dashboard/index.html | Renamed "Today"→"12H" tab; added Custom tab + `#custom-picker` div; added `#footer-version` span |
| 2026-06-08 | dashboard/style.css | Added picker styles (`#custom-picker`, `.picker-row`, `.picker-field`, `#custom-apply`, `.picker-error`); `.footer-version` |
| 2026-06-08 | dashboard/app.js | Added `isHourBucket`, `isHourView`, `viewBuckets` (replacing `isDayView`, `dayViewBuckets`); extended pad functions for `custom:` range; added `toDatetimeLocal`, `updateCustomTabLabel`; wired Custom tab interactions; `renderFooter` now shows version |
| 2026-06-08 | tests/test_server.py | Added `test_range_custom_timestamps`, `test_range_custom_via_endpoint`, `test_config_includes_version` |
| 2026-06-08 | CLAUDE.md | Added Versioning section with bump rules |
| 2026-06-08 | db.py | Added `bucket` param + `p50_tokens_per_task`/`max_tokens_per_task` to `query_tasks`; added `query_query_breakdown` |
| 2026-06-08 | server.py | Added `/api/queries` route; pass `bucket` param to `query_tasks`; sessions default limit now 10 |
| 2026-06-08 | dashboard/index.html | Section reorder (stats→tokens→sessions→tasks→queries→models→budget); updated legends; p50/max legend items |
| 2026-06-08 | dashboard/style.css | `.leg-line.leg-dashed` for p50 legend; `#sessions-list` max-height 188px + scroll |
| 2026-06-08 | dashboard/app.js | New `padQueries`, `renderQueryChart` (stacked), `api.queries`; p50/max lines on both charts; hourly day views; `dayViewStart` helper; `setViewMode` simplified |
| 2026-06-08 | tests/test_db.py | 5 new tests for `query_tasks` p50/max + hourly, `query_query_breakdown` top-N/few/hourly |
| 2026-06-08 | tests/test_server.py | 3 new tests for `/api/queries`, `/api/tasks` p50/max fields |
| 2026-06-08 | db.py | Removed `DB_PATH`; `connect()` always returns `":memory:"` (no persistent file) |
| 2026-06-08 | app.py | Removed `DB_PATH`; added `sys.frozen` guard for bundled dashboard path; imports `NSBundle` |
| 2026-06-08 | setup.py (new) | py2app bundle config; subclasses build command to clear install_requires |
| 2026-06-08 | justfile | Added `build` and `install-app` recipes |
| 2026-06-08 | pyproject.toml | Added `py2app>=0.28` to dev deps |
| 2026-06-08 | .gitignore | Added `build/` and `dist/` |
| 2026-06-08 | tests/conftest.py | `conn` fixture now calls `db.connect()` instead of constructing connection manually |
| 2026-06-07 | All | Full implementation complete — all 10 tasks delivered, 36 tests, 87% coverage |
| 2026-06-07 | popover.py | NSPopover → NSPanel (resizable); lazy init; `orderFrontRegardless` + `activateIgnoringOtherApps_` |
| 2026-06-07 | server.py + db.py | Local-timezone bucketing via `_tz_offset_ms()` + `_local_trunc()`; `day:X` drill-down range |
| 2026-06-07 | dashboard/ | Today = stat counters; 7d/30d gap-filling; chart click → day drill-down; hourly x-axis for today; session-title task labels |
