# Dashboard Hover Improvements — Design

**Date:** 2026-07-02
**Status:** Approved
**Scope:** Three independent hover/labeling improvements to the Chart.js dashboard. New feature → `just bump-minor` before committing.

## Motivation

Three usability issues with the dashboard's hover behaviors:

1. **Chart date tooltips are terse.** Hovering a bar shows only the x-axis label (`"11"` for day-of-month, `"8am"` for hours). The user wants a fuller, unambiguous label like `Jul 11` or `8am · Jul 2`.
2. **Skill / MCP name hover is a tiny hit target.** The full name only appears via the native `title` attribute on an 88px ellipsized `.tool-name` div. Per `docs/agent/lessons.md`, native `title` tooltips are unreliable in WKWebView, and the hit target is effectively just the ellipsis. Hovering the name should reliably show the full name.
3. **Queries are labeled by opaque IDs.** Tooltips show `027d99:1:1` (`sessionShortId:taskNum:queryNum`). The user wants human-readable names.

## Non-Goals

- No change to the x-axis tick labels themselves (they stay compact: `"11"`, `"8am"`). Only the *tooltip title* on hover gets the richer format.
- No persistence of prompt text beyond the in-memory DB (consistent with the app's in-memory-only architecture).
- No full-text search or query drill-down. Names appear in tooltips only.

---

## 1. Richer date/time tooltip titles

### Current behavior
- `bucketLabel(ts, range, prevTs)` returns compact labels used as both x-axis labels and (via `items[0].label`) tooltip titles.
- Query chart sets `tooltip.callbacks.title = items => items[0].label` in `initCharts` and again in `renderQueryChart`. Token chart uses the default tooltip (no title callback). Task chart sets callbacks in `renderTaskChart`.

### Change
Add a helper in `app.js`:

```js
function tooltipDateTitle(ts, range) {
  const md = new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); // "Jul 11"
  return isHourBucket(range) ? `${fmtHour(ts)} · ${md}` : md; // "8am · Jul 2"  /  "Jul 11"
}
```

- Reuses the exact `toLocaleDateString(undefined, { month: 'short', day: 'numeric' })` call already proven to work at the midnight-crossing label (app.js ~line 278) — avoids the `toLocaleTimeString` unreliability documented in lessons.
- Reuses existing `fmtHour(ts)` and `isHourBucket(range)`.

Each render function sets its own `tooltip.callbacks.title` using the padded array already stored at module level, resolving the timestamp by `dataIndex`:

- `renderTokenChart` → `_paddedTimeline[items[0].dataIndex].date`
- `renderQueryChart` → `_paddedQueries[items[0].dataIndex].date`
- `renderTaskChart` → `_paddedTasks[items[0].dataIndex].date`

```js
title: items => tooltipDateTitle(padded[items[0].dataIndex].date, range),
```

(where `padded` and `range` are in the render function's closure).

Per lessons ("don't set callbacks in initCharts if the render function overwrites them"), the title callback is set **only** in the render functions, not `initCharts`. If the token chart has no render function that currently sets tooltip callbacks, set them there where its padded array (`_paddedTimeline`) is in scope.

### Edge cases
- Empty/gap buckets still have a `.date` (padding functions generate all buckets), so lookup never yields `undefined`.

---

## 2. Skill / MCP hover anywhere on the name

### Current behavior
`renderSkills` / `renderMcp` produce:

```html
<div class="tool-name" title="${esc(s.name)}">${esc(s.name)}</div>
```

`.tool-name` is `width: 88px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap`. The only way to see the full name is the native `title` tooltip on that narrow, ellipsized element — unreliable in WKWebView.

### Change
Replace the native `title` with a custom CSS tooltip whose hover target is the **whole `.tool-row`**, matching the existing usage-strip custom-tooltip pattern (app.js ~lines 115–134).

Markup (both `renderSkills` and `renderMcp`):

```html
<div class="tool-row">
  <div class="tool-name">${esc(s.name)}</div>
  <div class="tool-bar-wrap"><div class="tool-fill skill-fill" style="width:${pct}%"></div></div>
  <div class="tool-meta">×${s.calls} · ${fmt(s.p50_output_tokens)} 50% / ${fmt(s.max_output_tokens)} max</div>
  <span class="tool-tip">${esc(s.name)}</span>
</div>
```

- Drop the `title="..."` attribute entirely.
- `${esc(...)}` is still required — the tooltip goes into `innerHTML`, and skill/MCP names originate from JSONL tool-use blocks.

CSS (`style.css`):

```css
.tool-row { position: relative; }
.tool-tip {
  visibility: hidden;
  position: absolute;
  bottom: 100%;
  left: 0;
  z-index: 10;
  background: #1c1c28;
  color: #ddd;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 4px;
  padding: 3px 7px;
  font-size: 12px;
  white-space: nowrap;
  pointer-events: none;
}
.tool-row:hover .tool-tip { visibility: visible; }
```

(Colors mirror the Chart.js tooltip / usage-tooltip styling for visual consistency.)

### Edge cases
- The tooltip shows for **every** row on hover, even when the name isn't truncated. This is acceptable and simpler than measuring overflow; the name is short and the tooltip is unobtrusive.

---

## 3. Query names from the first prompt

### Current behavior
Query identity is `query_id = f"{short_id}:{task_num}:{query_num}"`. Prompt text is never stored. `query_query_breakdown` returns `{query_id, total_tokens}` per query; the frontend tooltip shows `q.query_id`.

### Change — storage
New table in `db.py` `SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS queries (
    query_id    TEXT PRIMARY KEY,
    session_id  TEXT,
    text        TEXT
);
```

New writer in `db.py`:

```python
def upsert_query(conn, session_id, query_id, text):
    with _LOCK:
        conn.execute(
            "INSERT OR IGNORE INTO queries (query_id, session_id, text) VALUES (?, ?, ?)",
            (query_id, session_id, text),
        )
        conn.commit()
```

`INSERT OR IGNORE` keeps the **first** prompt seen for a query (the query-starting user message), and is idempotent across JSONL replays.

### Change — indexing (`indexer.py`)
In the `rec_type == "user" and _is_new_query(record)` branch, after computing `current_query_id`, extract and store the prompt text:

```python
text = _extract_prompt_text(record)          # first text block, whitespace-collapsed
if text:
    db.upsert_query(conn, session_id, current_query_id, text[:_QUERY_TEXT_MAX])
```

- `_QUERY_TEXT_MAX = 60` — **truncation happens at index time**; full prompts are never held in the DB.
- `_extract_prompt_text(record)` reuses the content-shape handling from `_is_clear_command`: `message.content` may be a list of `{type:"text", text}` blocks or a bare string. Join text blocks, `.strip()`, collapse internal whitespace runs to single spaces. Returns `""` when no text.
- Store the query text **before** the `continue`, so it's captured even if the query has no assistant response yet.

### Change — read (`db.py query_query_breakdown`)
`LEFT JOIN queries` to attach text; return it as a `text` field per query:

```sql
SELECT
    {trunc}                            AS bucket_ts,
    m.query_id                         AS query_id,
    q.text                             AS text,
    SUM(m.input_tokens + m.output_tokens) AS total_tokens
FROM messages m
LEFT JOIN queries q ON q.query_id = m.query_id
WHERE m.timestamp BETWEEN ? AND ?
GROUP BY bucket_ts, m.query_id
ORDER BY bucket_ts, total_tokens DESC
```

Each per-query dict becomes `{"query_id": ..., "text": ..., "total_tokens": ...}` (`text` may be `None`).

### Change — frontend (`app.js renderQueryChart`)
Tooltip label uses the name, falling back to the ID:

```js
const q = b.queries?.[item.dataset.queryIndex];
const name = q?.text || q?.query_id || item.dataset.label;
const shown = name.length > 50 ? name.slice(0, 49) + '…' : name;
return ` ${shown}: ${fmt(item.raw)} tokens`;
```

- Display truncation (~50) is separate from the 60-char storage cap.
- Chart.js tooltips render on a `<canvas>`, not `innerHTML`, so no `esc()` is needed here (and none is applied to `query_id` today).

### Edge cases
- Queries whose starting user message has no text (rare) fall back to `query_id`.
- `/clear` commands produce a query with text `"/clear"` — harmless.

---

## Testing

- **db.py**: `upsert_query` inserts once and ignores replays; `query_query_breakdown` returns `text` and falls back to `None`/`query_id` when a query has no stored text.
- **indexer.py**: indexing a fixture with a text prompt stores the truncated text; string-content and list-content message shapes both extract correctly; text longer than 60 chars is truncated at index time; a query with no text stores nothing (LEFT JOIN yields `None`).
- **JS** (date helper, tooltip): no JS test runner exists (documented deferral in project-analysis). Verify manually in the app; keep the helper small and pure so it *could* be unit-tested later.
- Coverage must stay ≥ 80%; `just lint` clean; `just test` green.

## Files touched

| File | Change |
| --- | --- |
| `claudemon/db.py` | `queries` table in SCHEMA; `upsert_query()`; `LEFT JOIN queries` in `query_query_breakdown` |
| `claudemon/indexer.py` | `_QUERY_TEXT_MAX`, `_extract_prompt_text()`; `upsert_query` call in the new-query branch |
| `claudemon/dashboard/app.js` | `tooltipDateTitle()`; title callbacks in render functions; `renderSkills`/`renderMcp` markup; query tooltip label |
| `claudemon/dashboard/style.css` | `.tool-row` positioning + `.tool-tip` rules |
| `tests/test_db.py`, `tests/test_indexer.py` | New tests for the above |

## Versioning

Run `just bump-minor` before committing (new feature). The pre-commit hook bumps patch on top — expected.
