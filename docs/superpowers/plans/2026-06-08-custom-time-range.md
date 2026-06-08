# Custom Time Range Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Custom" date-range tab with hour-granularity datetime inputs, and rename the "Today" tab to "12H".

**Architecture:** Five tasks in order — server (TDD), JS helpers/renames, JS pad functions, HTML+CSS, JS wiring. Each task compiles and passes tests independently. JS functions use hoisting so helper order in the file doesn't matter at runtime.

**Tech Stack:** Python (server.py), vanilla JS (app.js), HTML, CSS, pytest

---

### Task 1: Server — `custom:` range support

**Files:**
- Modify: `claudemon/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py` (after the imports, outside any fixture):

```python
from claudemon.server import _range_to_timestamps

def test_range_custom_timestamps():
    start, end = _range_to_timestamps("custom:1000000:2000000")
    assert start == 1_000_000
    assert end == 2_000_000

def test_range_custom_via_endpoint(server):
    # custom range spanning the seeded data should return a result
    import time
    now = int(time.time() * 1000)
    data = _get(server + f"/api/stats?range=custom:0:{now}")
    assert data["sessions"] == 1
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_server.py::test_range_custom_timestamps tests/test_server.py::test_range_custom_via_endpoint -v
```

Expected: both FAIL (`_range_to_timestamps` has no `custom:` case; the endpoint returns 500).

- [ ] **Step 3: Implement the `custom:` case in `server.py`**

In `claudemon/server.py`, inside `_range_to_timestamps`, add this case before the `case _:` default (i.e. after the `day:` case):

```python
        case s if s.startswith("custom:"):
            parts = s.split(":")
            return int(parts[1]), int(parts[2])
```

The full `match` block should now read:

```python
    match range_str:
        case "today":
            return now - 12 * 3600 * 1000, now
        case "7d":
            return now - 7 * 24 * 3600 * 1000, now
        case "30d":
            return now - 30 * 24 * 3600 * 1000, now
        case s if s.startswith("day:"):
            day_start_ms = int(s.split(":", 1)[1])
            day_start_dt = datetime.fromtimestamp(day_start_ms / 1000).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_end_ms = int((day_start_dt + timedelta(days=1)).timestamp() * 1000) - 1
            return day_start_ms, day_end_ms
        case s if s.startswith("custom:"):
            parts = s.split(":")
            return int(parts[1]), int(parts[2])
        case _:
            return 0, now
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_server.py::test_range_custom_timestamps tests/test_server.py::test_range_custom_via_endpoint -v
```

Expected: both PASS.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```bash
.venv/bin/pytest tests/ -q
```

Expected: 46 passed.

- [ ] **Step 6: Commit**

```bash
git add claudemon/server.py tests/test_server.py
git commit -m "feat(server): support custom:START_MS:END_MS range"
```

---

### Task 2: JS — add `isHourBucket`, rename `isDayView` → `isHourView`, rename `dayViewBuckets` → `viewBuckets`

**Files:**
- Modify: `claudemon/dashboard/app.js`

No unit tests for JS — verify correctness in Task 5 via the running app.

- [ ] **Step 1: Replace the `isDayView` function with `isHourBucket` + `isHourView`**

Find and replace the existing `isDayView` function (currently around line 255):

Old:
```js
function isDayView(range) {
  return range === 'today' || range.startsWith('day:');
}
```

New (two functions in its place):
```js
function isHourBucket(range) {
  if (range === 'today' || range.startsWith('day:')) return true;
  if (range.startsWith('custom:')) {
    const parts = range.split(':');
    return (parseInt(parts[2]) - parseInt(parts[1])) <= 24 * 3_600_000;
  }
  return false;
}

function isHourView(range) {
  return range === 'today' || range.startsWith('day:') ||
    (range.startsWith('custom:') && isHourBucket(range));
}
```

- [ ] **Step 2: Replace `dayViewBuckets` with `viewBuckets`**

Find and replace the existing `dayViewBuckets` function:

Old:
```js
function dayViewBuckets(range) {
  if (range === 'today') {
    const d = new Date(Date.now() - 12 * 3_600_000);
    d.setMinutes(0, 0, 0);
    const first = d.getTime();
    const n = new Date(); n.setMinutes(0, 0, 0);
    const last = n.getTime();
    const out = [];
    for (let ts = first; ts <= last; ts += 3_600_000) out.push(ts);
    return out;
  }
  const dayStart = parseInt(range.split(':')[1]);
  return Array.from({ length: 24 }, (_, h) => dayStart + h * 3_600_000);
}
```

New:
```js
function viewBuckets(range) {
  if (range === 'today') {
    const d = new Date(Date.now() - 12 * 3_600_000);
    d.setMinutes(0, 0, 0);
    const first = d.getTime();
    const n = new Date(); n.setMinutes(0, 0, 0);
    const last = n.getTime();
    const out = [];
    for (let ts = first; ts <= last; ts += 3_600_000) out.push(ts);
    return out;
  }
  if (range.startsWith('day:')) {
    const dayStart = parseInt(range.split(':')[1]);
    return Array.from({ length: 24 }, (_, h) => dayStart + h * 3_600_000);
  }
  if (range.startsWith('custom:')) {
    const parts = range.split(':');
    const startMs = parseInt(parts[1]);
    const endMs = parseInt(parts[2]);
    if (endMs - startMs <= 24 * 3_600_000) {
      const d = new Date(startMs); d.setMinutes(0, 0, 0);
      const first = d.getTime();
      const n = new Date(endMs); n.setMinutes(0, 0, 0);
      const last = n.getTime();
      const out = [];
      for (let ts = first; ts <= last; ts += 3_600_000) out.push(ts);
      return out;
    } else {
      const d = new Date(startMs); d.setHours(0, 0, 0, 0);
      const n = new Date(endMs); n.setHours(0, 0, 0, 0);
      const out = [];
      for (let ts = d.getTime(); ts <= n.getTime(); ts += 86_400_000) out.push(ts);
      return out;
    }
  }
}
```

- [ ] **Step 3: Update `api.timeline`, `api.tasks`, `api.queries` to use `isHourBucket`**

Replace the three method definitions inside the `api` object:

Old:
```js
  timeline(range) { return api.get(`/api/timeline?range=${range}&bucket=${isDayView(range) ? '1h' : '1d'}`); }, // isDayView hoisted
  tasks(range)    { return api.get(`/api/tasks?range=${range}&bucket=${isDayView(range) ? '1h' : '1d'}`); },    // isDayView hoisted
  queries(range) {
    const bucket = isDayView(range) ? '1h' : '1d'; // isDayView is hoisted (function declaration below)
    return api.get(`/api/queries?range=${range}&bucket=${bucket}`);
  },
```

New:
```js
  timeline(range) { return api.get(`/api/timeline?range=${range}&bucket=${isHourBucket(range) ? '1h' : '1d'}`); },
  tasks(range)    { return api.get(`/api/tasks?range=${range}&bucket=${isHourBucket(range) ? '1h' : '1d'}`); },
  queries(range) {
    return api.get(`/api/queries?range=${range}&bucket=${isHourBucket(range) ? '1h' : '1d'}`);
  },
```

- [ ] **Step 4: Update `bucketLabel` to use `isHourView` and handle custom multi-day**

Replace the existing `bucketLabel` function:

Old:
```js
function bucketLabel(ts, range) {
  const d = new Date(ts);
  if (isDayView(range)) {
    return d.toLocaleTimeString(undefined, { hour: 'numeric' });
  }
  if (range === '30d' || range === 'all') {
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  return d.toLocaleDateString(undefined, { weekday: 'short' });
}
```

New:
```js
function bucketLabel(ts, range) {
  const d = new Date(ts);
  if (isHourView(range)) {
    return d.toLocaleTimeString(undefined, { hour: 'numeric' });
  }
  if (range === '30d' || range === 'all' || range.startsWith('custom:')) {
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  return d.toLocaleDateString(undefined, { weekday: 'short' });
}
```

- [ ] **Step 5: Update `setViewMode` to use `isHourView`**

Old:
```js
function setViewMode(range) {
  const day = isDayView(range);
  document.getElementById('today-summary').classList.toggle('hidden', !day);
}
```

New:
```js
function setViewMode(range) {
  document.getElementById('today-summary').classList.toggle('hidden', !isHourView(range));
}
```

- [ ] **Step 6: Update `onChartClick` to use `isHourView`**

Old:
```js
  if (currentRange === 'today' || currentRange.startsWith('day:')) return;
```

New:
```js
  if (isHourView(currentRange)) return;
```

- [ ] **Step 7: Update `refresh` to use `isHourView`**

Old:
```js
  if (isDayView(currentRange)) {
    renderTodaySummary(stats, currentRange);
  }
```

New:
```js
  if (isHourView(currentRange)) {
    renderTodaySummary(stats, currentRange);
  }
```

- [ ] **Step 8: Run the Python test suite to confirm no regressions**

```bash
.venv/bin/pytest tests/ -q
```

Expected: 46 passed. (JS changes are not covered by pytest — correctness verified at runtime in Task 5.)

- [ ] **Step 9: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "refactor(ui): rename isDayView→isHourView, dayViewBuckets→viewBuckets; add isHourBucket"
```

---

### Task 3: JS — extend pad functions for `custom:` ranges

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Replace `padTimeline`**

Old:
```js
function padTimeline(timeline, range) {
  if (isDayView(range)) {
    const map = new Map(timeline.map(b => [b.date, b]));
    return dayViewBuckets(range).map(ts => map.get(ts) ?? {
      date: ts, input_tokens: 0, output_tokens: 0,
      cache_hit_rate: 0, queries: 0, tokens_per_query: 0,
    });
  }
  const days = range === '30d' ? 30 : range === '7d' ? 7 : null;
  if (!days) return timeline;
  const map = new Map(timeline.map(b => [b.date, b]));
  const result = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    d.setHours(0, 0, 0, 0);
    const ts = d.getTime();
    result.push(map.get(ts) ?? {
      date: ts, input_tokens: 0, output_tokens: 0,
      cache_hit_rate: 0, queries: 0, tokens_per_query: 0,
    });
  }
  return result;
}
```

New:
```js
function padTimeline(timeline, range) {
  if (isHourView(range) || range.startsWith('custom:')) {
    const map = new Map(timeline.map(b => [b.date, b]));
    return viewBuckets(range).map(ts => map.get(ts) ?? {
      date: ts, input_tokens: 0, output_tokens: 0,
      cache_hit_rate: 0, queries: 0, tokens_per_query: 0,
    });
  }
  const days = range === '30d' ? 30 : range === '7d' ? 7 : null;
  if (!days) return timeline;
  const map = new Map(timeline.map(b => [b.date, b]));
  const result = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    d.setHours(0, 0, 0, 0);
    const ts = d.getTime();
    result.push(map.get(ts) ?? {
      date: ts, input_tokens: 0, output_tokens: 0,
      cache_hit_rate: 0, queries: 0, tokens_per_query: 0,
    });
  }
  return result;
}
```

- [ ] **Step 2: Replace `padTasks`**

Old:
```js
function padTasks(tasksData, range) {
  if (isDayView(range)) {
    const map = new Map(tasksData.map(d => [d.date, d]));
    return dayViewBuckets(range).map(ts => map.get(ts) ?? {
      date: ts, tasks: [],
      avg_tokens_per_task: 0, p50_tokens_per_task: 0, max_tokens_per_task: 0,
    });
  }
  const days = range === '30d' ? 30 : range === '7d' ? 7 : null;
  if (!days) return tasksData;
  const map = new Map(tasksData.map(d => [d.date, d]));
  const result = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    d.setHours(0, 0, 0, 0);
    const ts = d.getTime();
    result.push(map.get(ts) ?? {
      date: ts, tasks: [],
      avg_tokens_per_task: 0, p50_tokens_per_task: 0, max_tokens_per_task: 0,
    });
  }
  return result;
}
```

New:
```js
function padTasks(tasksData, range) {
  if (isHourView(range) || range.startsWith('custom:')) {
    const map = new Map(tasksData.map(d => [d.date, d]));
    return viewBuckets(range).map(ts => map.get(ts) ?? {
      date: ts, tasks: [],
      avg_tokens_per_task: 0, p50_tokens_per_task: 0, max_tokens_per_task: 0,
    });
  }
  const days = range === '30d' ? 30 : range === '7d' ? 7 : null;
  if (!days) return tasksData;
  const map = new Map(tasksData.map(d => [d.date, d]));
  const result = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    d.setHours(0, 0, 0, 0);
    const ts = d.getTime();
    result.push(map.get(ts) ?? {
      date: ts, tasks: [],
      avg_tokens_per_task: 0, p50_tokens_per_task: 0, max_tokens_per_task: 0,
    });
  }
  return result;
}
```

- [ ] **Step 3: Replace `padQueries`**

Old:
```js
function padQueries(queriesData, range) {
  if (isDayView(range)) {
    const map = new Map(queriesData.map(b => [b.date, b]));
    return dayViewBuckets(range).map(ts => map.get(ts) ?? {
      date: ts, queries: [], other_count: 0, other_tokens: 0, p50_tpq: 0, max_tpq: 0,
    });
  }
  const days = range === '30d' ? 30 : range === '7d' ? 7 : null;
  if (!days) return queriesData;
  const map = new Map(queriesData.map(b => [b.date, b]));
  const result = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    d.setHours(0, 0, 0, 0);
    const ts = d.getTime();
    result.push(map.get(ts) ?? {
      date: ts, queries: [], other_count: 0, other_tokens: 0, p50_tpq: 0, max_tpq: 0,
    });
  }
  return result;
}
```

New:
```js
function padQueries(queriesData, range) {
  if (isHourView(range) || range.startsWith('custom:')) {
    const map = new Map(queriesData.map(b => [b.date, b]));
    return viewBuckets(range).map(ts => map.get(ts) ?? {
      date: ts, queries: [], other_count: 0, other_tokens: 0, p50_tpq: 0, max_tpq: 0,
    });
  }
  const days = range === '30d' ? 30 : range === '7d' ? 7 : null;
  if (!days) return queriesData;
  const map = new Map(queriesData.map(b => [b.date, b]));
  const result = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    d.setHours(0, 0, 0, 0);
    const ts = d.getTime();
    result.push(map.get(ts) ?? {
      date: ts, queries: [], other_count: 0, other_tokens: 0, p50_tpq: 0, max_tpq: 0,
    });
  }
  return result;
}
```

- [ ] **Step 4: Run the Python suite to confirm no regressions**

```bash
.venv/bin/pytest tests/ -q
```

Expected: 46 passed.

- [ ] **Step 5: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat(ui): extend pad functions to handle custom: ranges"
```

---

### Task 4: HTML + CSS — rename tab, add Custom button and picker

**Files:**
- Modify: `claudemon/dashboard/index.html`
- Modify: `claudemon/dashboard/style.css`

- [ ] **Step 1: Rename "Today" tab and add Custom button in `index.html`**

Old tabs block:
```html
    <button class="tab" data-range="today">Today</button>
    <button class="tab active" data-range="7d">7d</button>
    <button class="tab" data-range="30d">30d</button>
    <button class="tab" data-range="all">All</button>
```

New tabs block:
```html
    <button class="tab" data-range="today">12H</button>
    <button class="tab active" data-range="7d">7d</button>
    <button class="tab" data-range="30d">30d</button>
    <button class="tab" data-range="all">All</button>
    <button class="tab" id="custom-tab">Custom</button>
```

- [ ] **Step 2: Add the picker div after the `</div>` that closes `.header`**

Insert after `</div><!-- .header -->`:

```html
<div id="custom-picker">
  <div class="picker-row">
    <div class="picker-field">
      <label for="custom-start">From</label>
      <input type="datetime-local" id="custom-start" step="3600">
    </div>
    <div class="picker-field">
      <label for="custom-end">To</label>
      <input type="datetime-local" id="custom-end" step="3600">
    </div>
    <button id="custom-apply">Apply</button>
  </div>
  <div id="custom-error" class="picker-error"></div>
</div>
```

The full updated `<div class="header">` block through the picker:

```html
<div class="header">
  <h1>claudemon</h1>
  <div class="tabs">
    <button class="tab" data-range="today">12H</button>
    <button class="tab active" data-range="7d">7d</button>
    <button class="tab" data-range="30d">30d</button>
    <button class="tab" data-range="all">All</button>
    <button class="tab" id="custom-tab">Custom</button>
  </div>
</div>
<div id="custom-picker">
  <div class="picker-row">
    <div class="picker-field">
      <label for="custom-start">From</label>
      <input type="datetime-local" id="custom-start" step="3600">
    </div>
    <div class="picker-field">
      <label for="custom-end">To</label>
      <input type="datetime-local" id="custom-end" step="3600">
    </div>
    <button id="custom-apply">Apply</button>
  </div>
  <div id="custom-error" class="picker-error"></div>
</div>
```

- [ ] **Step 3: Add picker styles to `style.css`**

Append to the end of `claudemon/dashboard/style.css`:

```css
#custom-picker {
  display: none;
  background: #1c1c28;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  padding: 10px 16px;
}
.picker-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.picker-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.picker-field label {
  font-size: 10px;
  color: #666;
  text-transform: uppercase;
  letter-spacing: .06em;
}
.picker-field input[type="datetime-local"] {
  background: #0e0e1a;
  border: 1px solid #3a3a5a;
  border-radius: 4px;
  color: #ccc;
  font-size: 11px;
  padding: 4px 6px;
  outline: none;
}
.picker-field input[type="datetime-local"]:focus {
  border-color: #6d28d9;
}
#custom-apply {
  padding: 5px 12px;
  background: #6d28d9;
  border: none;
  border-radius: 4px;
  color: #fff;
  font-size: 11px;
  cursor: pointer;
}
#custom-apply:hover { background: #7c3aed; }
.picker-error {
  font-size: 10px;
  color: #f87171;
  margin-top: 5px;
  min-height: 14px;
}
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/ -q
```

Expected: 46 passed.

- [ ] **Step 5: Commit**

```bash
git add claudemon/dashboard/index.html claudemon/dashboard/style.css
git commit -m "feat(ui): rename Today→12H tab, add Custom tab and datetime picker"
```

---

### Task 5: JS — wire up Custom tab interactions

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Add `toDatetimeLocal` helper function**

Add after the `fmtDuration` function (before the `api` object):

```js
function toDatetimeLocal(d) {
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
}
```

- [ ] **Step 2: Add `updateCustomTabLabel` helper function**

Add after `toDatetimeLocal`:

```js
function updateCustomTabLabel() {
  const btn = document.getElementById('custom-tab');
  if (!currentRange.startsWith('custom:')) {
    btn.textContent = 'Custom';
    return;
  }
  const parts = currentRange.split(':');
  const startMs = parseInt(parts[1]);
  const endMs = parseInt(parts[2]);
  const start = new Date(startMs);
  const end = new Date(endMs);
  if (endMs - startMs <= 24 * 3_600_000) {
    const date = start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const s = start.toLocaleTimeString(undefined, { hour: 'numeric' });
    const e = end.toLocaleTimeString(undefined, { hour: 'numeric' });
    btn.textContent = `${date} ${s}–${e}`;
  } else {
    const s = start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const e = end.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    btn.textContent = `${s}–${e}`;
  }
}
```

- [ ] **Step 3: Wire up the Custom tab and picker inside `DOMContentLoaded`**

Inside the `document.addEventListener('DOMContentLoaded', () => { ... })` block, after `initCharts(); refresh(); refreshBanner();` and after the `setInterval` calls, add these event listeners (before the closing `});`):

```js
  const customTab = document.getElementById('custom-tab');
  const customPicker = document.getElementById('custom-picker');
  const customStart = document.getElementById('custom-start');
  const customEnd = document.getElementById('custom-end');

  customTab.addEventListener('click', () => {
    if (customPicker.style.display !== 'none') {
      customPicker.style.display = 'none';
      return;
    }
    const now = new Date();
    now.setMinutes(0, 0, 0);
    const sevenAgo = new Date(now.getTime() - 7 * 86_400_000);
    sevenAgo.setHours(0, 0, 0, 0);
    customStart.value = toDatetimeLocal(sevenAgo);
    customEnd.value = toDatetimeLocal(now);
    document.getElementById('custom-error').textContent = '';
    customPicker.style.display = '';
  });

  document.getElementById('custom-apply').addEventListener('click', () => {
    const start = new Date(customStart.value).getTime();
    const end = new Date(customEnd.value).getTime();
    if (isNaN(start) || isNaN(end) || end <= start) {
      document.getElementById('custom-error').textContent = 'End must be after start';
      return;
    }
    document.getElementById('custom-error').textContent = '';
    currentRange = `custom:${start}:${end}`;
    customPicker.style.display = 'none';
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    customTab.classList.add('active');
    updateCustomTabLabel();
    refresh();
  });

  document.addEventListener('click', e => {
    if (customPicker.style.display === 'none') return;
    if (!customPicker.contains(e.target) && e.target !== customTab) {
      customPicker.style.display = 'none';
    }
  });
```

- [ ] **Step 4: Update the preset tab click handler to close the picker and reset the label**

Old:
```js
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      currentRange = tab.dataset.range;
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      refresh();
    });
  });
```

New:
```js
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      if (!tab.dataset.range) return;
      currentRange = tab.dataset.range;
      customPicker.style.display = 'none';
      document.getElementById('custom-tab').textContent = 'Custom';
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      refresh();
    });
  });
```

- [ ] **Step 5: Run the Python suite one final time**

```bash
.venv/bin/pytest tests/ -q
```

Expected: 46 passed.

- [ ] **Step 6: Lint**

```bash
just lint
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat(ui): wire up Custom tab — datetime picker, apply, close, label"
```
