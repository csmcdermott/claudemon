# Dashboard Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add p50/max percentile lines to tasks and queries charts, replace the queries bar chart with a stacked per-query token chart, show hourly charts in day views alongside the stat-counter summary, reorder dashboard sections, and make the sessions list scrollable.

**Architecture:** Backend adds `bucket` parameter to `query_tasks` and a new `query_query_breakdown` function in db.py; server.py adds `/api/queries` route. Frontend replaces `renderQueryChart` with a stacked implementation driven by the new endpoint, adds p50/max lines to both charts, and enables hourly chart rendering in day views by removing the chart-hiding logic from `setViewMode`.

**Tech Stack:** Python stdlib sqlite3, rumps/PyObjC (unchanged), Chart.js 4.4, vanilla JS, pytest + `.venv/bin/pytest`

---

## File Map

| File | What changes |
|------|-------------|
| `claudemon/db.py` (lines 241–297) | `query_tasks`: add `bucket` param, compute p50/max per bucket |
| `claudemon/db.py` (append) | new `query_query_breakdown` function |
| `claudemon/server.py` (lines 92–116) | add `/api/queries` route; pass `bucket` param to `query_tasks` |
| `claudemon/dashboard/index.html` | reorder sections; update legends |
| `claudemon/dashboard/style.css` | add scrollable cap to `#sessions-list` |
| `claudemon/dashboard/app.js` | renderTaskChart, renderQueryChart, padQueries, setViewMode, padding, bucketLabel, api, refresh |
| `tests/test_db.py` | tests for query_tasks p50/max + hourly, query_query_breakdown |
| `tests/test_server.py` | tests for /api/queries, /api/tasks bucket param |

---

## Task 1: DB — `query_tasks` bucket param + p50/max

**Files:**
- Modify: `claudemon/db.py:241-297`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_db.py`:

```python
def test_query_tasks_p50_max(conn):
    db.upsert_session(conn, "s1", "proj", "T", 1000, 9000, "main")
    # 3 tasks: tokens 100, 200, 300
    db.insert_message(conn, "s1", "s1:1", "s1:1:1", 1000, "claude-sonnet-4-6", 40, 60, 0, 0)
    db.insert_message(conn, "s1", "s1:2", "s1:2:1", 2000, "claude-sonnet-4-6", 80, 120, 0, 0)
    db.insert_message(conn, "s1", "s1:3", "s1:3:1", 3000, "claude-sonnet-4-6", 120, 180, 0, 0)
    result = db.query_tasks(conn, (0, int(time.time() * 1000)))
    assert len(result) == 1
    b = result[0]
    assert b["p50_tokens_per_task"] == 200  # sorted[1] of [100, 200, 300]
    assert b["max_tokens_per_task"] == 300
    assert b["avg_tokens_per_task"] == 200


def test_query_tasks_hourly_bucket(conn):
    db.upsert_session(conn, "s1", "proj", None, 0, 99_000_000_000, "main")
    hour1 = 1749340800000
    hour2 = hour1 + 3_600_000
    db.insert_message(conn, "s1", "s1:1", "s1:1:1", hour1 + 100, "claude-sonnet-4-6", 10, 20, 0, 0)
    db.insert_message(conn, "s1", "s1:2", "s1:2:1", hour2 + 100, "claude-sonnet-4-6", 30, 40, 0, 0)
    result = db.query_tasks(conn, (hour1, hour2 + 3_600_000), bucket="1h")
    assert len(result) == 2
    for b in result:
        assert "p50_tokens_per_task" in b
        assert "max_tokens_per_task" in b
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
just test tests/test_db.py::test_query_tasks_p50_max tests/test_db.py::test_query_tasks_hourly_bucket
```

Expected: `AttributeError` or `TypeError` (bucket param not accepted, p50/max fields missing).

- [ ] **Step 3: Replace `query_tasks` in `claudemon/db.py`**

Replace the entire function at lines 241–297 with:

```python
def query_tasks(
    conn: sqlite3.Connection,
    range_ts: tuple[int, int],
    bucket: str = "1d",
    tz_offset_ms: int = 0,
) -> list[dict]:
    """Return per-bucket task breakdown for stacked chart.

    bucket: '1h' or '1d'
    """
    start_ms, end_ms = range_ts
    bucket_ms = 3_600_000 if bucket == "1h" else 86_400_000
    trunc = _local_trunc(bucket_ms, tz_offset_ms)
    rows = conn.execute(f"""
        SELECT
            {trunc}                                        AS bucket_ts,
            m.task_id,
            m.session_id,
            s.title                                        AS session_title,
            s.project                                      AS project,
            COUNT(DISTINCT m.query_id)                     AS queries,
            COALESCE(SUM(m.input_tokens), 0)               AS input_tokens,
            COALESCE(SUM(m.output_tokens), 0)              AS output_tokens
        FROM messages m
        LEFT JOIN sessions s ON s.session_id = m.session_id
        WHERE m.timestamp BETWEEN ? AND ?
        GROUP BY bucket_ts, m.task_id
        ORDER BY bucket_ts, m.task_id
    """, (start_ms, end_ms)).fetchall()

    buckets: dict[int, dict] = {}
    for r in rows:
        ts = r["bucket_ts"]
        if ts not in buckets:
            buckets[ts] = {"date": ts, "tasks": [], "total_tokens": 0}
        tok = r["input_tokens"] + r["output_tokens"]
        try:
            task_num = int(r["task_id"].split(":")[-1])
        except (ValueError, IndexError):
            task_num = 1
        title = r["session_title"] or r["project"] or r["task_id"]
        label = title if task_num == 1 else f"{title} #{task_num}"
        buckets[ts]["tasks"].append({
            "task_id": r["task_id"],
            "label": label,
            "queries": r["queries"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
        })
        buckets[ts]["total_tokens"] += tok

    result = []
    for ts in sorted(buckets):
        d = buckets[ts]
        task_tokens = sorted(
            t["input_tokens"] + t["output_tokens"] for t in d["tasks"]
        )
        n = len(task_tokens)
        result.append({
            "date": ts,
            "tasks": d["tasks"],
            "avg_tokens_per_task": round(d["total_tokens"] / max(n, 1)),
            "p50_tokens_per_task": task_tokens[(n - 1) // 2] if n > 0 else 0,
            "max_tokens_per_task": task_tokens[-1] if n > 0 else 0,
        })
    return result
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
just test tests/test_db.py::test_query_tasks_p50_max tests/test_db.py::test_query_tasks_hourly_bucket
```

Expected: both PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
just test
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add claudemon/db.py tests/test_db.py
git commit -m "feat(db): add bucket param and p50/max to query_tasks"
```

---

## Task 2: DB — `query_query_breakdown`

**Files:**
- Modify: `claudemon/db.py` (append after `query_tasks`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_db.py`:

```python
def test_query_query_breakdown_top_n(conn):
    db.upsert_session(conn, "s1", "proj", None, 0, 99_000_000_000, "main")
    ts_base = 1749340800000
    # 12 queries with output tokens 10, 20, ..., 120
    for i in range(12):
        db.insert_message(
            conn, "s1", "s1:1", f"s1:1:{i + 1}",
            ts_base + i * 1000, "claude-sonnet-4-6", 0, (i + 1) * 10, 0, 0,
        )
    result = db.query_query_breakdown(conn, (ts_base, ts_base + 20_000))
    assert len(result) == 1
    b = result[0]
    assert len(b["queries"]) == 10
    assert b["other_count"] == 2
    assert b["other_tokens"] == 30          # 10 + 20
    assert b["queries"][0]["total_tokens"] == 120  # sorted descending
    # sorted all: [10,20,...,120], n=12, p50 idx=(12-1)//2=5, value=60
    assert b["p50_tpq"] == 60
    assert b["max_tpq"] == 120


def test_query_query_breakdown_fewer_than_top_n(conn):
    db.upsert_session(conn, "s1", "proj", None, 0, 99_000_000_000, "main")
    ts_base = 1749340800000
    for i, toks in enumerate([100, 200, 300]):
        db.insert_message(
            conn, "s1", "s1:1", f"s1:1:{i + 1}",
            ts_base + i * 1000, "claude-sonnet-4-6", 0, toks, 0, 0,
        )
    result = db.query_query_breakdown(conn, (ts_base, ts_base + 10_000))
    assert len(result) == 1
    b = result[0]
    assert len(b["queries"]) == 3
    assert b["other_count"] == 0
    assert b["other_tokens"] == 0
    # sorted: [100,200,300], p50 idx=1, value=200
    assert b["p50_tpq"] == 200
    assert b["max_tpq"] == 300


def test_query_query_breakdown_hourly_bucket(conn):
    db.upsert_session(conn, "s1", "proj", None, 0, 99_000_000_000, "main")
    hour1 = 1749340800000
    hour2 = hour1 + 3_600_000
    db.insert_message(conn, "s1", "s1:1", "s1:1:1", hour1 + 100, "claude-sonnet-4-6", 0, 50, 0, 0)
    db.insert_message(conn, "s1", "s1:1", "s1:1:2", hour2 + 100, "claude-sonnet-4-6", 0, 80, 0, 0)
    result = db.query_query_breakdown(conn, (hour1, hour2 + 3_600_000), bucket="1h")
    assert len(result) == 2
    dates = {b["date"] for b in result}
    assert len(dates) == 2
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
just test tests/test_db.py::test_query_query_breakdown_top_n tests/test_db.py::test_query_query_breakdown_fewer_than_top_n tests/test_db.py::test_query_query_breakdown_hourly_bucket
```

Expected: `AttributeError: module 'claudemon.db' has no attribute 'query_query_breakdown'`.

- [ ] **Step 3: Add `query_query_breakdown` to `claudemon/db.py`**

Append after `query_tasks` (before `query_sessions`):

```python
def query_query_breakdown(
    conn: sqlite3.Connection,
    range_ts: tuple[int, int],
    bucket: str = "1d",
    tz_offset_ms: int = 0,
    top_n: int = 10,
) -> list[dict]:
    """Return per-bucket top-N query token breakdown for stacked chart.

    Each bucket dict: {date, queries[{query_id, total_tokens}], other_count,
                       other_tokens, p50_tpq, max_tpq}
    Queries sorted descending by total_tokens; excess collapsed into other_*.
    p50/max computed over all queries in the bucket, not just top_n.
    """
    start_ms, end_ms = range_ts
    bucket_ms = 3_600_000 if bucket == "1h" else 86_400_000
    trunc = _local_trunc(bucket_ms, tz_offset_ms)

    rows = conn.execute(f"""
        SELECT
            {trunc}                               AS bucket_ts,
            query_id,
            SUM(input_tokens + output_tokens)     AS total_tokens
        FROM messages
        WHERE timestamp BETWEEN ? AND ?
        GROUP BY bucket_ts, query_id
        ORDER BY bucket_ts, total_tokens DESC
    """, (start_ms, end_ms)).fetchall()

    raw: dict[int, list] = {}
    for r in rows:
        ts = r["bucket_ts"]
        if ts not in raw:
            raw[ts] = []
        raw[ts].append({"query_id": r["query_id"], "total_tokens": r["total_tokens"]})

    result = []
    for ts in sorted(raw):
        all_q = raw[ts]
        all_tok = [q["total_tokens"] for q in all_q]
        n = len(all_tok)
        sorted_tok = sorted(all_tok)
        p50 = sorted_tok[(n - 1) // 2] if n > 0 else 0
        max_tpq = sorted_tok[-1] if n > 0 else 0

        top = all_q[:top_n]
        rest = all_q[top_n:]
        result.append({
            "date": ts,
            "queries": top,
            "other_count": len(rest),
            "other_tokens": sum(q["total_tokens"] for q in rest),
            "p50_tpq": p50,
            "max_tpq": max_tpq,
        })
    return result
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
just test tests/test_db.py::test_query_query_breakdown_top_n tests/test_db.py::test_query_query_breakdown_fewer_than_top_n tests/test_db.py::test_query_query_breakdown_hourly_bucket
```

Expected: all 3 PASS.

- [ ] **Step 5: Run full test suite**

```bash
just test
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add claudemon/db.py tests/test_db.py
git commit -m "feat(db): add query_query_breakdown for stacked queries chart"
```

---

## Task 3: Server — `/api/queries` route + pass `bucket` param

**Files:**
- Modify: `claudemon/server.py:92-116`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
def test_queries_endpoint(server):
    data = _get(server + "/api/queries?range=all&bucket=1d")
    assert isinstance(data, list)
    assert len(data) >= 1
    b = data[0]
    assert "queries" in b
    assert isinstance(b["queries"], list)
    assert "other_count" in b
    assert "other_tokens" in b
    assert "p50_tpq" in b
    assert "max_tpq" in b
    # seeded_conn has 3 queries total, all fit within top_n=10
    total_q = sum(len(bucket["queries"]) for bucket in data)
    assert total_q == 3


def test_tasks_endpoint_has_p50_max(server):
    data = _get(server + "/api/tasks?range=all&bucket=1d")
    assert isinstance(data, list)
    assert len(data) >= 1
    for b in data:
        assert "p50_tokens_per_task" in b
        assert "max_tokens_per_task" in b
        assert b["max_tokens_per_task"] >= b["p50_tokens_per_task"]


def test_queries_endpoint_default_bucket(server):
    """bucket param is optional — omitting it must not 500."""
    data = _get(server + "/api/queries?range=all")
    assert isinstance(data, list)
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
just test tests/test_server.py::test_queries_endpoint tests/test_server.py::test_tasks_endpoint_has_p50_max tests/test_server.py::test_queries_endpoint_default_bucket
```

Expected: `HTTPError: HTTP Error 404` for the queries tests; the p50/max test fails with `AssertionError`.

- [ ] **Step 3: Update server.py route block**

In `claudemon/server.py`, replace the `elif parsed.path == "/api/tasks":` block and add the new `/api/queries` route. The full updated `try` block (lines 92–116) becomes:

```python
            try:
                if parsed.path == "/api/stats":
                    self._json(db.query_stats(conn, range_ts))

                elif parsed.path == "/api/timeline":
                    bucket = qs.get("bucket", ["1d"])[0]
                    self._json(db.query_timeline(conn, range_ts, bucket, _tz_offset_ms()))

                elif parsed.path == "/api/tasks":
                    bucket = qs.get("bucket", ["1d"])[0]
                    self._json(db.query_tasks(conn, range_ts, bucket=bucket, tz_offset_ms=_tz_offset_ms()))

                elif parsed.path == "/api/queries":
                    bucket = qs.get("bucket", ["1d"])[0]
                    self._json(db.query_query_breakdown(conn, range_ts, bucket, _tz_offset_ms()))

                elif parsed.path == "/api/sessions":
                    limit = int(qs.get("limit", ["5"])[0])
                    active_only = qs.get("active", ["false"])[0].lower() == "true"
                    result = db.query_sessions(conn, range_ts, limit=limit, active_only=active_only)
                    self._json(result)

                elif parsed.path == "/api/config":
                    if config_path.exists():
                        self._json(json.loads(config_path.read_text()))
                    else:
                        self._json({})

                else:
                    self._json_error(404, "not found")

            except Exception as exc:
                self._json_error(500, str(exc))
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
just test tests/test_server.py::test_queries_endpoint tests/test_server.py::test_tasks_endpoint_has_p50_max tests/test_server.py::test_queries_endpoint_default_bucket
```

Expected: all 3 PASS.

- [ ] **Step 5: Run full test suite**

```bash
just test
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add claudemon/server.py tests/test_server.py
git commit -m "feat(server): add /api/queries route; pass bucket param to query_tasks"
```

---

## Task 4: HTML/CSS — section reorder, updated legends, sessions scroll

**Files:**
- Modify: `claudemon/dashboard/index.html`
- Modify: `claudemon/dashboard/style.css`

No automated tests — visual changes verified by running the app.

- [ ] **Step 1: Replace `claudemon/dashboard/index.html` body content**

Replace everything between `<body>` and `<script src="app.js"></script>` with the following. Key changes: sections reordered; task chart appears before query chart; recent sessions moved up; legends updated to show p50/max lines; query chart section re-titled.

```html
<div id="banner" class="banner hidden">
  <div class="pulse"></div>
  <span>Working in <strong id="banner-project"></strong></span>
  <span class="banner-meta" id="banner-meta"></span>
</div>

<div class="header">
  <h1>claudemon</h1>
  <div class="tabs">
    <button class="tab" data-range="today">Today</button>
    <button class="tab active" data-range="7d">7d</button>
    <button class="tab" data-range="30d">30d</button>
    <button class="tab" data-range="all">All</button>
  </div>
</div>

<div class="stats">
  <div class="stat">
    <div class="stat-val" id="stat-sessions">—</div>
    <div class="stat-lbl">Sessions</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="stat-input">—</div>
    <div class="stat-lbl">Input tok</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="stat-output">—</div>
    <div class="stat-lbl">Output tok</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="stat-cache">—</div>
    <div class="stat-lbl">Cache hit</div>
  </div>
</div>

<section id="today-summary" class="hidden">
  <div id="today-date-label" class="today-date hidden"></div>
  <div class="today-grid">
    <div class="today-metric">
      <div class="today-val" id="today-tasks">—</div>
      <div class="today-lbl">Tasks</div>
    </div>
    <div class="today-metric">
      <div class="today-val" id="today-queries">—</div>
      <div class="today-lbl">Queries</div>
    </div>
    <div class="today-metric">
      <div class="today-val" id="today-tpq">—</div>
      <div class="today-lbl">Tok / query</div>
    </div>
    <div class="today-metric">
      <div class="today-val" id="today-tpt">—</div>
      <div class="today-lbl">Tok / task</div>
    </div>
  </div>
</section>

<section class="chart-section">
  <div class="sec-hdr">
    <div class="sec-title">Daily tokens + cache hit %</div>
    <div class="legend">
      <div class="leg"><div class="leg-dot" style="background:#a78bfa"></div>out</div>
      <div class="leg"><div class="leg-dot" style="background:#38bdf8"></div>in</div>
      <div class="leg"><div class="leg-line" style="background:#34d399"></div>cache %</div>
    </div>
  </div>
  <div class="axis-labels"><div class="axis-lbl">← tokens</div><div class="axis-lbl">cache % →</div></div>
  <div class="chart-wrap"><canvas id="token-chart"></canvas></div>
</section>

<section>
  <div class="sec-title" style="margin-bottom:4px">Recent sessions</div>
  <div id="sessions-list"></div>
</section>

<section class="chart-section">
  <div class="sec-hdr">
    <div class="sec-title">Tasks &amp; queries</div>
    <div class="legend">
      <div class="leg">
        <div style="display:flex;gap:2px">
          <div class="leg-dot" style="background:rgba(167,139,250,0.8)"></div>
          <div class="leg-dot" style="background:rgba(56,189,248,0.8)"></div>
          <div class="leg-dot" style="background:rgba(52,211,153,0.8)"></div>
        </div>
        tasks
      </div>
      <div class="leg"><div class="leg-line leg-dashed" style="border-color:#fcd34d"></div>p50 tok</div>
      <div class="leg"><div class="leg-line" style="background:#f87171"></div>top tok</div>
    </div>
  </div>
  <div class="axis-labels"><div class="axis-lbl">← queries</div><div class="axis-lbl">tok/task →</div></div>
  <div class="chart-wrap tall"><canvas id="task-chart"></canvas></div>
</section>

<section class="chart-section">
  <div class="sec-hdr">
    <div class="sec-title">Queries by token volume</div>
    <div class="legend">
      <div class="leg">
        <div style="display:flex;gap:2px">
          <div class="leg-dot" style="background:rgba(167,139,250,0.8)"></div>
          <div class="leg-dot" style="background:rgba(56,189,248,0.8)"></div>
          <div class="leg-dot" style="background:rgba(52,211,153,0.8)"></div>
        </div>
        queries
      </div>
      <div class="leg"><div class="leg-line leg-dashed" style="border-color:#fcd34d"></div>p50 tok</div>
      <div class="leg"><div class="leg-line" style="background:#f87171"></div>top tok</div>
    </div>
  </div>
  <div class="axis-labels"><div class="axis-lbl">← tokens</div><div class="axis-lbl">tok/query →</div></div>
  <div class="chart-wrap tall"><canvas id="query-chart"></canvas></div>
</section>

<section>
  <div class="sec-title" style="margin-bottom:6px">Model breakdown</div>
  <div id="models-list"></div>
</section>

<section>
  <div class="budget-row">
    <div class="budget-lbl">Weekly output budget</div>
    <div class="budget-val" id="budget-val">—</div>
  </div>
  <div class="budget-track"><div class="budget-fill" id="budget-fill" style="width:0%"></div></div>
  <div class="budget-sub">Personal soft limit · edit in settings</div>
</section>
```

- [ ] **Step 2: Add CSS for dashed legend line and sessions scroll in `style.css`**

Append to `claudemon/dashboard/style.css`:

```css
/* Dashed legend line indicator (p50) */
.leg-line.leg-dashed {
  background: none;
  border-bottom: 2px dashed;
  height: 0;
  width: 12px;
}

/* Sessions list: show ~4 rows, scroll to reveal more */
#sessions-list {
  max-height: 188px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.12) transparent;
}
#sessions-list::-webkit-scrollbar { width: 4px; }
#sessions-list::-webkit-scrollbar-track { background: transparent; }
#sessions-list::-webkit-scrollbar-thumb {
  background: rgba(255,255,255,0.12);
  border-radius: 2px;
}
```

- [ ] **Step 3: Commit**

```bash
git add claudemon/dashboard/index.html claudemon/dashboard/style.css
git commit -m "feat(ui): reorder sections; update legends; scrollable sessions list"
```

---

## Task 5: JS — `renderTaskChart` p50/max lines

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Update `initCharts` — tasks chart right-axis tick color**

In `initCharts`, the `taskChart` right axis currently uses `'#fcd34d'` as tick color. Change it to `'#888'` to be neutral between the two line colors:

```javascript
  taskChart = new Chart(document.getElementById('task-chart'), {
    data: { labels: [], datasets: [] },
    options: {
      ...CHART_DEFAULTS, ...clickOpts,
      plugins: { ...CHART_DEFAULTS.plugins, tooltip: {
        ...CHART_DEFAULTS.plugins.tooltip,
        filter: item => item.raw !== null && item.raw !== 0,
        callbacks: {
          title: items => items[0].label,
          label: item => {
            if (item.dataset.label === 'p50 tok') return ` p50: ${fmt(item.raw)}`;
            if (item.dataset.label === 'top tok') return ` max: ${fmt(item.raw)}`;
            return ` ${item.dataset.label}: ${item.raw} quer${item.raw === 1 ? 'y' : 'ies'}`;
          },
        },
      }},
      scales: {
        x: SCALE_X,
        yLeft: { ...SCALE_LEFT, stacked: true, yAxisID: 'yLeft' },
        yRight: { ...SCALE_RIGHT('#888', v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v), yAxisID: 'yRight' },
      },
    },
  });
```

- [ ] **Step 2: Replace `renderTaskChart`**

Replace the entire `renderTaskChart` function:

```javascript
function renderTaskChart(tasksData, range) {
  const padded = padTasks(tasksData, range);
  _paddedTasks = padded;
  if (!padded.length) return;
  const labels = padded.map(d => bucketLabel(d.date, range));
  const maxTasks = Math.max(...padded.map(d => d.tasks.length), 0);

  const stackDatasets = Array.from({ length: maxTasks }, (_, i) => ({
    type: 'bar',
    label: `Task ${i + 1}`,
    data: padded.map(d => d.tasks[i]?.queries ?? null),
    backgroundColor: PALETTE[i % PALETTE.length],
    borderColor: 'rgba(0,0,0,0.12)', borderWidth: 0.5,
    borderRadius: i === 0 ? { bottomLeft: 3, bottomRight: 3 } : 0,
    borderSkipped: false, stack: 'tasks', yAxisID: 'yLeft', order: 2,
  }));

  taskChart.options.plugins.tooltip.callbacks = {
    title: items => items[0].label,
    label: item => {
      if (item.dataset.label === 'p50 tok') return ` p50: ${fmt(item.raw)}`;
      if (item.dataset.label === 'top tok') return ` max: ${fmt(item.raw)}`;
      const task = padded[item.dataIndex]?.tasks[item.datasetIndex];
      const name = task?.label || item.dataset.label;
      const q = item.raw;
      return ` ${name}: ${q} quer${q === 1 ? 'y' : 'ies'}`;
    },
  };

  const activeBuckets = padded.filter(d => d.tasks.length > 0).length;
  taskChart.data.labels = labels;
  taskChart.data.datasets = [
    ...stackDatasets,
    ...(activeBuckets >= 2 ? [
      {
        type: 'line', label: 'p50 tok',
        data: padded.map(d => d.tasks.length ? d.p50_tokens_per_task : null),
        borderColor: '#fcd34d', borderWidth: 1.5, borderDash: [4, 2],
        pointRadius: 2, pointBackgroundColor: '#fcd34d',
        spanGaps: false, tension: 0.4, yAxisID: 'yRight', order: 1,
      },
      {
        type: 'line', label: 'top tok',
        data: padded.map(d => d.tasks.length ? d.max_tokens_per_task : null),
        borderColor: '#f87171', borderWidth: 1.5,
        pointRadius: 2, pointBackgroundColor: '#f87171',
        spanGaps: false, tension: 0.4, yAxisID: 'yRight', order: 1,
      },
    ] : []),
  ];
  taskChart.update();
}
```

- [ ] **Step 3: Manual verification**

Run `just build` or open the dashboard directly. Switch to the 7d view, confirm the tasks chart now shows a yellow dashed line (p50) and a red-orange solid line (max) instead of a single yellow average line. Single-data-point views should show no lines (activeBuckets < 2 guard).

- [ ] **Step 4: Run lint**

```bash
just lint
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat(ui): replace avg tok/task line with p50 + max lines on tasks chart"
```

---

## Task 6: JS — stacked queries chart

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Add `_paddedQueries` module-level variable**

After the existing `let _paddedTasks = [];` line, add:

```javascript
let _paddedQueries = [];
```

- [ ] **Step 2: Add `api.queries` method**

In the `api` object, add after the `tasks` method:

```javascript
  queries(range) {
    const bucket = isDayView(range) ? '1h' : '1d';
    return api.get(`/api/queries?range=${range}&bucket=${bucket}`);
  },
```

- [ ] **Step 3: Add `padQueries` function**

Add after `padTasks`:

```javascript
function padQueries(queriesData, range) {
  if (isDayView(range)) {
    const dayStart = range === 'today'
      ? (() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); })()
      : parseInt(range.split(':')[1]);
    const map = new Map(queriesData.map(b => [b.date, b]));
    const result = [];
    for (let h = 0; h < 24; h++) {
      const ts = dayStart + h * 3_600_000;
      result.push(map.get(ts) ?? {
        date: ts, queries: [], other_count: 0, other_tokens: 0, p50_tpq: 0, max_tpq: 0,
      });
    }
    return result;
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

- [ ] **Step 4: Update `onChartClick` to include `_paddedQueries`**

Replace:
```javascript
  const ts = _paddedTimeline[idx]?.date ?? _paddedTasks[idx]?.date;
```
With:
```javascript
  const ts = _paddedTimeline[idx]?.date ?? _paddedTasks[idx]?.date ?? _paddedQueries[idx]?.date;
```

- [ ] **Step 5: Update `initCharts` — queryChart to stacked**

Replace the `queryChart = new Chart(...)` block in `initCharts`:

```javascript
  queryChart = new Chart(document.getElementById('query-chart'), {
    data: { labels: [], datasets: [] },
    options: {
      ...CHART_DEFAULTS, ...clickOpts,
      plugins: { ...CHART_DEFAULTS.plugins, tooltip: {
        ...CHART_DEFAULTS.plugins.tooltip,
        filter: item => item.raw !== null && item.raw !== 0,
        callbacks: {
          title: items => items[0].label,
          label: item => ` ${item.dataset.label}`,
        },
      }},
      scales: {
        x: SCALE_X,
        yLeft: { ...SCALE_LEFT, stacked: true, yAxisID: 'yLeft' },
        yRight: { ...SCALE_RIGHT('#888', v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v), yAxisID: 'yRight' },
      },
    },
  });
```

- [ ] **Step 6: Replace `renderQueryChart`**

Replace the entire `renderQueryChart` function:

```javascript
function renderQueryChart(queriesData, range) {
  const padded = padQueries(queriesData, range);
  _paddedQueries = padded;
  if (!padded.length) return;

  const labels = padded.map(b => bucketLabel(b.date, range));
  const maxQ = Math.max(...padded.map(b => b.queries?.length ?? 0), 0);

  const stackDatasets = Array.from({ length: maxQ }, (_, i) => ({
    type: 'bar',
    label: `Query ${i + 1}`,
    data: padded.map(b => b.queries?.[i]?.total_tokens ?? null),
    backgroundColor: PALETTE[i % PALETTE.length],
    borderColor: 'rgba(0,0,0,0.12)', borderWidth: 0.5,
    borderRadius: i === 0 ? { bottomLeft: 3, bottomRight: 3 } : 0,
    borderSkipped: false, stack: 'queries', yAxisID: 'yLeft', order: 2,
  }));

  const otherDataset = {
    type: 'bar',
    label: 'other',
    data: padded.map(b => b.other_tokens > 0 ? b.other_tokens : null),
    backgroundColor: 'rgba(100,100,120,0.5)',
    borderColor: 'rgba(0,0,0,0.12)', borderWidth: 0.5,
    borderSkipped: false, stack: 'queries', yAxisID: 'yLeft', order: 2,
  };

  queryChart.options.plugins.tooltip.callbacks = {
    title: items => items[0].label,
    label: item => {
      if (item.dataset.label === 'p50 tok') return ` p50: ${fmt(item.raw)}`;
      if (item.dataset.label === 'top tok') return ` max: ${fmt(item.raw)}`;
      if (item.dataset.label === 'other') {
        const b = padded[item.dataIndex];
        return ` +${b.other_count} other: ${fmt(item.raw)} tokens`;
      }
      const b = padded[item.dataIndex];
      const q = b.queries?.[item.datasetIndex];
      return ` ${q?.query_id ?? item.dataset.label}: ${fmt(item.raw)} tokens`;
    },
  };

  const activeBuckets = padded.filter(b => (b.queries?.length ?? 0) > 0).length;
  const hasOther = padded.some(b => b.other_tokens > 0);
  queryChart.data.labels = labels;
  queryChart.data.datasets = [
    ...stackDatasets,
    ...(hasOther ? [otherDataset] : []),
    ...(activeBuckets >= 2 ? [
      {
        type: 'line', label: 'p50 tok',
        data: padded.map(b => b.p50_tpq || null),
        borderColor: '#fcd34d', borderWidth: 1.5, borderDash: [4, 2],
        pointRadius: 2, pointBackgroundColor: '#fcd34d',
        spanGaps: false, tension: 0.4, yAxisID: 'yRight', order: 1,
      },
      {
        type: 'line', label: 'top tok',
        data: padded.map(b => b.max_tpq || null),
        borderColor: '#f87171', borderWidth: 1.5,
        pointRadius: 2, pointBackgroundColor: '#f87171',
        spanGaps: false, tension: 0.4, yAxisID: 'yRight', order: 1,
      },
    ] : []),
  ];
  queryChart.update();
}
```

- [ ] **Step 7: Update `refresh()` to fetch queriesData and pass to renderQueryChart**

In `refresh`, add `api.queries(currentRange)` to the Promise.all and pass result to `renderQueryChart`.

Replace:
```javascript
  const [stats, timeline, tasks, sessions, config] = await Promise.all([
    api.stats(currentRange),
    api.timeline(currentRange),
    api.tasks(currentRange),
    api.sessions(currentRange),
    api.config(),
  ]);
```
With:
```javascript
  const [stats, timeline, tasks, queriesData, sessions, config] = await Promise.all([
    api.stats(currentRange),
    api.timeline(currentRange),
    api.tasks(currentRange),
    api.queries(currentRange),
    api.sessions(currentRange),
    api.config(),
  ]);
```

Then replace the `renderQueryChart(timeline, currentRange)` call (in the `else` branch) with:
```javascript
    renderQueryChart(queriesData, currentRange);
```

- [ ] **Step 8: Bump sessions limit to 10**

In the `api` object, change:
```javascript
  sessions(range) { return api.get(`/api/sessions?range=${range}&limit=5`); },
```
To:
```javascript
  sessions(range) { return api.get(`/api/sessions?range=${range}&limit=10`); },
```

- [ ] **Step 9: Manual verification**

Open the dashboard. In 7d/30d view: queries chart now shows stacked colored bars (one per query in the bucket, up to 10) with a grey "other" segment if applicable. Yellow dashed p50 and red max lines appear when there are multiple data points. Hovering shows query_id and token count.

- [ ] **Step 10: Run lint**

```bash
just lint
```

- [ ] **Step 11: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat(ui): replace queries bar chart with stacked per-query token chart; add p50/max lines"
```

---

## Task 7: JS — day view hourly charts

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Update `bucketLabel` to treat `day:X` like `today`**

Replace `bucketLabel`:

```javascript
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

- [ ] **Step 2: Update `api.timeline` and `api.tasks` bucket selection**

In the `api` object, replace:
```javascript
  timeline(range) { return api.get(`/api/timeline?range=${range}&bucket=${range === 'today' ? '1h' : '1d'}`); },
  tasks(range)    { return api.get(`/api/tasks?range=${range}`); },
```
With:
```javascript
  timeline(range) { return api.get(`/api/timeline?range=${range}&bucket=${isDayView(range) ? '1h' : '1d'}`); },
  tasks(range)    { return api.get(`/api/tasks?range=${range}&bucket=${isDayView(range) ? '1h' : '1d'}`); },
```

- [ ] **Step 3: Update `padTimeline` to fill 24 hourly buckets in day views**

Replace `padTimeline`:

```javascript
function padTimeline(timeline, range) {
  if (isDayView(range)) {
    const dayStart = range === 'today'
      ? (() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); })()
      : parseInt(range.split(':')[1]);
    const map = new Map(timeline.map(b => [b.date, b]));
    const result = [];
    for (let h = 0; h < 24; h++) {
      const ts = dayStart + h * 3_600_000;
      result.push(map.get(ts) ?? {
        date: ts, input_tokens: 0, output_tokens: 0,
        cache_hit_rate: 0, queries: 0, tokens_per_query: 0,
      });
    }
    return result;
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

- [ ] **Step 4: Update `padTasks` to fill 24 hourly buckets in day views**

Replace `padTasks`:

```javascript
function padTasks(tasksData, range) {
  if (isDayView(range)) {
    const dayStart = range === 'today'
      ? (() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); })()
      : parseInt(range.split(':')[1]);
    const map = new Map(tasksData.map(d => [d.date, d]));
    const result = [];
    for (let h = 0; h < 24; h++) {
      const ts = dayStart + h * 3_600_000;
      result.push(map.get(ts) ?? {
        date: ts, tasks: [],
        avg_tokens_per_task: 0, p50_tokens_per_task: 0, max_tokens_per_task: 0,
      });
    }
    return result;
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

- [ ] **Step 5: Update `setViewMode` — show charts in day views**

Replace `setViewMode`:

```javascript
function setViewMode(range) {
  const day = isDayView(range);
  document.getElementById('today-summary').classList.toggle('hidden', !day);
}
```

- [ ] **Step 6: Update `refresh()` — always render charts**

In `refresh`, replace the current if/else block:

```javascript
  if (isDayView(currentRange)) {
    renderTodaySummary(stats, currentRange);
  } else {
    renderTokenChart(timeline, currentRange);
    renderQueryChart(queriesData, currentRange);
    renderTaskChart(tasks, currentRange);
  }
```

With:

```javascript
  if (isDayView(currentRange)) {
    renderTodaySummary(stats, currentRange);
  }
  renderTokenChart(timeline, currentRange);
  renderTaskChart(tasks, currentRange);
  renderQueryChart(queriesData, currentRange);
```

- [ ] **Step 7: Manual verification**

Open the dashboard. Click "Today": the 4-stat summary row is visible AND all three charts appear below it with hourly x-axis labels (e.g., "12 AM", "1 AM"). Click a bar in the 7d token chart to drill into that day: same behaviour — stat counters + hourly charts. Click "7d" to return to multi-day view.

- [ ] **Step 8: Run lint + full tests**

```bash
just lint && just test
```

Expected: lint clean, all tests pass.

- [ ] **Step 9: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat(ui): show hourly charts in day views alongside stat counters"
```

---

## Done

All seven tasks produce a fully working dashboard:
- Tasks & queries chart has p50 (yellow dashed) + max (red solid) lines
- Queries chart is stacked per-query token bars with p50/max lines
- Day/today view shows stat counters + all three hourly charts
- Sections ordered: stats → tokens chart → recent sessions → tasks → queries → models → budget
- Sessions list scrollable, fetches 10 rows
