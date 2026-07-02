# Dashboard Hover Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve three dashboard hover behaviors — richer date/time tooltip titles, reliable full-name hover for skills/MCP tools, and human-readable query names sourced from the first prompt.

**Architecture:** Query names are captured at index time into a new in-memory `queries` table (truncated to 60 chars), joined into the existing `query_query_breakdown`, and shown in the query chart's Chart.js tooltip. Date tooltip titles and the skill/MCP hover are pure frontend changes in `app.js` / `style.css`.

**Tech Stack:** Python 3.11+ (stdlib `sqlite3`), pytest, vanilla JS + Chart.js, CSS.

## Global Constraints

- **In-memory SQLite only** — `db.connect()` always returns `":memory:"`. No `DB_PATH`. New tables go in the `SCHEMA` string.
- **All DB writers hold `_LOCK`** and call `conn.commit()` (see `upsert_session`, `insert_message`).
- **venv required** — run all tooling via `.venv/bin/` prefixes or an activated venv (`just test`, `just lint`).
- **Coverage ≥ 80%** (`just coverage`); **lint clean** (`just lint`); **all tests pass** (`just test`).
- **No new dependencies.**
- **`esc()` on any server-supplied string interpolated into `innerHTML`** (app.js). Chart.js tooltips render on `<canvas>`, so values placed only in tooltip callbacks do NOT need `esc()`.
- **No JS test runner exists** — frontend-only tasks are verified manually by launching the app; keep JS helpers small and pure.
- **Versioning:** this is a feature. Run `just bump-minor` once before the first commit that touches shipping code (the pre-commit hook then bumps patch on top — expected). Do NOT edit `_version.py` / `pyproject.toml` by hand.

---

### Task 1: `queries` table + `upsert_query()`

**Files:**
- Modify: `claudemon/db.py` (SCHEMA string ~lines 7–57; add function after `insert_tool_use` ~line 125)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `db.upsert_query(conn, session_id: str, query_id: str, text: str) -> None` — inserts `(query_id, session_id, text)` with `INSERT OR IGNORE` (first write wins). New table `queries(query_id TEXT PRIMARY KEY, session_id TEXT, text TEXT)`.

- [ ] **Step 1: Bump the minor version (once, before any shipping-code commit)**

Run: `just bump-minor`
Expected: prints a new minor version (e.g. `Version bumped to 0.7.0`).

- [ ] **Step 2: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_upsert_query_insert(conn):
    db.upsert_query(conn, "s1", "s1:1:1", "fix the hover behaviors")
    row = conn.execute("SELECT * FROM queries WHERE query_id='s1:1:1'").fetchone()
    assert row["session_id"] == "s1"
    assert row["text"] == "fix the hover behaviors"


def test_upsert_query_ignores_replay(conn):
    db.upsert_query(conn, "s1", "s1:1:1", "first prompt")
    db.upsert_query(conn, "s1", "s1:1:1", "second prompt")
    row = conn.execute("SELECT text FROM queries WHERE query_id='s1:1:1'").fetchone()
    assert row["text"] == "first prompt"  # first write wins
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_db.py::test_upsert_query_insert -v`
Expected: FAIL — `AttributeError: module 'claudemon.db' has no attribute 'upsert_query'` (or `no such table: queries`).

- [ ] **Step 4: Add the table to SCHEMA**

In `claudemon/db.py`, inside the `SCHEMA = """..."""` string, add after the `tool_uses` block (after the `idx_tool_uses_ts` index line, before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS queries (
    query_id    TEXT PRIMARY KEY,
    session_id  TEXT,
    text        TEXT
);
```

- [ ] **Step 5: Add the writer**

In `claudemon/db.py`, after the `insert_tool_use` function, add:

```python
def upsert_query(
    conn: sqlite3.Connection,
    session_id: str,
    query_id: str,
    text: str,
) -> None:
    """Store the first-seen prompt text for a query. First write wins."""
    with _LOCK:
        conn.execute(
            "INSERT OR IGNORE INTO queries (query_id, session_id, text)"
            " VALUES (?, ?, ?)",
            (query_id, session_id, text),
        )
        conn.commit()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_db.py::test_upsert_query_insert tests/test_db.py::test_upsert_query_ignores_replay -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add claudemon/db.py tests/test_db.py
git commit -m "feat: add queries table and upsert_query for query names"
```

---

### Task 2: Capture first-prompt text in the indexer

**Files:**
- Modify: `claudemon/indexer.py` (module constant near top; helper near `_is_clear_command` ~line 25; new-query branch ~lines 141–147)
- Test: `tests/test_indexer.py`

**Interfaces:**
- Consumes: `db.upsert_query(conn, session_id, query_id, text)` from Task 1.
- Produces: `indexer._extract_prompt_text(record: dict) -> str` — first text content, whitespace-collapsed, `""` if none. Constant `indexer._QUERY_TEXT_MAX = 60`. Indexing now populates the `queries` table with text truncated to 60 chars.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_indexer.py`:

```python
def test_extract_prompt_text_list_content():
    rec = {"message": {"content": [
        {"type": "text", "text": "  fix  the   hover\n behaviors "},
    ]}}
    assert indexer._extract_prompt_text(rec) == "fix the hover behaviors"


def test_extract_prompt_text_string_content():
    rec = {"message": {"content": "just a string prompt"}}
    assert indexer._extract_prompt_text(rec) == "just a string prompt"


def test_extract_prompt_text_none():
    rec = {"message": {"content": [{"type": "tool_result", "content": "x"}]}}
    assert indexer._extract_prompt_text(rec) == ""


def test_index_file_stores_query_text(conn):
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    row = conn.execute(
        "SELECT text FROM queries WHERE query_id='abc123:1:1'"
    ).fetchone()
    assert row["text"] == "Hello"


def test_index_file_truncates_query_text(conn, tmp_path):
    long_prompt = "x" * 200
    line = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": long_prompt}]},
        "timestamp": "2026-06-01T10:00:00.000Z",
        "sessionId": "longsess", "uuid": "u1", "parentUuid": None,
        "cwd": "/Users/test/test-project", "gitBranch": "main",
        "isSidechain": False, "isMeta": False,
    }
    assistant = {
        "type": "assistant",
        "message": {"model": "claude-sonnet-4-6", "usage": {"output_tokens": 10}},
        "timestamp": "2026-06-01T10:00:01.000Z", "sessionId": "longsess",
        "uuid": "a1", "cwd": "/Users/test/test-project", "gitBranch": "main",
    }
    import json
    f = tmp_path / "longsess.jsonl"
    f.write_text(json.dumps(line) + "\n" + json.dumps(assistant) + "\n")
    indexer.index_file(conn, f, task_gap_minutes=30)
    row = conn.execute(
        "SELECT text FROM queries WHERE query_id='longse:1:1'"
    ).fetchone()
    assert row["text"] == "x" * 60
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_indexer.py -k "prompt_text or query_text" -v`
Expected: FAIL — `AttributeError: module 'claudemon.indexer' has no attribute '_extract_prompt_text'`.

- [ ] **Step 3: Add the constant and helper**

In `claudemon/indexer.py`, add the constant after the imports (after `import claudemon.db as db`):

```python
_QUERY_TEXT_MAX = 60
```

Add this helper right after `_is_clear_command` (before `index_file`):

```python
def _extract_prompt_text(record: dict) -> str:
    """First text content of a user message, whitespace-collapsed. '' if none."""
    content = record.get("message", {}).get("content", [])
    if isinstance(content, list):
        text = " ".join(
            c.get("text", "")
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        )
    elif isinstance(content, str):
        text = content
    else:
        return ""
    return " ".join(text.split())
```

- [ ] **Step 4: Store the text in the new-query branch**

In `claudemon/indexer.py`, in the `rec_type == "user" and _is_new_query(record)` branch, immediately after the line `current_query_id = f"{short_id}:{task_num}:{query_num}"` (before `last_branch = branch`):

```python
                prompt_text = _extract_prompt_text(record)
                if prompt_text:
                    db.upsert_query(
                        conn, session_id, current_query_id,
                        prompt_text[:_QUERY_TEXT_MAX],
                    )
```

(Indentation: this sits inside the `if is_new_query:`/`else:` block's parent — same level as `short_id = session_id[:6]`.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_indexer.py -k "prompt_text or query_text" -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Run the full indexer + db suites (guard against regressions)**

Run: `.venv/bin/pytest tests/test_indexer.py tests/test_db.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add claudemon/indexer.py tests/test_indexer.py
git commit -m "feat: capture first-prompt text per query at index time"
```

---

### Task 3: Return query text from `query_query_breakdown`

**Files:**
- Modify: `claudemon/db.py` (`query_query_breakdown` ~lines 339–394)
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `queries` table + `upsert_query` from Task 1.
- Produces: each per-query dict from `query_query_breakdown` now includes `"text"` (str or `None`): `{"query_id", "text", "total_tokens"}`. Existing keys (`date`, `queries`, `other_count`, `other_tokens`, `p50_tpq`, `max_tpq`) unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_query_query_breakdown_includes_text(conn):
    db.upsert_session(conn, "s1", "proj", None, 0, 99_000_000_000, "main")
    ts_base = 1749340800000
    db.insert_message(conn, "s1", "s1:1", "s1:1:1", ts_base, "claude-sonnet-4-6", 0, 50, 0, 0)
    db.insert_message(conn, "s1", "s1:1", "s1:1:2", ts_base + 1000, "claude-sonnet-4-6", 0, 80, 0, 0)
    db.upsert_query(conn, "s1", "s1:1:1", "named query")
    # s1:1:2 has no stored text
    result = db.query_query_breakdown(conn, (ts_base, ts_base + 10_000))
    by_id = {q["query_id"]: q for q in result[0]["queries"]}
    assert by_id["s1:1:1"]["text"] == "named query"
    assert by_id["s1:1:2"]["text"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_db.py::test_query_query_breakdown_includes_text -v`
Expected: FAIL — `KeyError: 'text'`.

- [ ] **Step 3: Update the SQL and the row-assembly**

In `claudemon/db.py`, replace the SQL query inside `query_query_breakdown` (the `conn.execute(f"""...""")` block) with:

```python
    rows = conn.execute(f"""
        SELECT
            {trunc}                                   AS bucket_ts,
            m.query_id                                AS query_id,
            q.text                                    AS text,
            SUM(m.input_tokens + m.output_tokens)     AS total_tokens
        FROM messages m
        LEFT JOIN queries q ON q.query_id = m.query_id
        WHERE m.timestamp BETWEEN ? AND ?
        GROUP BY bucket_ts, m.query_id
        ORDER BY bucket_ts, total_tokens DESC
    """, (start_ms, end_ms)).fetchall()
```

Then update the per-row append (the `raw[ts].append(...)` line) to carry `text`:

```python
        raw[ts].append({
            "query_id": r["query_id"],
            "text": r["text"],
            "total_tokens": r["total_tokens"],
        })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_db.py::test_query_query_breakdown_includes_text -v`
Expected: PASS.

- [ ] **Step 5: Run the full db + server suites**

Run: `.venv/bin/pytest tests/test_db.py tests/test_server.py -v`
Expected: all PASS (server `/api/queries` still serializes the extra field fine).

- [ ] **Step 6: Commit**

```bash
git add claudemon/db.py tests/test_db.py
git commit -m "feat: return per-query prompt text from query_query_breakdown"
```

---

### Task 4: Show query names in the query chart tooltip

**Files:**
- Modify: `claudemon/dashboard/app.js` (`renderQueryChart` label callback ~lines 448–450)

**Interfaces:**
- Consumes: `text` field on each query object from Task 3 (`b.queries[i].text`).
- Produces: query tooltip label shows the truncated prompt text instead of `query_id`.

- [ ] **Step 1: Update the label callback**

In `claudemon/dashboard/app.js`, inside `renderQueryChart`'s `queryChart.options.plugins.tooltip.callbacks.label`, replace the final two lines of the callback:

```javascript
      const b = padded[item.dataIndex];
      const q = b.queries?.[item.dataset.queryIndex];
      return ` ${q?.query_id ?? item.dataset.label}: ${fmt(item.raw)} tokens`;
```

with:

```javascript
      const b = padded[item.dataIndex];
      const q = b.queries?.[item.dataset.queryIndex];
      const name = q?.text || q?.query_id || item.dataset.label;
      const shown = name.length > 50 ? name.slice(0, 49) + '…' : name;
      return ` ${shown}: ${fmt(item.raw)} tokens`;
```

(No `esc()` — this value is rendered by Chart.js on a canvas, not via `innerHTML`.)

- [ ] **Step 2: Manually verify in the app**

Run: `just run` (or launch the app the usual way). Open the dashboard, pick a multi-day or day range with query data, hover a query bar segment.
Expected: tooltip shows the prompt text (e.g. `fix the hover behaviors: 12k tokens`) instead of `027d99:1:1`. Queries with no stored text still show the ID.

- [ ] **Step 3: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat: show query prompt text in query chart tooltip"
```

---

### Task 5: Richer date/time tooltip titles

**Files:**
- Modify: `claudemon/dashboard/app.js` (add helper after `bucketLabel` ~line 283; `renderTokenChart` ~line 408; `renderQueryChart` title callback ~line 440; `renderTaskChart` title callback ~line 498)

**Interfaces:**
- Consumes: `isHourBucket(range)` and `fmtHour(ts)` (existing); module padded arrays `_paddedTimeline` / `_paddedQueries` / `_paddedTasks`.
- Produces: `tooltipDateTitle(ts: number, range: string) -> string` — `"Jul 11"` for day views, `"8am · Jul 2"` for hour views.

- [ ] **Step 1: Add the helper**

In `claudemon/dashboard/app.js`, after the `bucketLabel` function (right before the `// ── Gap filling ──` comment), add:

```javascript
function tooltipDateTitle(ts, range) {
  const md = new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return isHourBucket(range) ? `${fmtHour(ts)} · ${md}` : md;
}
```

- [ ] **Step 2: Set the title callback on the token chart**

In `renderTokenChart`, before the final `tokenChart.update();`, add:

```javascript
  tokenChart.options.plugins.tooltip.callbacks = {
    title: items => tooltipDateTitle(padded[items[0].dataIndex].date, range),
  };
```

- [ ] **Step 3: Update the query chart title callback**

In `renderQueryChart`, change the `title` line inside `queryChart.options.plugins.tooltip.callbacks` from:

```javascript
    title: items => items[0].label,
```

to:

```javascript
    title: items => tooltipDateTitle(padded[items[0].dataIndex].date, range),
```

- [ ] **Step 4: Update the task chart title callback**

In `renderTaskChart`, change the `title` line inside `taskChart.options.plugins.tooltip.callbacks` from:

```javascript
    title: items => items[0].label,
```

to:

```javascript
    title: items => tooltipDateTitle(padded[items[0].dataIndex].date, range),
```

- [ ] **Step 5: Manually verify in the app**

Run: `just run`. Hover bars in the Tokens, Queries, and Tasks charts.
Expected: in a 7d/30d view the tooltip title reads e.g. `Jul 11`; in a Today/day view it reads e.g. `8am · Jul 2`. X-axis tick labels are unchanged (still `11` / `8am`).

- [ ] **Step 6: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat: richer date/time titles in chart tooltips"
```

---

### Task 6: Skill / MCP full-name hover anywhere on the row

**Files:**
- Modify: `claudemon/dashboard/app.js` (`renderSkills` ~lines 666–673, `renderMcp` ~lines 683–690)
- Modify: `claudemon/dashboard/style.css` (`.tool-row` ~line 300; add `.tool-tip` rules)

**Interfaces:**
- Produces: hovering anywhere on a `.tool-row` reveals a custom tooltip with the full (esc'd) skill/MCP name. Native `title` attribute removed.

- [ ] **Step 1: Update `renderSkills` markup**

In `claudemon/dashboard/app.js`, in `renderSkills`, replace the returned template with:

```javascript
    return `<div class="tool-row">
      <div class="tool-name">${esc(s.name)}</div>
      <div class="tool-bar-wrap"><div class="tool-fill skill-fill" style="width:${pct}%"></div></div>
      <div class="tool-meta">×${s.calls} · ${fmt(s.p50_output_tokens)} 50% / ${fmt(s.max_output_tokens)} max</div>
      <span class="tool-tip">${esc(s.name)}</span>
    </div>`;
```

- [ ] **Step 2: Update `renderMcp` markup**

In `renderMcp`, replace the returned template with:

```javascript
    return `<div class="tool-row">
      <div class="tool-name">${esc(m.name)}</div>
      <div class="tool-bar-wrap"><div class="tool-fill mcp-fill" style="width:${pct}%"></div></div>
      <div class="tool-meta">×${m.calls} · ${fmt(m.p50_output_tokens)} 50% / ${fmt(m.max_output_tokens)} max</div>
      <span class="tool-tip">${esc(m.name)}</span>
    </div>`;
```

- [ ] **Step 3: Add CSS**

In `claudemon/dashboard/style.css`, change the `.tool-row` rule to add positioning:

```css
.tool-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  position: relative;
}
```

Then add after the `.mcp-fill` rule (~line 326):

```css
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

- [ ] **Step 4: Manually verify in the app**

Run: `just run`. Expand the Skills and MCP sections. Hover anywhere along a skill/MCP row (over the name, the bar, or the meta text).
Expected: a tooltip with the full name appears above the row, from anywhere on the row — not just the ellipsis. Long names (e.g. `superpowers:brainstorming`) show in full.

- [ ] **Step 5: Commit**

```bash
git add claudemon/dashboard/app.js claudemon/dashboard/style.css
git commit -m "feat: skill/MCP full-name tooltip on whole-row hover"
```

---

### Task 7: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite with coverage**

Run: `just coverage`
Expected: all tests pass; coverage ≥ 80%.

- [ ] **Step 2: Lint**

Run: `just lint`
Expected: clean.

- [ ] **Step 3: Update agent docs**

Add a row to the "Recently Changed Areas" table in `docs/agent/project-analysis.md` describing this feature (queries table + query names, richer tooltip titles, whole-row skill/MCP hover). If any lesson emerged (e.g. re-confirming native `title` unreliability), append it to `docs/agent/lessons.md`.

- [ ] **Step 4: Commit docs**

```bash
git add docs/agent/project-analysis.md docs/agent/lessons.md
git commit -m "docs: record dashboard hover improvements"
```

---

## Self-Review

**Spec coverage:**
- §1 Richer date tooltips → Task 5 ✓
- §2 Skill/MCP hover → Task 6 ✓
- §3 Query names: storage → Task 1; index-time capture + truncation → Task 2; breakdown join → Task 3; frontend label → Task 4 ✓
- Testing section → Tasks 1–3 have TDD; frontend Tasks 4–6 have manual verify (no JS runner, per spec); Task 7 covers coverage/lint ✓
- Versioning (`just bump-minor`) → Task 1 Step 1 ✓

**Placeholder scan:** No TBD/TODO; all code shown inline.

**Type consistency:** `upsert_query(conn, session_id, query_id, text)` used identically in Tasks 1, 2, 3-test. `_extract_prompt_text(record)` and `_QUERY_TEXT_MAX` consistent in Task 2. `text` field key consistent across Tasks 2/3/4. `tooltipDateTitle(ts, range)` consistent across Task 5 steps. Note: the truncation test in Task 2 (`test_index_file_truncates_query_text`) depends on `upsert_query` from Task 1 and the `queries` table — both land before Task 2 runs.
