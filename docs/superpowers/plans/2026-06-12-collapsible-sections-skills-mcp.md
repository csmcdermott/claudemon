# Collapsible Sections + Skills & MCP Usage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all dashboard sections after "Daily tokens" collapsible (default collapsed), and add "Skills used" and "MCP tools" ranked-list panels.

**Architecture:** Extend the DB with a `tool_uses` table, populated by the indexer parsing `message.content` tool_use blocks that already exist in assistant JSONL records. A new `/api/tools` endpoint aggregates call counts, p50, and max output tokens per skill/MCP service. The dashboard wraps existing sections in `.csec` divs with a single delegated click handler, and renders two new ranked-list sections after model breakdown.

**Tech Stack:** Python 3.11+ (sqlite3, http.server), vanilla JS, CSS

---

## Files

| File | Change |
|---|---|
| `claudemon/db.py` | Add `tool_uses` to SCHEMA; add `insert_tool_use()`; add `query_tool_usage()` |
| `claudemon/indexer.py` | Parse `message.content` tool_use blocks inside the assistant record branch |
| `claudemon/server.py` | Add `/api/tools` route to `do_GET` |
| `claudemon/dashboard/style.css` | Add `.csec*` and `.tool-row*` rules |
| `claudemon/dashboard/index.html` | Replace collapsible `<section>` tags with `.csec` divs; add skills + mcp sections |
| `claudemon/dashboard/app.js` | Add `initCollapsibles()`, `api.tools()`, `renderSkills()`, `renderMcp()`; extend `refresh()` and `DOMContentLoaded` |
| `tests/test_db.py` | Add tests for `insert_tool_use` and `query_tool_usage` |
| `tests/test_indexer.py` | Add tests for tool_use content block parsing |
| `tests/test_server.py` | Add tests for `/api/tools` |

---

### Task 1: DB — tool_uses schema + insert_tool_use

**Files:**
- Modify: `claudemon/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_tool_uses_table_exists(conn):
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "tool_uses" in tables


def test_insert_tool_use_basic(conn):
    db.upsert_session(conn, "s1", "proj", None, 1000, 2000, "main")
    db.insert_tool_use(conn, "s1", "s1:1:1", 1500, "skill", "brainstorming", 500)
    rows = conn.execute("SELECT * FROM tool_uses WHERE session_id='s1'").fetchall()
    assert len(rows) == 1
    assert rows[0]["tool_type"] == "skill"
    assert rows[0]["tool_name"] == "brainstorming"
    assert rows[0]["output_tokens"] == 500


def test_insert_tool_use_deduplication(conn):
    db.upsert_session(conn, "s1", "proj", None, 1000, 2000, "main")
    db.insert_tool_use(conn, "s1", "s1:1:1", 1500, "skill", "brainstorming", 500)
    db.insert_tool_use(conn, "s1", "s1:1:1", 1500, "skill", "brainstorming", 500)
    count = conn.execute("SELECT COUNT(*) FROM tool_uses").fetchone()[0]
    assert count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test tests/test_db.py::test_tool_uses_table_exists tests/test_db.py::test_insert_tool_use_basic tests/test_db.py::test_insert_tool_use_deduplication
```

Expected: `AttributeError: module 'claudemon.db' has no attribute 'insert_tool_use'`

- [ ] **Step 3: Add SCHEMA table and insert_tool_use to db.py**

In `claudemon/db.py`, append to the `SCHEMA` string (before the closing `"""`):

```python
CREATE TABLE IF NOT EXISTS tool_uses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT REFERENCES sessions(session_id),
    query_id      TEXT,
    timestamp     INTEGER,
    tool_type     TEXT,
    tool_name     TEXT,
    output_tokens INTEGER DEFAULT 0,
    UNIQUE (session_id, query_id, timestamp, tool_type, tool_name)
);
CREATE INDEX IF NOT EXISTS idx_tool_uses_ts ON tool_uses(timestamp);
```

After `insert_message()` in `claudemon/db.py`, add:

```python
def insert_tool_use(
    conn: sqlite3.Connection,
    session_id: str,
    query_id: str,
    timestamp: int,
    tool_type: str,
    tool_name: str,
    output_tokens: int,
) -> None:
    with _LOCK:
        conn.execute("""
            INSERT OR IGNORE INTO tool_uses
                (session_id, query_id, timestamp, tool_type, tool_name, output_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, query_id, timestamp, tool_type, tool_name, output_tokens))
        conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test tests/test_db.py::test_tool_uses_table_exists tests/test_db.py::test_insert_tool_use_basic tests/test_db.py::test_insert_tool_use_deduplication
```

Expected: 3 passed

- [ ] **Step 5: Run full test suite to verify no regressions**

```bash
just test
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add claudemon/db.py tests/test_db.py
git commit -m "feat: add tool_uses table and insert_tool_use to db"
```

---

### Task 2: DB — query_tool_usage

**Files:**
- Modify: `claudemon/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_query_tool_usage_empty_range(conn):
    now = int(time.time() * 1000)
    db.upsert_session(conn, "s1", "proj", None, 1000, 2000, "main")
    db.insert_tool_use(conn, "s1", "s1:1:1", 1500, "skill", "brainstorming", 500)
    result = db.query_tool_usage(conn, (now + 1_000_000, now + 2_000_000))
    assert result == {"skills": [], "mcp": []}


def test_query_tool_usage_basic(conn):
    now = int(time.time() * 1000)
    db.upsert_session(conn, "s1", "proj", None, now - 5000, now, "main")
    db.insert_tool_use(conn, "s1", "s1:1:1", now - 4000, "skill", "brainstorming", 500)
    db.insert_tool_use(conn, "s1", "s1:1:2", now - 3000, "skill", "brainstorming", 1000)
    db.insert_tool_use(conn, "s1", "s1:1:3", now - 2000, "skill", "tdd", 800)
    db.insert_tool_use(conn, "s1", "s1:1:1", now - 4000, "mcp", "playwright", 500)
    result = db.query_tool_usage(conn, (now - 10_000, now))
    # brainstorming has 2 calls, tdd has 1 — sorted descending by calls
    assert result["skills"][0]["name"] == "brainstorming"
    assert result["skills"][0]["calls"] == 2
    assert result["skills"][1]["name"] == "tdd"
    assert result["skills"][1]["calls"] == 1
    assert result["mcp"][0]["name"] == "playwright"
    assert result["mcp"][0]["calls"] == 1


def test_query_tool_usage_p50_max(conn):
    now = int(time.time() * 1000)
    db.upsert_session(conn, "s1", "proj", None, now - 5000, now, "main")
    db.insert_tool_use(conn, "s1", "s1:1:1", now - 4000, "skill", "brainstorming", 500)
    db.insert_tool_use(conn, "s1", "s1:1:2", now - 3000, "skill", "brainstorming", 1000)
    db.insert_tool_use(conn, "s1", "s1:1:3", now - 2000, "skill", "brainstorming", 2000)
    result = db.query_tool_usage(conn, (now - 10_000, now))
    skill = result["skills"][0]
    assert skill["calls"] == 3
    # sorted [500, 1000, 2000]; n=3; (3-1)//2 = 1; p50 = 1000
    assert skill["p50_output_tokens"] == 1000
    assert skill["max_output_tokens"] == 2000
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test tests/test_db.py::test_query_tool_usage_empty_range tests/test_db.py::test_query_tool_usage_basic tests/test_db.py::test_query_tool_usage_p50_max
```

Expected: `AttributeError: module 'claudemon.db' has no attribute 'query_tool_usage'`

- [ ] **Step 3: Add query_tool_usage to db.py**

Append to `claudemon/db.py`, after `query_today_output_tokens`:

```python
def query_tool_usage(
    conn: sqlite3.Connection,
    range_ts: tuple[int, int],
) -> dict:
    """Return skill and MCP tool usage aggregated over the range.

    Returns {"skills": [...], "mcp": [...]} sorted by calls descending.
    Each entry: {name, calls, p50_output_tokens, max_output_tokens}.
    """
    start_ms, end_ms = range_ts
    rows = conn.execute("""
        SELECT tool_type, tool_name, output_tokens
        FROM tool_uses
        WHERE timestamp BETWEEN ? AND ?
        ORDER BY tool_type, tool_name
    """, (start_ms, end_ms)).fetchall()

    groups: dict[tuple, list] = {}
    for r in rows:
        key = (r["tool_type"], r["tool_name"])
        if key not in groups:
            groups[key] = []
        groups[key].append(r["output_tokens"])

    skills: list[dict] = []
    mcp: list[dict] = []
    for (tool_type, tool_name), tokens in groups.items():
        n = len(tokens)
        sorted_tok = sorted(tokens)
        entry = {
            "name": tool_name,
            "calls": n,
            "p50_output_tokens": sorted_tok[(n - 1) // 2],
            "max_output_tokens": sorted_tok[-1],
        }
        (skills if tool_type == "skill" else mcp).append(entry)

    skills.sort(key=lambda x: x["calls"], reverse=True)
    mcp.sort(key=lambda x: x["calls"], reverse=True)
    return {"skills": skills, "mcp": mcp}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test tests/test_db.py::test_query_tool_usage_empty_range tests/test_db.py::test_query_tool_usage_basic tests/test_db.py::test_query_tool_usage_p50_max
```

Expected: 3 passed

- [ ] **Step 5: Run full suite**

```bash
just test
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add claudemon/db.py tests/test_db.py
git commit -m "feat: add query_tool_usage to db"
```

---

### Task 3: Indexer — parse tool_use content blocks

**Files:**
- Modify: `claudemon/indexer.py`
- Modify: `tests/test_indexer.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_indexer.py`:

```python
def test_index_file_inserts_skill_tool_use(conn, tmp_path):
    jsonl = tmp_path / "t1.jsonl"
    jsonl.write_text(
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"q"}]},'
        '"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"t1","uuid":"u1",'
        '"parentUuid":null,"cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":10,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":500},"stop_reason":"tool_use","content":[{"type":"tool_use",'
        '"id":"tu_1","name":"Skill","input":{"skill":"brainstorming"}}]},'
        '"timestamp":"2026-06-01T10:00:05.000Z","sessionId":"t1","uuid":"a1",'
        '"parentUuid":"u1","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
    )
    indexer.index_file(conn, jsonl, task_gap_minutes=30)
    rows = conn.execute("SELECT * FROM tool_uses WHERE session_id='t1'").fetchall()
    assert len(rows) == 1
    assert rows[0]["tool_type"] == "skill"
    assert rows[0]["tool_name"] == "brainstorming"
    assert rows[0]["output_tokens"] == 500


def test_index_file_inserts_plugin_mcp_tool_use(conn, tmp_path):
    jsonl = tmp_path / "t2.jsonl"
    jsonl.write_text(
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"q"}]},'
        '"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"t2","uuid":"u1",'
        '"parentUuid":null,"cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":10,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":300},"stop_reason":"tool_use","content":[{"type":"tool_use",'
        '"id":"tu_2","name":"mcp__plugin_playwright_playwright__browser_navigate",'
        '"input":{"url":"http://example.com"}}]},'
        '"timestamp":"2026-06-01T10:00:05.000Z","sessionId":"t2","uuid":"a1",'
        '"parentUuid":"u1","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
    )
    indexer.index_file(conn, jsonl, task_gap_minutes=30)
    rows = conn.execute("SELECT * FROM tool_uses WHERE session_id='t2'").fetchall()
    assert len(rows) == 1
    assert rows[0]["tool_type"] == "mcp"
    assert rows[0]["tool_name"] == "playwright"
    assert rows[0]["output_tokens"] == 300


def test_index_file_inserts_claude_ai_mcp_tool_use(conn, tmp_path):
    jsonl = tmp_path / "t3.jsonl"
    jsonl.write_text(
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"q"}]},'
        '"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"t3","uuid":"u1",'
        '"parentUuid":null,"cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":10,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":200},"stop_reason":"tool_use","content":[{"type":"tool_use",'
        '"id":"tu_3","name":"mcp__claude_ai_Google_Drive__copy_file",'
        '"input":{"fileId":"abc"}}]},'
        '"timestamp":"2026-06-01T10:00:05.000Z","sessionId":"t3","uuid":"a1",'
        '"parentUuid":"u1","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
    )
    indexer.index_file(conn, jsonl, task_gap_minutes=30)
    rows = conn.execute("SELECT * FROM tool_uses WHERE session_id='t3'").fetchall()
    assert len(rows) == 1
    assert rows[0]["tool_type"] == "mcp"
    assert rows[0]["tool_name"] == "google-drive"


def test_index_file_no_tool_use_in_text_only_content(conn, tmp_path):
    jsonl = tmp_path / "t4.jsonl"
    jsonl.write_text(
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"q"}]},'
        '"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"t4","uuid":"u1",'
        '"parentUuid":null,"cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":10,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":100},"stop_reason":"end_turn","content":[{"type":"text",'
        '"text":"Here is the answer."}]},'
        '"timestamp":"2026-06-01T10:00:05.000Z","sessionId":"t4","uuid":"a1",'
        '"parentUuid":"u1","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
    )
    indexer.index_file(conn, jsonl, task_gap_minutes=30)
    count = conn.execute(
        "SELECT COUNT(*) FROM tool_uses WHERE session_id='t4'"
    ).fetchone()[0]
    assert count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test tests/test_indexer.py::test_index_file_inserts_skill_tool_use tests/test_indexer.py::test_index_file_inserts_plugin_mcp_tool_use tests/test_indexer.py::test_index_file_inserts_claude_ai_mcp_tool_use tests/test_indexer.py::test_index_file_no_tool_use_in_text_only_content
```

Expected: 4 fail — `tool_uses` table will exist (from Task 1) but no rows are inserted yet.

- [ ] **Step 3: Add tool_use parsing to indexer.py**

In `claudemon/indexer.py`, inside the `if rec_type == "assistant":` block, immediately after the existing `db.insert_message(...)` call, add:

```python
                for block in msg.get("content", []):
                    if block.get("type") != "tool_use":
                        continue
                    block_name = block.get("name", "")
                    if block_name == "Skill":
                        tool_type = "skill"
                        tool_name = block.get("input", {}).get("skill", "unknown")
                    elif block_name.startswith("mcp__"):
                        tool_type = "mcp"
                        service = block_name.split("__")[1]
                        if service.startswith("plugin_"):
                            service = service.removeprefix("plugin_")
                            tool_name = service.split("_")[0].lower()
                        elif service.startswith("claude_ai_"):
                            tool_name = service.removeprefix("claude_ai_").lower().replace("_", "-")
                        else:
                            tool_name = service.split("_")[0].lower()
                    else:
                        continue
                    db.insert_tool_use(
                        conn, session_id, query_id, ts,
                        tool_type, tool_name, output_tokens,
                    )
```

The variable `query_id` is `current_query_id or f"{short_id}:1:1"` which is already resolved before `db.insert_message`. Use `query_id` (the local variable already assigned on the line above `db.insert_message`). The full assistant block after your change:

```python
            if rec_type == "assistant":
                msg = record.get("message", {})
                usage = msg.get("usage", {})
                model = msg.get("model", "unknown")

                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)

                if ts is None:
                    continue

                # Ensure session exists
                proj = session_project or project
                db.upsert_session(
                    conn, session_id, proj, pending_title,
                    session_started_at or ts, ts,
                    last_branch,
                )
                pending_title = None  # consumed

                short_id = session_id[:6]
                task_id = f"{short_id}:{task_num}" if task_num > 0 else f"{short_id}:1"
                query_id = current_query_id or f"{short_id}:1:1"

                db.insert_message(
                    conn, session_id, task_id, query_id, ts, model,
                    input_tokens, output_tokens, cache_creation, cache_read,
                )

                for block in msg.get("content", []):
                    if block.get("type") != "tool_use":
                        continue
                    block_name = block.get("name", "")
                    if block_name == "Skill":
                        tool_type = "skill"
                        tool_name = block.get("input", {}).get("skill", "unknown")
                    elif block_name.startswith("mcp__"):
                        tool_type = "mcp"
                        service = block_name.split("__")[1]
                        if service.startswith("plugin_"):
                            service = service.removeprefix("plugin_")
                            tool_name = service.split("_")[0].lower()
                        elif service.startswith("claude_ai_"):
                            tool_name = service.removeprefix("claude_ai_").lower().replace("_", "-")
                        else:
                            tool_name = service.split("_")[0].lower()
                    else:
                        continue
                    db.insert_tool_use(
                        conn, session_id, query_id, ts,
                        tool_type, tool_name, output_tokens,
                    )

                if ts:
                    last_timestamp = ts
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test tests/test_indexer.py::test_index_file_inserts_skill_tool_use tests/test_indexer.py::test_index_file_inserts_plugin_mcp_tool_use tests/test_indexer.py::test_index_file_inserts_claude_ai_mcp_tool_use tests/test_indexer.py::test_index_file_no_tool_use_in_text_only_content
```

Expected: 4 passed

- [ ] **Step 5: Run full suite**

```bash
just test
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add claudemon/indexer.py tests/test_indexer.py
git commit -m "feat: index skill and MCP tool_use blocks from assistant records"
```

---

### Task 4: Server — /api/tools endpoint

**Files:**
- Modify: `claudemon/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_server.py`, add a new fixture and two tests:

```python
@pytest.fixture
def tools_seeded_conn(conn):
    """DB with tool_uses rows for /api/tools testing."""
    now = int(time.time() * 1000)
    db.upsert_session(conn, "t1", "proj", "T1", now - 7200000, now, "main")
    db.insert_message(conn, "t1", "t1:1", "t1:1:1", now - 7000000, "claude-sonnet-4-6", 10, 500, 0, 0)
    db.insert_message(conn, "t1", "t1:1", "t1:1:2", now - 6000000, "claude-sonnet-4-6", 10, 1000, 0, 0)
    db.insert_message(conn, "t1", "t1:1", "t1:1:3", now - 5000000, "claude-sonnet-4-6", 10, 2000, 0, 0)
    db.insert_tool_use(conn, "t1", "t1:1:1", now - 7000000, "skill", "brainstorming", 500)
    db.insert_tool_use(conn, "t1", "t1:1:2", now - 6000000, "skill", "brainstorming", 1000)
    db.insert_tool_use(conn, "t1", "t1:1:3", now - 5000000, "skill", "brainstorming", 2000)
    db.insert_tool_use(conn, "t1", "t1:1:1", now - 7000000, "mcp", "playwright", 500)
    return conn


@pytest.fixture
def tools_server(tools_seeded_conn, tmp_path):
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<html><body>dashboard</body></html>")
    (dashboard_dir / "style.css").write_text("body{}")
    (dashboard_dir / "app.js").write_text("// ok")
    config_path = tmp_path / "config.json"
    config_path.write_text('{"task_gap_minutes": 30}')
    port = start_server(tools_seeded_conn, config_path, dashboard_dir)
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/", timeout=0.2) as r:
                r.read()
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.01)
    else:
        raise RuntimeError("server did not start within 2s")
    yield base


def test_tools_endpoint_empty(server):
    data = _get(server + "/api/tools?range=7d")
    assert "skills" in data
    assert "mcp" in data
    assert data["skills"] == []
    assert data["mcp"] == []


def test_tools_endpoint_with_data(tools_server):
    data = _get(tools_server + "/api/tools?range=all")
    assert len(data["skills"]) == 1
    skill = data["skills"][0]
    assert skill["name"] == "brainstorming"
    assert skill["calls"] == 3
    assert skill["p50_output_tokens"] == 1000   # sorted [500,1000,2000] → index 1
    assert skill["max_output_tokens"] == 2000
    assert len(data["mcp"]) == 1
    assert data["mcp"][0]["name"] == "playwright"
    assert data["mcp"][0]["calls"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test tests/test_server.py::test_tools_endpoint_empty tests/test_server.py::test_tools_endpoint_with_data
```

Expected: `urllib.error.HTTPError: HTTP Error 404` (route not registered)

- [ ] **Step 3: Add /api/tools route to server.py**

In `claudemon/server.py`, inside `do_GET`, add this branch after the `/api/usage` elif and before the final `else`:

```python
                elif parsed.path == "/api/tools":
                    self._json(db.query_tool_usage(conn, range_ts))
```

The full `do_GET` elif chain should now end:
```python
                elif parsed.path == "/api/usage":
                    self._json(_handle_usage())

                elif parsed.path == "/api/tools":
                    self._json(db.query_tool_usage(conn, range_ts))

                else:
                    self._json_error(404, "not found")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test tests/test_server.py::test_tools_endpoint_empty tests/test_server.py::test_tools_endpoint_with_data
```

Expected: 2 passed

- [ ] **Step 5: Run full suite**

```bash
just test
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add claudemon/server.py tests/test_server.py
git commit -m "feat: add /api/tools endpoint for skills and MCP usage"
```

---

### Task 5: CSS — collapsible styles + tool-row rules

**Files:**
- Modify: `claudemon/dashboard/style.css`

- [ ] **Step 1: Append new CSS rules**

Append to the end of `claudemon/dashboard/style.css`:

```css
/* ── Collapsible sections ──────────────────────────── */
.csec { margin-bottom: 6px; }
.csec-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  cursor: pointer;
  user-select: none;
}
.csec-hdr:hover { background: rgba(255,255,255,0.02); }
.csec-title {
  font-size: 12px;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: .08em;
}
.csec-chevron {
  font-size: 9px;
  color: #444;
  transition: transform 0.15s ease;
}
.csec.open .csec-chevron { transform: rotate(90deg); }
.csec-body { display: none; padding: 0 16px 12px; }
.csec.open .csec-body { display: block; }

/* ── Tool rows (skills / mcp lists) ───────────────── */
.tool-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.tool-name {
  font-size: 13px;
  color: #bbb;
  font-weight: 500;
  width: 88px;
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-bar-wrap {
  flex: 1;
  height: 3px;
  background: rgba(255,255,255,0.06);
  border-radius: 2px;
  overflow: hidden;
}
.tool-fill { height: 3px; border-radius: 2px; }
.tool-meta { font-size: 12px; color: #777; white-space: nowrap; }
.skill-fill { background: #4ade80; }
.mcp-fill   { background: #38bdf8; }
```

- [ ] **Step 2: Run lint**

```bash
just lint
```

Expected: clean (ruff doesn't lint CSS; if there's a CSS linter configured, verify it passes)

- [ ] **Step 3: Commit**

```bash
git add claudemon/dashboard/style.css
git commit -m "feat: add collapsible section and tool-row CSS"
```

---

### Task 6: HTML — collapsible wrappers + new sections

**Files:**
- Modify: `claudemon/dashboard/index.html`

- [ ] **Step 1: Replace the four collapsible sections**

Replace the four `<section>` tags after "Daily tokens" with `.csec` wrappers. The "Daily tokens" `<section class="chart-section">` is the FIRST chart section and stays unchanged.

**Replace the "Recent sessions" section** (currently `<section>` with `<div class="sec-title" ...>Recent sessions</div>`):

Old:
```html
<section>
  <div class="sec-title" style="margin-bottom:4px">Recent sessions</div>
  <div id="sessions-list"></div>
</section>
```

New:
```html
<div class="csec">
  <div class="csec-hdr">
    <span class="csec-title">Recent sessions</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div id="sessions-list"></div>
  </div>
</div>
```

**Replace the "Tasks & queries" section** (currently `<section class="chart-section">` with task-chart):

Old:
```html
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
```

New:
```html
<div class="csec">
  <div class="csec-hdr">
    <span class="csec-title">Tasks &amp; queries</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div class="legend" style="margin-bottom:4px">
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
    <div class="axis-labels"><div class="axis-lbl">← queries</div><div class="axis-lbl">tok/task →</div></div>
    <div class="chart-wrap tall"><canvas id="task-chart"></canvas></div>
  </div>
</div>
```

**Replace the "Queries by token volume" section** (currently `<section class="chart-section">` with query-chart):

Old:
```html
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
```

New:
```html
<div class="csec">
  <div class="csec-hdr">
    <span class="csec-title">Queries by token volume</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div class="legend" style="margin-bottom:4px">
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
    <div class="axis-labels"><div class="axis-lbl">← tokens</div><div class="axis-lbl">tok/query →</div></div>
    <div class="chart-wrap tall"><canvas id="query-chart"></canvas></div>
  </div>
</div>
```

**Replace the "Model breakdown" section** (currently `<section>` with `models-list`):

Old:
```html
<section>
  <div class="sec-title" style="margin-bottom:6px">Model breakdown</div>
  <div id="models-list"></div>
</section>
```

New:
```html
<div class="csec">
  <div class="csec-hdr">
    <span class="csec-title">Model breakdown</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div id="models-list"></div>
  </div>
</div>
```

- [ ] **Step 2: Add the two new sections after model breakdown (before `<footer>`)**

Insert the following immediately after the model breakdown `.csec` div and before `<footer>`:

```html
<div class="csec">
  <div class="csec-hdr">
    <span class="csec-title">Skills used</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div id="skills-list"></div>
  </div>
</div>

<div class="csec">
  <div class="csec-hdr">
    <span class="csec-title">MCP tools</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div id="mcp-list"></div>
  </div>
</div>
```

- [ ] **Step 3: Run lint**

```bash
just lint
```

Expected: clean

- [ ] **Step 4: Commit**

```bash
git add claudemon/dashboard/index.html
git commit -m "feat: wrap dashboard sections in collapsible divs, add skills/mcp sections"
```

---

### Task 7: JS — initCollapsibles + renderSkills + renderMcp + api.tools

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Add api.tools to the api object**

In `claudemon/dashboard/app.js`, find the `api` object (around line 182). It currently ends with:

```javascript
  config()        { return api.get(`/api/config`); },
```

Add one line after it:

```javascript
  tools(range)    { return api.get(`/api/tools?range=${range}`); },
```

- [ ] **Step 2: Add initCollapsibles function**

Add this function anywhere before `document.addEventListener('DOMContentLoaded', ...)`. Placing it after `renderFooter` (around line 584) works well:

```javascript
function initCollapsibles() {
  document.querySelectorAll('.csec-hdr').forEach(hdr => {
    hdr.addEventListener('click', () => hdr.closest('.csec').classList.toggle('open'));
  });
}
```

- [ ] **Step 3: Add renderSkills and renderMcp functions**

Add these two functions immediately after `initCollapsibles`:

```javascript
function renderSkills(skills) {
  const el = document.getElementById('skills-list');
  if (!skills.length) {
    el.innerHTML = '<div style="color:#444;font-size:11px;padding:4px 0">No skill usage in this range</div>';
    return;
  }
  const maxCalls = skills[0].calls;
  el.innerHTML = skills.map(s => {
    const pct = Math.round(s.calls / maxCalls * 100);
    return `<div class="tool-row">
      <div class="tool-name" title="${esc(s.name)}">${esc(s.name)}</div>
      <div class="tool-bar-wrap"><div class="tool-fill skill-fill" style="width:${pct}%"></div></div>
      <div class="tool-meta">×${s.calls} · ${fmt(s.p50_output_tokens)} 50% / ${fmt(s.max_output_tokens)} max</div>
    </div>`;
  }).join('');
}

function renderMcp(mcp) {
  const el = document.getElementById('mcp-list');
  if (!mcp.length) {
    el.innerHTML = '<div style="color:#444;font-size:11px;padding:4px 0">No MCP usage in this range</div>';
    return;
  }
  const maxCalls = mcp[0].calls;
  el.innerHTML = mcp.map(m => {
    const pct = Math.round(m.calls / maxCalls * 100);
    return `<div class="tool-row">
      <div class="tool-name" title="${esc(m.name)}">${esc(m.name)}</div>
      <div class="tool-bar-wrap"><div class="tool-fill mcp-fill" style="width:${pct}%"></div></div>
      <div class="tool-meta">×${m.calls} · ${fmt(m.p50_output_tokens)} 50% / ${fmt(m.max_output_tokens)} max</div>
    </div>`;
  }).join('');
}
```

- [ ] **Step 4: Extend refresh() to fetch and render tools**

Find the `refresh()` function. It currently has:

```javascript
async function refresh() {
  const [stats, timeline, tasks, queriesData, sessions, config] = await Promise.all([
    api.stats(currentRange),
    api.timeline(currentRange),
    api.tasks(currentRange),
    api.queries(currentRange),
    api.sessions(currentRange),
    api.config(),
  ]);
  ...
  renderModels(stats);
  renderSessions(sessions);
  renderFooter(stats, config);
}
```

Change it to:

```javascript
async function refresh() {
  const [stats, timeline, tasks, queriesData, sessions, config, tools] = await Promise.all([
    api.stats(currentRange),
    api.timeline(currentRange),
    api.tasks(currentRange),
    api.queries(currentRange),
    api.sessions(currentRange),
    api.config(),
    api.tools(currentRange),
  ]);
  ...
  renderModels(stats);
  renderSessions(sessions);
  renderFooter(stats, config);
  renderSkills(tools.skills);
  renderMcp(tools.mcp);
}
```

(The `...` represents the existing lines between destructuring and the render calls — leave those unchanged.)

- [ ] **Step 5: Wire initCollapsibles into DOMContentLoaded**

Find the `DOMContentLoaded` handler. It currently starts:

```javascript
document.addEventListener('DOMContentLoaded', () => {
  _usageStripHTML = document.getElementById('usage-strip').innerHTML;
  initCharts();
  refresh();
```

Add `initCollapsibles()` after `initCharts()`:

```javascript
document.addEventListener('DOMContentLoaded', () => {
  _usageStripHTML = document.getElementById('usage-strip').innerHTML;
  initCharts();
  initCollapsibles();
  refresh();
```

- [ ] **Step 6: Run lint**

```bash
just lint
```

Expected: clean

- [ ] **Step 7: Run full test suite**

```bash
just test
```

Expected: all pass

- [ ] **Step 8: Run coverage check**

```bash
just coverage
```

Expected: ≥ 80% on covered modules

- [ ] **Step 9: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat: collapsible sections and skills/MCP usage panels in dashboard"
```

---

## Self-Review

After all tasks are committed, verify:

- [ ] `just test` — all pass
- [ ] `just coverage` — ≥ 80%
- [ ] `just lint` — clean
- [ ] Open the dashboard and confirm: all sections after "Daily tokens" start collapsed; clicking a header expands/collapses it; "Skills used" and "MCP tools" sections appear and show data (or "No usage in this range" if the indexed history has none)
