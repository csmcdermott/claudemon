# Collapsible Sections + Skills & MCP Usage — Design Spec

| Field | Value |
| --- | --- |
| **Date** | 2026-06-12 |
| **Status** | Approved |
| **Scope** | db.py · indexer.py · server.py · dashboard/index.html · dashboard/app.js |

---

## Overview

Two related changes shipped together:

1. **Collapsible sections** — every dashboard section after "Daily tokens + cache hit %" becomes a collapsible panel, all collapsed by default, toggled by clicking the section header.
2. **Skills & MCP usage panels** — two new collapsible sections ("Skills used", "MCP tools") appended after "Model breakdown", showing call count, p50 output tokens, and max output tokens per entry.

---

## Motivation

The dashboard is growing tall. Collapsible sections let users focus on what they care about without removing any data. Skills and MCP usage complete the picture of "what is Claude actually doing with my tokens" — currently invisible because the indexer only stores aggregate token counts per message, not the tool calls within.

---

## Data Model

### New table: `tool_uses`

```sql
CREATE TABLE IF NOT EXISTS tool_uses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT REFERENCES sessions(session_id),
    query_id      TEXT,
    timestamp     INTEGER,
    tool_type     TEXT,     -- 'skill' | 'mcp'
    tool_name     TEXT,     -- e.g. 'brainstorming' | 'playwright'
    output_tokens INTEGER DEFAULT 0,
    UNIQUE (session_id, query_id, timestamp, tool_type, tool_name)
);
CREATE INDEX IF NOT EXISTS idx_tool_uses_ts ON tool_uses(timestamp);
```

`output_tokens` is the output token count of the assistant response that contained this tool call — a proxy for response cost. One response containing multiple tool calls produces one row per unique `(tool_type, tool_name)` combination; the UNIQUE constraint deduplicates on re-index.

### New DB function: `insert_tool_use`

```python
def insert_tool_use(conn, session_id, query_id, timestamp, tool_type, tool_name, output_tokens):
    with _LOCK:
        conn.execute("""
            INSERT OR IGNORE INTO tool_uses
                (session_id, query_id, timestamp, tool_type, tool_name, output_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, query_id, timestamp, tool_type, tool_name, output_tokens))
        conn.commit()
```

### New DB function: `query_tool_usage`

```python
def query_tool_usage(conn, range_ts):
    start_ms, end_ms = range_ts
    rows = conn.execute("""
        SELECT tool_type, tool_name, output_tokens
        FROM tool_uses
        WHERE timestamp BETWEEN ? AND ?
        ORDER BY tool_type, tool_name
    """, (start_ms, end_ms)).fetchall()
```

All rows fetched; grouped by `(tool_type, tool_name)` in Python to collect the full `output_tokens` distribution needed for p50/max. Computes p50 using the lower-median formula (`sorted[(n-1)//2]`) — same pattern as `query_tasks` and `query_query_breakdown`. Returns:

```python
{
    "skills": [{"name": str, "calls": int, "p50_output_tokens": int, "max_output_tokens": int}, ...],
    "mcp":    [{"name": str, "calls": int, "p50_output_tokens": int, "max_output_tokens": int}, ...],
}
```

Both lists sorted by `calls` descending.

---

## Indexer Changes

Inside the existing `assistant` record branch in `indexer.py`, after extracting `output_tokens`:

```python
for block in msg.get("content", []):
    if block.get("type") != "tool_use":
        continue
    name = block.get("name", "")
    if name == "Skill":
        tool_type = "skill"
        tool_name = block.get("input", {}).get("skill", "unknown")
    elif name.startswith("mcp__"):
        tool_type = "mcp"
        # "mcp__plugin_playwright_playwright__browser_navigate" → "playwright"
        # "mcp__claude_ai_Google_Drive__copy_file"             → "google-drive"
        # "mcp__claude_ai_Gmail__authenticate"                 → "gmail"
        service = name.split("__")[1]
        if service.startswith("plugin_"):
            service = service.removeprefix("plugin_")
            tool_name = service.split("_")[0].lower()   # "playwright_playwright" → "playwright"
        elif service.startswith("claude_ai_"):
            tool_name = service.removeprefix("claude_ai_").lower().replace("_", "-")  # "google-drive"
        else:
            tool_name = service.split("_")[0].lower()
    else:
        continue
    if current_query_id and ts:
        db.insert_tool_use(
            conn, session_id, current_query_id, ts,
            tool_type, tool_name, output_tokens,
        )
```

`current_query_id` is already tracked in the assistant record branch. No new state needed.

**Assumption:** Claude Code JSONL assistant records store the full API response body, including `message.content` with `tool_use` blocks. The indexer already reads `msg = record.get("message", {})` — walking `msg.get("content", [])` is additive and safe if content is absent or empty.

---

## API

### New endpoint: `GET /api/tools`

Accepts the same `range` parameter as all other endpoints. Calls `_range_to_timestamps()` (existing helper) and `db.query_tool_usage()`.

```
GET /api/tools?range=7d
```

Response:
```json
{
  "skills": [
    {"name": "brainstorming", "calls": 23, "p50_output_tokens": 2048, "max_output_tokens": 13000},
    {"name": "tdd",           "calls": 12, "p50_output_tokens": 1800, "max_output_tokens": 9400}
  ],
  "mcp": [
    {"name": "playwright",   "calls": 45, "p50_output_tokens": 1024, "max_output_tokens": 8000},
    {"name": "google-drive", "calls": 18, "p50_output_tokens": 640,  "max_output_tokens": 3200}
  ]
}
```

Empty arrays when no data for the range. HTTP 500 `{"error": "..."}` on failure (standard error shape).

---

## Dashboard — HTML

### Collapsible wrapper pattern

Replace every `<section>` after "Daily tokens" with this structure:

```html
<div class="csec">
  <div class="csec-hdr" data-target="sessions-body">
    <span class="csec-title">Recent sessions</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body" id="sessions-body">
    <!-- existing section content -->
  </div>
</div>
```

Sections to wrap (in order):
1. Recent sessions
2. Tasks & queries
3. Queries by token volume
4. Model breakdown
5. Skills used *(new)*
6. MCP tools *(new)*

The "Daily tokens + cache hit %" chart section remains always-visible (not collapsible).

### New sections (appended after Model breakdown)

```html
<div class="csec">
  <div class="csec-hdr" data-target="skills-body">
    <span class="csec-title">Skills used</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body" id="skills-body">
    <div id="skills-list"></div>
  </div>
</div>

<div class="csec">
  <div class="csec-hdr" data-target="mcp-body">
    <span class="csec-title">MCP tools</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body" id="mcp-body">
    <div id="mcp-list"></div>
  </div>
</div>
```

---

## Dashboard — CSS

New rules in `style.css`:

```css
.csec { background: var(--surface); border-radius: 6px; margin-bottom: 6px; overflow: hidden; }

.csec-hdr {
  display: flex; align-items: center; justify-content: space-between;
  padding: 7px 10px; cursor: pointer; user-select: none;
}
.csec-hdr:hover { background: rgba(255,255,255,0.03); }

.csec-title { font-size: 11px; color: var(--text-muted); }

.csec-chevron { font-size: 9px; color: var(--text-dim); transition: transform 0.15s ease; }
.csec.open .csec-chevron { transform: rotate(90deg); }

.csec-body { display: none; padding: 0 10px 8px; }
.csec.open .csec-body { display: block; }

/* Tool rows (shared by model breakdown, skills, mcp) */
.tool-row { display: flex; align-items: center; gap: 6px; margin-bottom: 5px; }
.tool-name { font-size: 10px; color: var(--text-muted); width: 80px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tool-bar-wrap { flex: 1; background: var(--bg); border-radius: 2px; height: 4px; }
.tool-fill { height: 4px; border-radius: 2px; }
.tool-meta { font-size: 9px; color: var(--text-dim); white-space: nowrap; flex-shrink: 0; }

.skill-fill { background: #4ade80; }
.mcp-fill   { background: #38bdf8; }
```

The existing `.sec-title`, `.sec-hdr` rules on unwrapped sections remain untouched (the "Daily tokens" chart section keeps its current markup).

---

## Dashboard — JavaScript

### Collapsible toggle

Single delegated listener wired in `initCollapsibles()`, called once on load:

```javascript
function initCollapsibles() {
    document.querySelectorAll('.csec-hdr').forEach(hdr => {
        hdr.addEventListener('click', () => hdr.closest('.csec').classList.toggle('open'));
    });
}
```

All `.csec` divs start without the `open` class (collapsed by default) — no JS needed to set initial state.

### `renderSkills(skills)` and `renderMcp(mcp)`

Both follow the same shape:

```javascript
function renderSkills(skills) {
    const el = document.getElementById('skills-list');
    if (!skills.length) { el.innerHTML = '<div class="empty">No skill usage in this range</div>'; return; }
    const max = skills[0].calls;
    el.innerHTML = skills.map(s => {
        const pct = Math.round(s.calls / max * 100);
        return `<div class="tool-row">
          <div class="tool-name" title="${esc(s.name)}">${esc(s.name)}</div>
          <div class="tool-bar-wrap"><div class="tool-fill skill-fill" style="width:${pct}%"></div></div>
          <div class="tool-meta">×${s.calls} · ${fmt(s.p50_output_tokens)} 50% / ${fmt(s.max_output_tokens)} max</div>
        </div>`;
    }).join('');
}
```

`fmt()` is the existing token formatter (already in app.js). `esc()` is the existing XSS helper. `renderMcp` is identical with `mcp-fill` and `mcp` data.

### Fetching `/api/tools`

Added to the existing `refreshAll()` fetch chain alongside `/api/stats`, `/api/timeline`, etc:

```javascript
const [stats, timeline, tasks, queries, tools] = await Promise.all([
    api.stats(range), api.timeline(range), api.tasks(range), api.queries(range), api.tools(range)
]);
// ...
renderSkills(tools.skills);
renderMcp(tools.mcp);
```

`api.tools` follows the existing `api.*` pattern (fetch + `.json()`).

---

## Model Breakdown Migration

The existing `#models-list` section gets wrapped in `.csec` like all others. The render logic in `renderModels()` is unchanged — only the surrounding HTML changes.

---

## Testing

New tests in `tests/test_db.py`:
- `test_insert_tool_use_basic` — insert skill + mcp rows, verify `query_tool_usage` returns correct calls/p50/max
- `test_tool_use_deduplication` — same `(session, query, ts, type, name)` inserted twice → only one row
- `test_tool_use_empty_range` — no rows in range → empty skills and mcp lists
- `test_tool_use_p50` — odd and even row counts produce correct lower-median

New tests in `tests/test_server.py`:
- `test_tools_endpoint_returns_skills_and_mcp` — fixture with tool_use rows, verify `/api/tools` shape
- `test_tools_endpoint_empty` — no data → `{"skills": [], "mcp": []}`

---

## Out of Scope

- Collapse-state persistence across sessions (no localStorage — default collapsed is always the right starting point)
- Per-tool breakdown within an MCP service (service-level grouping is sufficient)
- Token attribution to individual tool calls within a multi-tool response (full response `output_tokens` attributed to each tool in that response)
- Chart views for skills/MCP over time (ranked list is sufficient for v1)
