# Custom Time Range & 12H Tab — Design Spec

| Field | Value |
| --- | --- |
| **Date** | 2026-06-08 |
| **Status** | Approved |

## Overview

Two related changes to the dashboard time-range controls:

1. Rename the "Today" tab to **"12H"** (label only; internal range string stays `"today"`).
2. Add a **"Custom" tab** that opens a dropdown with datetime-range inputs (hour granularity). Applies a `custom:START_MS:END_MS` range; uses hourly buckets when the span ≤ 24 h, daily buckets otherwise.

---

## Range Format

Custom ranges are encoded as `custom:START_MS:END_MS` where both values are UTC milliseconds (integers). This string is passed to every `/api/*` endpoint as the `range` query parameter, matching the existing convention of `today`, `7d`, `day:1234567890`.

---

## Server Changes (`server.py`)

### `_range_to_timestamps`

Add one new case:

```python
case s if s.startswith("custom:"):
    _, start, end = s.split(":")
    return int(start), int(end)
```

No other server changes. Bucket selection (1h vs 1d) is driven by the JS layer, which passes the correct `bucket=` param to each API call.

---

## JS Changes (`app.js`)

### Bucket selection

Replace the current `isDayView(range)` ternary in `api.timeline`, `api.tasks`, and `api.queries` with a shared helper:

```js
function isHourBucket(range) {
  if (range === 'today' || range.startsWith('day:')) return true;
  if (range.startsWith('custom:')) {
    const [, start, end] = range.split(':');
    return (parseInt(end) - parseInt(start)) <= 24 * 3_600_000;
  }
  return false;
}
```

The three `api.*` helpers pass `bucket=${isHourBucket(range) ? '1h' : '1d'}`.

### `isDayView` → `isHourView`

Rename `isDayView` to `isHourView` and extend it to cover sub-24h custom ranges (same logic as `isHourBucket`). All existing call sites updated. The function governs:
- Whether `#today-summary` is shown
- Whether `bucketLabel` formats as hour vs. date
- Whether `dayViewBuckets` generates hourly or daily stamps

### `dayViewBuckets` → `viewBuckets`

Rename to `viewBuckets` and add a `custom:` branch:

```js
function viewBuckets(range) {
  if (range === 'today') { /* existing 12h rolling logic */ }
  if (range.startsWith('day:')) { /* existing 24-bucket logic */ }
  if (range.startsWith('custom:')) {
    const [, start, end] = range.split(':');
    const startMs = parseInt(start), endMs = parseInt(end);
    if (endMs - startMs <= 24 * 3_600_000) {
      // hourly buckets: local-hour-truncate start, step 1h until end
      const d = new Date(startMs); d.setMinutes(0, 0, 0);
      const first = d.getTime();
      const n = new Date(endMs); n.setMinutes(0, 0, 0);
      const last = n.getTime();
      const out = [];
      for (let ts = first; ts <= last; ts += 3_600_000) out.push(ts);
      return out;
    } else {
      // daily buckets: local-midnight-truncate start, step 1d until end
      const d = new Date(startMs); d.setHours(0, 0, 0, 0);
      const n = new Date(endMs); n.setHours(0, 0, 0, 0);
      const out = [];
      for (let ts = d.getTime(); ts <= n.getTime(); ts += 86_400_000) out.push(ts);
      return out;
    }
  }
}
```

### `bucketLabel`

Extend the date-label branch to handle custom multi-day ranges (same format as 30d/all: `Mon short day`).

### `padTimeline`, `padTasks`, `padQueries`

Add an explicit branch: `if (range.startsWith('custom:')) return viewBuckets(range).map(ts => map.get(ts) ?? emptyBucket(ts))`. This covers both the sub-24h hourly case and the multi-day daily case — `viewBuckets` handles the branching internally. The existing `isHourView` branch (for `today` and `day:X`) and the `7d`/`30d` fixed-count branches are unchanged.

### `onChartClick`

Guard `isHourView(range)` (replacing `isDayView`) for the drill-down prevention. For multi-day custom ranges, clicking a bar should still drill down to `day:TIMESTAMP` (same behaviour as 7d/30d).

---

## HTML Changes (`index.html`)

1. Change button text: `Today` → `12H` (keep `data-range="today"`).
2. Add a "Custom" button with no `data-range` attr and `id="custom-tab"`.
3. Add a hidden `<div id="custom-picker">` positioned below the tab bar containing:
   - `<input type="datetime-local" id="custom-start" step="3600">`
   - `<input type="datetime-local" id="custom-end" step="3600">`
   - `<button id="custom-apply">Apply</button>`

### Default values

When the picker opens, pre-fill start = 7 days ago at 00:00 local, end = now truncated to the current hour. This gives a sensible starting point without being an empty form.

### Tab label

When a custom range is active, the "Custom" button text updates to a short formatted range, e.g. `Jun 1 – Jun 7` (multi-day) or `Jun 7 2pm – 8pm` (same-day). The full `custom:S:E` range string is stored in `currentRange`; the label is derived from it at render time.

---

## CSS Changes (`style.css`)

- `#custom-picker`: absolutely positioned below the `.tabs` container; `z-index: 100`; dark background matching the dashboard palette; hidden by default (`display: none`).
- Active "Custom" tab uses same `.active` styling as other tabs.
- Datetime inputs styled to match existing dark theme (no native chrome border).

---

## Behaviour Details

| Scenario | Bucket | Today-summary shown |
|---|---|---|
| `today` (12H rolling) | 1h | Yes |
| `day:X` (drill-down) | 1h | Yes |
| `custom:S:E` span ≤ 24h | 1h | Yes |
| `custom:S:E` span > 24h | 1d | No |
| `7d`, `30d`, `all` | 1d | No |

- Clicking any preset tab closes the picker and clears the custom tab label back to "Custom".
- Apply with start ≥ end: show a brief inline validation message ("End must be after start"), do not refresh.
- Clicking outside the picker closes it without applying.

---

## Testing

- Unit test: `_range_to_timestamps("custom:1000:2000")` returns `(1000, 2000)`.
- Unit test: `isHourBucket` returns true for ≤24h custom, false for >24h.
- Existing tests unaffected (no changes to `today`, `7d`, `30d`, `all` paths).
