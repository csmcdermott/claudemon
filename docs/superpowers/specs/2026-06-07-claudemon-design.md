# claudemon — Design Spec

| Field | Value |
|---|---|
| **Date** | 2026-06-07 |
| **Status** | Approved |

## Overview

A macOS menu bar app that monitors Claude Code usage in real time. Parses local Claude Code session files (`~/.claude/projects/**/*.jsonl`) to display token usage, cache efficiency, query/task analytics, and active session state. No Anthropic API calls required; all data is local.

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Menu bar | `rumps` | Pythonic macOS status bar; wraps AppKit NSStatusItem |
| Popup panel | PyObjC `NSPopover` + `WKWebView` | Native macOS popover (arrow, dismiss-on-click-outside, animation); avoids floating window |
| Dashboard UI | HTML / CSS / Chart.js | Full chart library access; hot-reloadable during development |
| Local server | Python `http.server` (stdlib) | Serves dashboard HTML + JSON API; bound to localhost only; no extra dependency |
| File watching | `watchdog` | Cross-platform file system events; watches JSONL and session files |
| Data index | SQLite via `sqlite3` (stdlib) | Persistent processed index; incremental updates via byte-offset cursors |
| Config | JSON (`~/.claudemon/config.json`) | Personal budget and preferences |

**Dependencies introduced:** `rumps`, `watchdog`, `pyobjc-framework-WebKit` (for WKWebView). PyObjC ships with macOS Python; rumps and watchdog are pip-installable.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│               macOS Integration Layer            │
│  app.py          popover.py       statusitem.py  │
│  rumps.App       NSPopover +      icon · tokens  │
│  entry point     WKWebView        · state dot    │
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│                   Data Layer                     │
│  watcher.py        indexer.py        db.py       │
│  watchdog          JSONL parser →    SQLite       │
│  observer          SQLite writer     schema +     │
│                                      query API   │
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│                 Dashboard Layer                  │
│  server.py                  dashboard/           │
│  http.server thread         index.html           │
│  /api/stats                 Chart.js             │
│  /api/sessions              CSS                  │
│  /api/timeline                                   │
└─────────────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│                    Storage                       │
│  ~/.claudemon/claudemon.db   ~/.claudemon/config.json  │
│  ~/.claude/projects/**/*.jsonl  (read-only source)     │
│  ~/.claude/sessions/*.json      (session state)        │
└─────────────────────────────────────────────────┘
```

---

## Module Descriptions

| Module | Responsibility |
|---|---|
| `app.py` | Entry point. Initialises rumps app, wires together watcher, indexer, server, and status item. Runs initial full index on startup. |
| `statusitem.py` | Manages the menu bar icon. Displays today's output token count and a session state dot. Refreshes on watcher events. |
| `popover.py` | PyObjC NSPopover containing a WKWebView. Shows/hides on icon click. Loads `http://localhost:{port}/`. |
| `watcher.py` | watchdog `Observer` watching `~/.claude/projects/` (JSONL) and `~/.claude/sessions/` (session state). Dispatches events to indexer and statusitem. |
| `indexer.py` | Parses JSONL deltas (seeking to stored byte offset), extracts messages, writes to SQLite, updates `file_cursors`. Also assigns task IDs using multi-signal heuristic. |
| `db.py` | SQLite schema definition and query API (no raw SQL outside this module). |
| `server.py` | Single-threaded `http.server` on a random localhost port. Handles `/` (HTML) and `/api/*` (JSON). Queries `db.py`. |
| `dashboard/` | Static HTML + Chart.js dashboard. Fetches `/api/stats`, `/api/timeline`, `/api/tasks`, `/api/sessions` on load and on a 30-second poll. |

---

## SQLite Schema

```sql
CREATE TABLE sessions (
    session_id   TEXT PRIMARY KEY,
    project      TEXT,      -- directory slug, e.g. "HomeHQ"
    title        TEXT,      -- from ai-title record
    started_at   INTEGER,   -- unix ms
    ended_at     INTEGER,   -- unix ms, updated as records arrive
    git_branch   TEXT
);

CREATE TABLE messages (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id             TEXT REFERENCES sessions(session_id),
    task_id                TEXT,   -- assigned by indexer, e.g. "da4f16:3"
    timestamp              INTEGER,
    model                  TEXT,
    input_tokens           INTEGER,
    output_tokens          INTEGER,
    cache_creation_tokens  INTEGER,
    cache_read_tokens      INTEGER
);

CREATE TABLE file_cursors (
    file_path      TEXT PRIMARY KEY,
    last_offset    INTEGER,   -- byte offset for incremental parse
    last_modified  REAL       -- os.stat mtime
);

CREATE INDEX idx_messages_ts ON messages(timestamp);
CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_messages_task ON messages(task_id);
```

`task_id` format: `{session_id_prefix}:{task_number}` — unique within the database, stable across re-indexing.

---

## Task Boundary Detection

A new task begins within a session when **any** of these signals is detected (checked in order):

1. **New session** — every session start is a task boundary.
2. **`/clear` command** — user message content (stripped) equals `/clear`; explicit intent to reset context.
3. **Git branch change** — `gitBranch` field on the new record differs from the previous record's branch.
4. **30-minute gap** — timestamp gap between consecutive messages exceeds 30 minutes.

The threshold (30 min) is configurable in `~/.claudemon/config.json`. Task IDs are assigned at index time; recomputing them requires a full re-index (triggered automatically if the threshold changes).

A **query** is defined as one user-initiated round trip: a non-meta, non-tool-result user message plus all subsequent assistant messages until the next user message.

---

## Menu Bar Status Item

The status item shows three elements from left to right:

```
◆  1.2M  ●
```

| Element | Meaning |
|---|---|
| `◆` | Static app icon (SF Symbol or custom) |
| `1.2M` | Today's total output tokens, formatted (k / M) |
| `●` | Session state dot |

**Session state dot colours:**

| State | Colour | Condition |
|---|---|---|
| No sessions | `#2a2a35` (dark, muted) | No `~/.claude/sessions/*.json` files present |
| Idle | `#f59e0b` (amber) | Session file exists, `status != "busy"` |
| Working | `#22c55e` (green, pulsing) | Any session file has `status == "busy"` |

Session state is determined by re-reading all `~/.claude/sessions/*.json` files on any change event. If multiple sessions exist, the highest-priority state wins (working > idle > none).

---

## Dashboard Panel

The popup panel is a native `NSPopover` anchored to the status item. Width: 380px. Panel is scrollable. WKWebView loads `http://localhost:{port}/`.

### Sections (top to bottom)

1. **Active session banner** *(conditional)* — shown only when a session is working. Displays project name, elapsed time, live in/out token counts, task count.

2. **Header** — app title + time range tabs: Today · 7d · 30d · All.

3. **Stats row** (4 columns) — Sessions · Input tokens · Output tokens · Cache hit rate. Each shows delta vs previous equivalent period.

4. **Chart: Daily tokens + cache hit %** — grouped bars (output purple, input blue) on left Y axis; cache hit rate as a green line on right Y axis. Today tab switches to hourly buckets.

5. **Chart: Queries + tokens/query** — query count bars (orange) on left Y axis; tokens/query line (yellow) on right Y axis.

6. **Chart: Tasks & queries** — stacked bar chart where each bar = one day, each segment = one task (colour-coded by task slot), bar height = total queries. Hover tooltip shows: day summary, then per-task query count. Tokens/task line (yellow) on right Y axis.

7. **Budget bar** — output tokens used vs personal soft limit (from config). Label shows absolute + percentage. Configurable via settings.

8. **Model breakdown** — horizontal bar per model showing proportion of total messages; right-aligned label shows `Xk in / XM out`.

9. **Recent sessions** — most recent sessions scoped to selected time range (default limit: 5). Per row: state dot · title · project + duration · `Xk in / Xk out` · `N tasks · N queries`.

10. **Footer** — lifetime cache reads + session count. Quit button.

---

## HTTP API

All endpoints served by `server.py` on a random localhost port chosen at startup. Bound to `127.0.0.1` only.

| Method | Path | Query params | Returns |
|---|---|---|---|
| GET | `/` | — | Dashboard HTML |
| GET | `/api/stats` | `range=today\|7d\|30d\|all` | Totals: sessions, input_tokens, output_tokens, cache_hit_rate, model_breakdown, task_count, query_count, tokens_per_query, tokens_per_task |
| GET | `/api/timeline` | `range`, `bucket=1h\|1d` | Array of `{date, input_tokens, output_tokens, cache_hit_rate}` |
| GET | `/api/tasks` | `range` | Array of `{date, tasks: [{task_id, queries, input_tokens, output_tokens}], avg_tokens_per_task}` |
| GET | `/api/sessions` | `range`, `limit=5`, `active=false` | Array of sessions with aggregated token + task + query counts. `active=true` returns only currently-running sessions (for banner refresh). |
| GET | `/api/config` | — | Current config JSON |
| POST | `/api/config` | — | Body: partial config; merges and saves |

---

## Config File

Location: `~/.claudemon/config.json`

```json
{
  "weekly_output_budget": 8000000,
  "task_gap_minutes": 30,
  "server_port": 0
}
```

`server_port: 0` means pick a random available port on startup (recommended). Set a fixed port to avoid re-opening the panel after restarts during development.

---

## Data Flow

1. **Startup** — `indexer.py` scans all `~/.claude/projects/**/*.jsonl`. For each file, checks `file_cursors`; if new or modified, parses from last offset. Writes sessions + messages to SQLite. Assigns task IDs. Marks `file_cursors`. Takes ~100–200ms for ~370 sessions.

2. **File watch loop** — `watcher.py` receives `FileModifiedEvent` or `FileCreatedEvent` for new JSONL writes. Dispatches to `indexer.py` for delta parse. Dispatches `FileModifiedEvent` for `~/.claude/sessions/*.json` to `statusitem.py` for state update.

3. **Token display update** — after any index delta, `statusitem.py` re-queries `db.py` for today's output total and refreshes the menu bar label.

4. **Panel open** — `popover.py` shows NSPopover; WKWebView loads dashboard from local server. Dashboard JS fetches `/api/stats` and `/api/timeline` and `/api/tasks` with the current range tab's value.

5. **Panel live update** — dashboard polls `/api/stats` every 30 seconds while visible. Active session banner is refreshed every 5 seconds via a separate `/api/sessions?active=true` call.

---

## Project Structure

```
claudemon/
├── claudemon/
│   ├── __init__.py
│   ├── app.py           # rumps.App entry point
│   ├── statusitem.py    # menu bar icon + state dot
│   ├── popover.py       # NSPopover + WKWebView
│   ├── watcher.py       # watchdog observer
│   ├── indexer.py       # JSONL parser + task detector
│   ├── db.py            # SQLite schema + queries
│   ├── server.py        # local HTTP server + API handlers
│   └── dashboard/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── tests/
├── docs/
│   └── agent/
│       ├── project-analysis.md
│       └── lessons.md
├── scripts/
├── CLAUDE.md
├── justfile
├── pyproject.toml
└── README.md
```

---

## Testing Strategy

- **Unit tests** — `indexer.py` (JSONL parsing, task boundary detection with known fixture files), `db.py` (query correctness against a seeded in-memory SQLite), `server.py` (API response shape).
- **Integration tests** — full pipeline: write fixture JSONL → index → query API → assert response.
- **No mocking of SQLite** — tests use real in-memory SQLite (`":memory:"`).
- **Coverage target** — >80% per CLAUDE.md quality gates.

---

## Known Constraints

- Dashboard colors use the dark theme only; no light mode support in v1.
- Task boundary detection is heuristic; edge cases (very long uninterrupted sessions) may produce larger-than-expected tasks.
- The NSPopover WKWebView requires the app to run as a proper macOS app bundle or with appropriate entitlements; development via `python app.py` works but distribution requires packaging (e.g. `py2app`).
- No support for multiple simultaneous users or shared `~/.claude` directories.
