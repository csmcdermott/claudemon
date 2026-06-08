## Project Overview

| Field | Value |
| --- | --- |
| **Project name** | claudemon |
| **Purpose** | macOS menu bar app to monitor Claude Code usage in real time — token counts, cache hit rates, query/task analytics, active session state |
| **Target release** | v1.0 (personal use) |
| **Last updated** | 2026-06-07 (implementation complete) |

## Tech Stack

| Layer | Technology | Notes |
| --- | --- | --- |
| Menu bar | rumps | Wraps AppKit NSStatusItem |
| Popup panel | PyObjC NSPopover + WKWebView | Native macOS popover; WKWebView renders HTML dashboard |
| Dashboard UI | HTML / CSS / Chart.js | Fetches JSON from local server |
| Local HTTP server | Python stdlib http.server | Random localhost port; 127.0.0.1 only |
| File watching | watchdog | Watches ~/.claude/projects/**/*.jsonl and ~/.claude/sessions/*.json |
| Data index | SQLite (stdlib sqlite3) | Persistent; incremental via byte-offset cursors in file_cursors table |
| Config | JSON | ~/.claudemon/config.json |
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
- SQLite as processed index with byte-offset cursors for incremental O(new bytes) indexing
- Task boundary detection uses multi-signal heuristic: 30-min gap OR git branch change OR /clear command OR new session
- NSPopover for native macOS UX (vs pywebview floating window)
- Local HTTP server allows full Chart.js dashboard inside WKWebView

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
| HTTP server | claudemon/server.py | /api/stats, /api/timeline, /api/tasks, /api/sessions, /api/config |

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
GET  /api/stats?range=today|7d|30d|all
GET  /api/timeline?range=...&bucket=1h|1d
GET  /api/tasks?range=...
GET  /api/sessions?range=...&limit=5&active=false
GET  /api/config
POST /api/config
POST /api/quit   → sends SIGTERM to process (used by dashboard Quit button)
```

Full spec: `docs/superpowers/specs/2026-06-07-claudemon-design.md`
Implementation plan: `docs/superpowers/plans/2026-06-07-claudemon.md`

**Error shape:** HTTP 500 with `{"error": "message"}` JSON body.

## Known Issues / Technical Debt

| Date | Area | Description |
| --- | --- | --- |
| 2026-06-07 | Distribution | NSPopover + WKWebView requires app bundle or entitlements for distribution; dev via `python app.py` works fine |
| 2026-06-07 | Task detection | Heuristic-based; very long uninterrupted sessions may produce unexpectedly large tasks |
| 2026-06-07 | SQLite reads | Read functions (query_stats etc.) don't hold _LOCK. Concurrent read+write is safe in WAL mode for a single user but not fully serialised. |
| 2026-06-07 | Query chart | queries/day is approximated by distributing total queries proportional to daily output token share — not exact per-day counts |

## Implementation Notes

- **venv required**: System Python is Homebrew-managed and externally locked. All `just` recipes use `.venv/bin/` prefixes. Always `source .venv/bin/activate` or use `just` to run tools.
- **macOS-only modules excluded from coverage**: `app.py`, `popover.py`, `statusitem.py`, `watcher.py` are omitted from coverage measurement (require macOS event loop). Covered modules target ≥80%.
- **session_id from JSONL content, not filename**: The indexer reads `sessionId` from JSONL records; the filename stem is the fallback. In production they always match (Claude Code names files by UUID), but tests use fixture filenames like `abc123.jsonl`.
- **`/api/quit` fires SIGTERM in a daemon thread**: Ensures the HTTP response is sent before the process exits.

## Recently Changed Areas

| Date | File / Area | What changed |
| --- | --- | --- |
| 2026-06-07 | All | Full implementation complete — all 10 tasks delivered, 36 tests, 87% coverage |
| 2026-06-07 | db.py | Added thread lock, idempotent INSERT OR IGNORE, session range lower-bound filter, FK enforcement |
| 2026-06-07 | indexer.py | Fixed query_id fallback (was :0:, now :1:), fixed isSidechain guard |
| 2026-06-07 | server.py | Fixed port-0 TOCTOU, POST path parsing (self.path → urlparse), GET / error handling |
