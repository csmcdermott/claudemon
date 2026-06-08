# Dashboard Enhancements — Design Spec

**Date:** 2026-06-08  
**Status:** Approved

---

## Overview

Five enhancements to the claudemon dashboard:

1. p50 + max lines on queries and tasks charts (replacing the single average line)
2. Stacked queries chart: top-10 individual queries by token volume + "other" segment
3. Day/today view shows hourly charts alongside the existing stat-counter summary
4. Section reorder
5. Recent sessions: cap visible rows at 4, scroll to reveal more; fetch 10 from API

---

## 1. p50 + max Right-Axis Lines

### Scope
Applies to both the **Tasks & queries** chart and the **Queries + tokens** chart (see §2).

### Data computation
SQLite has no native MEDIAN function. Both percentile values are computed in Python after fetching per-entity token sums.

**For queries chart:**  
p50 and max come from `query_query_breakdown` (§2) via `/api/queries`. `query_timeline` is **not changed** for this feature.

**For tasks chart:**  
`query_tasks` already returns per-task token totals within each day/hour bucket object. Python computes p50 and max from that task list.

New fields appended to each bucket dict in `query_tasks`:
```
p50_tokens_per_task   int
max_tokens_per_task   int
```

The existing `avg_tokens_per_task` field is retained (used in today-summary stat counter) but the **chart line is removed** — replaced by p50 and max.

### Visual
- p50 line: yellow (`#fcd34d`), 1.5px, dashed
- max line: red-orange (`#f87171`), 1.5px, solid
- Both on `yRight` axis; `yRight` tick formatter: `k`/`M` shorthand
- Legend updated: "p50 tok" + "top tok" (replacing "tok/query" / "tok/task")
- Tooltip: ` p50: 8k` / ` max: 48k` on hover

---

## 2. Stacked Queries Chart

### New endpoint: `GET /api/queries`

Query parameters:
- `range` — same as other endpoints
- `bucket` — `1h` or `1d` (default `1d`)

### New DB function: `query_query_breakdown(conn, range_ts, bucket, tz_offset_ms, top_n=10)`

Returns one dict per bucket:
```json
{
  "date": 1749340800000,
  "queries": [
    {"query_id": "abc:1:1", "total_tokens": 48000},
    ...
  ],
  "other_count": 23,
  "other_tokens": 12000,
  "p50_tpq": 8000,
  "max_tpq": 48000
}
```

- `queries` contains up to `top_n=10` entries, sorted descending by `total_tokens`
- If there are more than `top_n` queries in a bucket, the remainder is collapsed into `other_count` / `other_tokens`
- p50 and max are computed over **all** queries in the bucket (not just top 10)

Implementation: fetch all `(bucket_ts, query_id, SUM(tokens))` rows in range, group in Python by bucket, sort descending, split at top_n.

### Chart changes (frontend)

The `queryChart` changes from "query count bars + avg line" to:

**Left axis (stacked bars — total tokens):**
- Up to 10 colored segments per bucket (one per top query, using PALETTE)
- An 11th grey segment for "other" if `other_count > 0`
- Left axis label: `← tokens` (was `← queries`)

**Right axis (two lines):**
- p50 tokens/query (yellow dashed)
- max tokens/query (red-orange solid)

**Tooltip:**
- On a colored segment: `query_id: 48k tokens`
- On the grey segment: `+23 other: 12k tokens`
- On a line: `p50: 8k` / `max: 48k`

**Gap-filling:**
New `padQueries(queriesData, range)` function mirrors `padTasks` — fills missing day or hour buckets with empty objects.

**Module-level state:**
Add `_paddedQueries = []` alongside `_paddedTimeline` and `_paddedTasks`. The click drill-down handler reads `date` from `_paddedQueries[idx]` if `_paddedTimeline[idx]` is null.

**API call:**
```js
queries(range) { return api.get(`/api/queries?range=${range}&bucket=${isDayView(range) ? '1h' : '1d'}`); }
```

**`refresh()` change:**  
Add `api.queries(currentRange)` to the `Promise.all` alongside stats, timeline, tasks, sessions, config. Pass the result to `renderQueryChart`.

**`queryChart` init:**  
Add `stacked: true` to the `yLeft` scale in `initCharts` (mirrors the existing `taskChart` setup).

---

## 3. Day View — Hourly Charts

### Behaviour change

`setViewMode(range)` currently hides all `.chart-section` elements when in a day view. New behaviour: **show chart sections in day views**. The `today-summary` stat counters remain visible above the charts.

### Hourly buckets

Any day view (`range === 'today'` or `range.startsWith('day:')`) passes `bucket=1h` to all three chart endpoints:
- `/api/timeline?bucket=1h`
- `/api/tasks?bucket=1h` (requires new bucket param — see below)
- `/api/queries?bucket=1h`

### `query_tasks` bucket param

Add `bucket: str = "1d"` parameter to `query_tasks`. Internally uses `_local_trunc(bucket_ms, tz_offset_ms)` with `bucket_ms = 3_600_000` for `1h` or `86_400_000` for `1d`. No other logic changes.

Server passes `bucket` from the `?bucket=` query param when calling `query_tasks`.

New route: `GET /api/tasks?range=...&bucket=1h|1d`

### Hourly gap-filling

`padTimeline` extended: when `range === 'today'` or `range.startsWith('day:')`, fill 24 hourly buckets (midnight → midnight). Uses the same `date` field format (UTC ms at hour boundary) already produced by `_local_trunc(3_600_000, tz_offset_ms)`.

`padTasks` and `padQueries` extended similarly for hourly day views.

### Label formatting

`bucketLabel` already returns hourly labels for `today` range (`d.toLocaleTimeString`). Extend the same branch to cover `day:X` ranges.

---

## 4. Section Order

New HTML order (within `<body>`, after header):

1. Stats counters (`div.stats`)
2. `today-summary` (unchanged — day view only)
3. Daily tokens & cache hit chart (`canvas#token-chart`)
4. Recent sessions (`div#sessions-list`)
5. Tasks & queries chart (`canvas#task-chart`)
6. Queries + tokens chart (`canvas#query-chart`)
7. Model breakdown (`div#models-list`)
8. Weekly output budget (budget section)
9. Footer

The `renderQueryChart` and `renderTaskChart` swap order in `refresh()` to match (tasks rendered before queries).

---

## 5. Recent Sessions — Scrollable Cap

- API fetch: increase `limit` from `5` to `10` in `api.sessions(range)` call
- CSS: add `max-height` and `overflow-y: auto` to `#sessions-list` so only ~4 rows are visible without scrolling (approximately `4 × row-height ≈ 188px`)
- Scrollbar styled to match dark theme

---

## Files Changed

| File | Change |
|------|--------|
| `claudemon/db.py` | `query_tasks`: add bucket param + p50/max per-task; new `query_query_breakdown` (includes p50/max for queries chart) |
| `claudemon/server.py` | new `/api/queries` route; pass bucket to `query_tasks` |
| `claudemon/dashboard/app.js` | new `api.queries`; updated `renderQueryChart`, `renderTaskChart`; new `padQueries`; hourly gap-fill in `padTimeline`/`padTasks`; `setViewMode` shows charts in day view; `bucketLabel` handles `day:X` |
| `claudemon/dashboard/index.html` | section reorder; updated legends |
| `tests/` | new/updated tests for `query_timeline` p50/max, `query_tasks` bucket + p50/max, `query_query_breakdown` |

---

## Out of Scope

- No changes to `statusitem.py`, `watcher.py`, `indexer.py`, `app.py`, `popover.py`
- No new external dependencies
- No persistent DB changes (all in-memory)
