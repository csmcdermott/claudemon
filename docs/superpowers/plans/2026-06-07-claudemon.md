# claudemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS menu bar app that monitors Claude Code usage in real time by parsing local JSONL session files.

**Architecture:** A Python `rumps` app with a PyObjC `NSPopover` containing a `WKWebView` that renders a Chart.js dashboard served by a local `http.server` thread. A `watchdog` observer watches `~/.claude/projects/**/*.jsonl` for changes, triggering incremental JSONL parsing into a SQLite index. Task and query boundaries are detected heuristically from timestamps, git branch changes, and `/clear` commands.

**Tech Stack:** Python 3.11+, rumps, watchdog, pyobjc-framework-WebKit, sqlite3 (stdlib), http.server (stdlib), Chart.js (CDN)

---

## File Map

```
claudemon/
├── claudemon/
│   ├── __init__.py          # package marker
│   ├── app.py               # rumps.App entry point; wires all components
│   ├── db.py                # SQLite schema + all query functions
│   ├── indexer.py           # JSONL parser; assigns task_id/query_id; writes to DB
│   ├── watcher.py           # watchdog Observer; dispatches to indexer + statusitem
│   ├── server.py            # http.server thread; /api/* JSON endpoints
│   ├── statusitem.py        # menu bar icon, token count, state dot (macOS only)
│   ├── popover.py           # NSPopover + WKWebView (macOS only)
│   └── dashboard/
│       ├── index.html       # panel markup
│       ├── app.js           # fetch + Chart.js rendering
│       └── style.css        # dark theme styles
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # shared fixtures (in-memory DB, fixture JSONL path)
│   ├── fixtures/
│   │   └── sample_session.jsonl
│   ├── test_db.py
│   ├── test_indexer.py
│   └── test_server.py
├── scripts/
│   └── pre-push.sh
├── docs/
│   ├── agent/
│   └── superpowers/
├── CLAUDE.md
├── justfile
└── pyproject.toml
```

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `justfile`
- Create: `scripts/pre-push.sh`
- Create: `claudemon/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/` (directory)

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "claudemon"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "rumps>=0.4.0",
    "watchdog>=4.0.0",
    "pyobjc-framework-WebKit>=10.0",
]

[project.scripts]
claudemon = "claudemon.app:main"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "ruff>=0.4.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I"]
```

- [ ] **Step 2: Create `justfile`**

```makefile
lint:
    ruff check claudemon/ tests/

test:
    pytest tests/ -v

coverage:
    pytest tests/ --cov=claudemon --cov-report=term-missing --cov-fail-under=80

install-pre-push:
    cp scripts/pre-push.sh .git/hooks/pre-push
    chmod +x .git/hooks/pre-push
```

- [ ] **Step 3: Create `scripts/pre-push.sh`**

```bash
#!/usr/bin/env bash
set -e
echo "Running lint..."
ruff check claudemon/ tests/
echo "Running tests with coverage..."
pytest tests/ --cov=claudemon --cov-report=term-missing --cov-fail-under=80
echo "Pre-push checks passed."
```

- [ ] **Step 4: Create package markers and install dev dependencies**

```bash
touch claudemon/__init__.py tests/__init__.py
mkdir -p tests/fixtures
pip install -e ".[dev]"
```

Expected: installs rumps, watchdog, pyobjc-framework-WebKit, pytest, pytest-cov, ruff.

- [ ] **Step 5: Verify tooling works**

```bash
just lint   # should pass (no source files yet)
just test   # should pass (no tests yet)
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml justfile scripts/ claudemon/__init__.py tests/__init__.py tests/fixtures/
git commit -m "feat: project scaffolding"
```

---

## Task 2: SQLite schema and query layer (`db.py`)

**Files:**
- Create: `claudemon/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Create `tests/conftest.py` with in-memory DB fixture**

```python
import pytest
import sqlite3
from pathlib import Path
import claudemon.db as db


@pytest.fixture
def conn():
    """In-memory SQLite connection with schema applied."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    yield c
    c.close()


FIXTURES_DIR = Path(__file__).parent / "fixtures"
```

- [ ] **Step 2: Write failing tests in `tests/test_db.py`**

```python
import time
import pytest
from tests.conftest import FIXTURES_DIR
import claudemon.db as db


def test_schema_creates_tables(conn):
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert tables >= {"sessions", "messages", "file_cursors"}


def test_upsert_session_insert(conn):
    db.upsert_session(conn, "s1", "myproject", None, 1000, 2000, "main")
    row = conn.execute("SELECT * FROM sessions WHERE session_id='s1'").fetchone()
    assert row["project"] == "myproject"
    assert row["started_at"] == 1000
    assert row["ended_at"] == 2000


def test_upsert_session_updates_ended_at(conn):
    db.upsert_session(conn, "s1", "myproject", None, 1000, 2000, "main")
    db.upsert_session(conn, "s1", "myproject", "My title", 1000, 3000, "main")
    row = conn.execute("SELECT * FROM sessions WHERE session_id='s1'").fetchone()
    assert row["ended_at"] == 3000
    assert row["title"] == "My title"


def test_insert_message(conn):
    db.upsert_session(conn, "s1", "proj", None, 1000, 1000, "main")
    db.insert_message(conn, "s1", "s1:1", "s1:1:1", 1000, "claude-sonnet-4-6", 10, 50, 500, 200)
    rows = conn.execute("SELECT * FROM messages WHERE session_id='s1'").fetchall()
    assert len(rows) == 1
    assert rows[0]["output_tokens"] == 50
    assert rows[0]["task_id"] == "s1:1"
    assert rows[0]["query_id"] == "s1:1:1"


def test_get_and_update_cursor(conn):
    assert db.get_cursor(conn, "/path/file.jsonl") is None
    db.update_cursor(conn, "/path/file.jsonl", 1024, 1.5, 2, 3, "main", 99000)
    c = db.get_cursor(conn, "/path/file.jsonl")
    assert c["last_offset"] == 1024
    assert c["last_task_num"] == 2
    assert c["last_query_num"] == 3
    assert c["last_branch"] == "main"
    assert c["last_timestamp"] == 99000


def test_query_stats_empty(conn):
    result = db.query_stats(conn, (0, int(time.time() * 1000)))
    assert result["sessions"] == 0
    assert result["output_tokens"] == 0
    assert result["cache_hit_rate"] == 0.0


def test_query_stats_with_data(conn):
    db.upsert_session(conn, "s1", "proj", "T", 1000, 2000, "main")
    db.insert_message(conn, "s1", "s1:1", "s1:1:1", 1500, "claude-sonnet-4-6", 10, 50, 500, 200)
    db.insert_message(conn, "s1", "s1:1", "s1:1:2", 1600, "claude-sonnet-4-6", 15, 60, 0, 700)
    db.insert_message(conn, "s1", "s1:2", "s1:2:1", 1700, "claude-sonnet-4-6", 20, 80, 800, 0)
    result = db.query_stats(conn, (0, int(time.time() * 1000)))
    assert result["sessions"] == 1
    assert result["tasks"] == 2
    assert result["queries"] == 3
    assert result["input_tokens"] == 45
    assert result["output_tokens"] == 190
    # cache_hit_rate = 900 / (45 + 900 + 1300) = 40.1%
    assert abs(result["cache_hit_rate"] - 40.1) < 0.5


def test_query_timeline_buckets(conn):
    db.upsert_session(conn, "s1", "proj", None, 1000, 2000, "main")
    # Two messages on different days
    day1 = 1748736000000  # 2025-06-01 00:00:00 UTC in ms
    day2 = day1 + 86400000  # 2025-06-02
    db.insert_message(conn, "s1", "s1:1", "s1:1:1", day1 + 1000, "claude-sonnet-4-6", 10, 50, 0, 0)
    db.insert_message(conn, "s1", "s1:1", "s1:1:2", day2 + 1000, "claude-sonnet-4-6", 20, 80, 0, 0)
    buckets = db.query_timeline(conn, (day1, day2 + 86400000), "1d")
    assert len(buckets) >= 2
    totals = {b["date"]: b["output_tokens"] for b in buckets}
    assert any(v == 50 for v in totals.values())
    assert any(v == 80 for v in totals.values())


def test_query_sessions_returns_aggregates(conn):
    db.upsert_session(conn, "s1", "proj", "Title A", 1000, 5000, "main")
    db.insert_message(conn, "s1", "s1:1", "s1:1:1", 1500, "claude-sonnet-4-6", 10, 50, 0, 0)
    db.insert_message(conn, "s1", "s1:1", "s1:1:2", 2000, "claude-sonnet-4-6", 10, 60, 0, 0)
    rows = db.query_sessions(conn, (0, int(time.time() * 1000)), limit=5)
    assert len(rows) == 1
    assert rows[0]["title"] == "Title A"
    assert rows[0]["output_tokens"] == 110
    assert rows[0]["task_count"] == 1
    assert rows[0]["query_count"] == 2
```

- [ ] **Step 3: Run tests to verify they all fail**

```bash
just test
```

Expected: all test_db tests fail with `ModuleNotFoundError: No module named 'claudemon.db'`

- [ ] **Step 4: Implement `claudemon/db.py`**

```python
import sqlite3
import time
from pathlib import Path

DB_PATH = Path.home() / ".claudemon" / "claudemon.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    project      TEXT,
    title        TEXT,
    started_at   INTEGER,
    ended_at     INTEGER,
    git_branch   TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id             TEXT REFERENCES sessions(session_id),
    task_id                TEXT,
    query_id               TEXT,
    timestamp              INTEGER,
    model                  TEXT,
    input_tokens           INTEGER DEFAULT 0,
    output_tokens          INTEGER DEFAULT 0,
    cache_creation_tokens  INTEGER DEFAULT 0,
    cache_read_tokens      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS file_cursors (
    file_path       TEXT PRIMARY KEY,
    last_offset     INTEGER DEFAULT 0,
    last_modified   REAL DEFAULT 0,
    last_task_num   INTEGER DEFAULT 0,
    last_query_num  INTEGER DEFAULT 0,
    last_branch     TEXT,
    last_timestamp  INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_messages_ts      ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_task    ON messages(task_id);
CREATE INDEX IF NOT EXISTS idx_messages_query   ON messages(query_id);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def upsert_session(
    conn: sqlite3.Connection,
    session_id: str,
    project: str,
    title: str | None,
    started_at: int,
    ended_at: int,
    git_branch: str | None,
) -> None:
    conn.execute("""
        INSERT INTO sessions (session_id, project, title, started_at, ended_at, git_branch)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            title     = COALESCE(excluded.title, title),
            ended_at  = MAX(ended_at, excluded.ended_at)
    """, (session_id, project, title, started_at, ended_at, git_branch))
    conn.commit()


def insert_message(
    conn: sqlite3.Connection,
    session_id: str,
    task_id: str,
    query_id: str,
    timestamp: int,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int,
    cache_read_tokens: int,
) -> None:
    conn.execute("""
        INSERT INTO messages
            (session_id, task_id, query_id, timestamp, model,
             input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (session_id, task_id, query_id, timestamp, model,
          input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens))
    conn.commit()


def get_cursor(conn: sqlite3.Connection, file_path: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM file_cursors WHERE file_path = ?", (file_path,)
    ).fetchone()


def update_cursor(
    conn: sqlite3.Connection,
    file_path: str,
    last_offset: int,
    last_modified: float,
    last_task_num: int,
    last_query_num: int,
    last_branch: str | None,
    last_timestamp: int,
) -> None:
    conn.execute("""
        INSERT INTO file_cursors
            (file_path, last_offset, last_modified, last_task_num,
             last_query_num, last_branch, last_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            last_offset    = excluded.last_offset,
            last_modified  = excluded.last_modified,
            last_task_num  = excluded.last_task_num,
            last_query_num = excluded.last_query_num,
            last_branch    = excluded.last_branch,
            last_timestamp = excluded.last_timestamp
    """, (file_path, last_offset, last_modified, last_task_num,
          last_query_num, last_branch, last_timestamp))
    conn.commit()


def _range_condition(start_ms: int, end_ms: int) -> tuple[str, tuple]:
    return "timestamp BETWEEN ? AND ?", (start_ms, end_ms)


def query_stats(conn: sqlite3.Connection, range_ts: tuple[int, int]) -> dict:
    start_ms, end_ms = range_ts
    row = conn.execute("""
        SELECT
            COUNT(DISTINCT session_id)             AS sessions,
            COUNT(DISTINCT task_id)                AS tasks,
            COUNT(DISTINCT query_id)               AS queries,
            COALESCE(SUM(input_tokens), 0)         AS input_tokens,
            COALESCE(SUM(output_tokens), 0)        AS output_tokens,
            COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation,
            COALESCE(SUM(cache_read_tokens), 0)    AS cache_read
        FROM messages
        WHERE timestamp BETWEEN ? AND ?
    """, (start_ms, end_ms)).fetchone()

    total_input_all = row["input_tokens"] + row["cache_read"] + row["cache_creation"]
    cache_hit_rate = (row["cache_read"] / total_input_all * 100) if total_input_all > 0 else 0.0

    tasks = max(row["tasks"], 1)
    queries = max(row["queries"], 1)
    total_tokens = row["input_tokens"] + row["output_tokens"]

    models = conn.execute("""
        SELECT model,
               COALESCE(SUM(input_tokens), 0)  AS input_tokens,
               COALESCE(SUM(output_tokens), 0) AS output_tokens,
               COUNT(*)                         AS messages
        FROM messages
        WHERE timestamp BETWEEN ? AND ?
        GROUP BY model
        ORDER BY messages DESC
    """, (start_ms, end_ms)).fetchall()

    return {
        "sessions": row["sessions"],
        "tasks": row["tasks"],
        "queries": row["queries"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "cache_hit_rate": round(cache_hit_rate, 1),
        "tokens_per_query": round(total_tokens / queries),
        "tokens_per_task": round(total_tokens / tasks),
        "model_breakdown": [
            {
                "model": m["model"],
                "input_tokens": m["input_tokens"],
                "output_tokens": m["output_tokens"],
                "messages": m["messages"],
            }
            for m in models
        ],
    }


def query_timeline(
    conn: sqlite3.Connection, range_ts: tuple[int, int], bucket: str = "1d"
) -> list[dict]:
    """Return per-bucket token totals and cache hit rate.

    bucket: '1h' or '1d'
    Returned dicts: {date, input_tokens, output_tokens, cache_hit_rate}
    """
    start_ms, end_ms = range_ts
    # SQLite: group by truncated timestamp
    if bucket == "1h":
        trunc = "(timestamp / 3600000) * 3600000"
    else:
        trunc = "(timestamp / 86400000) * 86400000"

    rows = conn.execute(f"""
        SELECT
            {trunc}                                        AS bucket_ts,
            COALESCE(SUM(input_tokens), 0)                AS input_tokens,
            COALESCE(SUM(output_tokens), 0)               AS output_tokens,
            COALESCE(SUM(cache_creation_tokens), 0)       AS cache_creation,
            COALESCE(SUM(cache_read_tokens), 0)           AS cache_read
        FROM messages
        WHERE timestamp BETWEEN ? AND ?
        GROUP BY bucket_ts
        ORDER BY bucket_ts
    """, (start_ms, end_ms)).fetchall()

    result = []
    for r in rows:
        total = r["input_tokens"] + r["cache_read"] + r["cache_creation"]
        hit_rate = (r["cache_read"] / total * 100) if total > 0 else 0.0
        result.append({
            "date": r["bucket_ts"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cache_hit_rate": round(hit_rate, 1),
        })
    return result


def query_tasks(conn: sqlite3.Connection, range_ts: tuple[int, int]) -> list[dict]:
    """Return per-day task breakdown for stacked chart.

    Each entry: {date, tasks: [{task_id, queries, input_tokens, output_tokens}],
                 avg_tokens_per_task}
    """
    start_ms, end_ms = range_ts
    rows = conn.execute("""
        SELECT
            (timestamp / 86400000) * 86400000             AS day_ts,
            task_id,
            COUNT(DISTINCT query_id)                       AS queries,
            COALESCE(SUM(input_tokens), 0)                AS input_tokens,
            COALESCE(SUM(output_tokens), 0)               AS output_tokens
        FROM messages
        WHERE timestamp BETWEEN ? AND ?
        GROUP BY day_ts, task_id
        ORDER BY day_ts, task_id
    """, (start_ms, end_ms)).fetchall()

    days: dict[int, dict] = {}
    for r in rows:
        day = r["day_ts"]
        if day not in days:
            days[day] = {"date": day, "tasks": [], "total_tokens": 0}
        tok = r["input_tokens"] + r["output_tokens"]
        days[day]["tasks"].append({
            "task_id": r["task_id"],
            "queries": r["queries"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
        })
        days[day]["total_tokens"] += tok

    result = []
    for day_ts in sorted(days):
        d = days[day_ts]
        n_tasks = max(len(d["tasks"]), 1)
        result.append({
            "date": day_ts,
            "tasks": d["tasks"],
            "avg_tokens_per_task": round(d["total_tokens"] / n_tasks),
        })
    return result


def query_sessions(
    conn: sqlite3.Connection,
    range_ts: tuple[int, int],
    limit: int = 5,
    active_only: bool = False,
) -> list[dict]:
    start_ms, end_ms = range_ts
    extra = "AND s.ended_at >= ? " if active_only else ""
    extra_params = (int(__import__("time").time() * 1000) - 60000,) if active_only else ()

    rows = conn.execute(f"""
        SELECT
            s.session_id, s.project, s.title,
            s.started_at, s.ended_at, s.git_branch,
            COALESCE(SUM(m.input_tokens), 0)   AS input_tokens,
            COALESCE(SUM(m.output_tokens), 0)  AS output_tokens,
            COUNT(DISTINCT m.task_id)           AS task_count,
            COUNT(DISTINCT m.query_id)          AS query_count
        FROM sessions s
        LEFT JOIN messages m
            ON m.session_id = s.session_id AND m.timestamp BETWEEN ? AND ?
        WHERE s.started_at <= ? {extra}
        GROUP BY s.session_id
        ORDER BY s.started_at DESC
        LIMIT ?
    """, (start_ms, end_ms, end_ms) + extra_params + (limit,)).fetchall()

    return [dict(r) for r in rows]


def query_today_output_tokens(conn: sqlite3.Connection) -> int:
    import time
    from datetime import datetime, timezone
    today_start = int(
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp() * 1000
    )
    now = int(time.time() * 1000)
    row = conn.execute(
        "SELECT COALESCE(SUM(output_tokens), 0) AS total FROM messages WHERE timestamp BETWEEN ? AND ?",
        (today_start, now),
    ).fetchone()
    return row["total"]
```

- [ ] **Step 5: Run tests**

```bash
just test tests/test_db.py
```

Expected: all 9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add claudemon/db.py tests/test_db.py tests/conftest.py
git commit -m "feat: SQLite schema and query layer"
```

---

## Task 3: JSONL indexer (`indexer.py`)

**Files:**
- Create: `claudemon/indexer.py`
- Create: `tests/fixtures/sample_session.jsonl`
- Create: `tests/test_indexer.py`

- [ ] **Step 1: Create `tests/fixtures/sample_session.jsonl`**

Write exactly these 7 lines (one JSON object per line, no blank lines):

```
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Hello"}]},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"abc123","uuid":"u1","parentUuid":null,"userType":"external","entrypoint":"cli","cwd":"/Users/test/test-project","gitBranch":"main","isSidechain":false,"isMeta":false,"permissionMode":"default","version":"2.1.0"}
{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":10,"cache_creation_input_tokens":500,"cache_read_input_tokens":200,"output_tokens":50},"stop_reason":"end_turn","content":[{"type":"text","text":"Hello back"}]},"timestamp":"2026-06-01T10:00:05.000Z","sessionId":"abc123","uuid":"a1","parentUuid":"u1","userType":"external","entrypoint":"cli","cwd":"/Users/test/test-project","gitBranch":"main","isSidechain":false,"version":"2.1.0"}
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Continue"}]},"timestamp":"2026-06-01T10:01:00.000Z","sessionId":"abc123","uuid":"u2","parentUuid":"a1","userType":"external","entrypoint":"cli","cwd":"/Users/test/test-project","gitBranch":"main","isSidechain":false,"isMeta":false,"permissionMode":"default","version":"2.1.0"}
{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":15,"cache_creation_input_tokens":0,"cache_read_input_tokens":700,"output_tokens":60},"stop_reason":"end_turn","content":[{"type":"text","text":"Continued"}]},"timestamp":"2026-06-01T10:01:05.000Z","sessionId":"abc123","uuid":"a2","parentUuid":"u2","userType":"external","entrypoint":"cli","cwd":"/Users/test/test-project","gitBranch":"main","isSidechain":false,"version":"2.1.0"}
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"New task query"}]},"timestamp":"2026-06-01T10:46:00.000Z","sessionId":"abc123","uuid":"u3","parentUuid":"a2","userType":"external","entrypoint":"cli","cwd":"/Users/test/test-project","gitBranch":"main","isSidechain":false,"isMeta":false,"permissionMode":"default","version":"2.1.0"}
{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":20,"cache_creation_input_tokens":800,"cache_read_input_tokens":0,"output_tokens":80},"stop_reason":"end_turn","content":[{"type":"text","text":"New task response"}]},"timestamp":"2026-06-01T10:46:05.000Z","sessionId":"abc123","uuid":"a3","parentUuid":"u3","userType":"external","entrypoint":"cli","cwd":"/Users/test/test-project","gitBranch":"main","isSidechain":false,"version":"2.1.0"}
{"type":"ai-title","aiTitle":"Test session for indexing","sessionId":"abc123"}
```

Expected data after indexing:
- 3 assistant messages
- task "abc123:1" has 2 queries (gap between query 1 and 2 is 55s < 30min)
- task "abc123:2" has 1 query (gap between query 2 and 3 is 45 min > 30min threshold)

- [ ] **Step 2: Write failing tests in `tests/test_indexer.py`**

```python
import pytest
from pathlib import Path
from tests.conftest import FIXTURES_DIR
import claudemon.db as db
import claudemon.indexer as indexer


FIXTURE_JSONL = FIXTURES_DIR / "sample_session.jsonl"


def test_index_file_creates_session(conn):
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    row = conn.execute("SELECT * FROM sessions WHERE session_id='abc123'").fetchone()
    assert row is not None
    assert row["project"] == "test-project"
    assert row["title"] == "Test session for indexing"


def test_index_file_inserts_messages(conn):
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    rows = conn.execute("SELECT * FROM messages WHERE session_id='abc123' ORDER BY timestamp").fetchall()
    assert len(rows) == 3
    assert rows[0]["output_tokens"] == 50
    assert rows[1]["output_tokens"] == 60
    assert rows[2]["output_tokens"] == 80


def test_index_file_token_totals(conn):
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    row = conn.execute("""
        SELECT SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_creation_tokens) as cc, SUM(cache_read_tokens) as cr
        FROM messages WHERE session_id='abc123'
    """).fetchone()
    assert row["inp"] == 45
    assert row["out"] == 190
    assert row["cc"] == 1300
    assert row["cr"] == 900


def test_index_file_task_boundaries(conn):
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    tasks = {r[0] for r in conn.execute(
        "SELECT DISTINCT task_id FROM messages WHERE session_id='abc123'"
    ).fetchall()}
    assert len(tasks) == 2


def test_index_file_query_boundaries(conn):
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    queries = {r[0] for r in conn.execute(
        "SELECT DISTINCT query_id FROM messages WHERE session_id='abc123'"
    ).fetchall()}
    assert len(queries) == 3


def test_index_file_same_task_for_first_two_queries(conn):
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    rows = conn.execute(
        "SELECT task_id, query_id FROM messages WHERE session_id='abc123' ORDER BY timestamp"
    ).fetchall()
    # First two queries share the same task
    assert rows[0]["task_id"] == rows[1]["task_id"]
    # Third query is a different task (45min gap)
    assert rows[2]["task_id"] != rows[0]["task_id"]


def test_index_file_is_idempotent(conn):
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id='abc123'"
    ).fetchone()[0]
    assert count == 3  # not 6


def test_index_file_updates_cursor(conn):
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    cursor = db.get_cursor(conn, str(FIXTURE_JSONL))
    assert cursor is not None
    assert cursor["last_offset"] == FIXTURE_JSONL.stat().st_size
    assert cursor["last_task_num"] == 2
    assert cursor["last_query_num"] == 1  # query_num resets per task


def test_task_boundary_on_branch_change(conn, tmp_path):
    jsonl = tmp_path / "branch_test.jsonl"
    jsonl.write_text(
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"q1"}]},'
        '"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"b1","uuid":"u1",'
        '"parentUuid":null,"cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":10},"stop_reason":"end_turn","content":[]},'
        '"timestamp":"2026-06-01T10:00:05.000Z","sessionId":"b1","uuid":"a1",'
        '"parentUuid":"u1","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"q2"}]},'
        '"timestamp":"2026-06-01T10:01:00.000Z","sessionId":"b1","uuid":"u2",'
        '"parentUuid":"a1","cwd":"/p","gitBranch":"feature","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":10},"stop_reason":"end_turn","content":[]},'
        '"timestamp":"2026-06-01T10:01:05.000Z","sessionId":"b1","uuid":"a2",'
        '"parentUuid":"u2","cwd":"/p","gitBranch":"feature","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
    )
    indexer.index_file(conn, jsonl, task_gap_minutes=30)
    tasks = {r[0] for r in conn.execute(
        "SELECT DISTINCT task_id FROM messages WHERE session_id='b1'"
    ).fetchall()}
    assert len(tasks) == 2  # branch change triggered new task despite <30min gap


def test_task_boundary_on_clear_command(conn, tmp_path):
    jsonl = tmp_path / "clear_test.jsonl"
    jsonl.write_text(
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"hello"}]},'
        '"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"c1","uuid":"u1",'
        '"parentUuid":null,"cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":10},"stop_reason":"end_turn","content":[]},'
        '"timestamp":"2026-06-01T10:00:05.000Z","sessionId":"c1","uuid":"a1",'
        '"parentUuid":"u1","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"/clear"}]},'
        '"timestamp":"2026-06-01T10:01:00.000Z","sessionId":"c1","uuid":"u2",'
        '"parentUuid":"a1","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":10},"stop_reason":"end_turn","content":[]},'
        '"timestamp":"2026-06-01T10:01:05.000Z","sessionId":"c1","uuid":"a2",'
        '"parentUuid":"u2","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
    )
    indexer.index_file(conn, jsonl, task_gap_minutes=30)
    tasks = {r[0] for r in conn.execute(
        "SELECT DISTINCT task_id FROM messages WHERE session_id='c1'"
    ).fetchall()}
    assert len(tasks) == 2  # /clear triggered new task


def test_tool_use_result_not_a_new_query(conn, tmp_path):
    jsonl = tmp_path / "tool_test.jsonl"
    jsonl.write_text(
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"run tool"}]},'
        '"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"t1","uuid":"u1",'
        '"parentUuid":null,"cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":10},"stop_reason":"tool_use","content":[]},'
        '"timestamp":"2026-06-01T10:00:05.000Z","sessionId":"t1","uuid":"a1",'
        '"parentUuid":"u1","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"user","toolUseResult":"result","message":{"role":"user","content":[]},'
        '"timestamp":"2026-06-01T10:00:06.000Z","sessionId":"t1","uuid":"u2",'
        '"parentUuid":"a1","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":8,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":20},"stop_reason":"end_turn","content":[]},'
        '"timestamp":"2026-06-01T10:00:08.000Z","sessionId":"t1","uuid":"a2",'
        '"parentUuid":"u2","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
    )
    indexer.index_file(conn, jsonl, task_gap_minutes=30)
    queries = {r[0] for r in conn.execute(
        "SELECT DISTINCT query_id FROM messages WHERE session_id='t1'"
    ).fetchall()}
    assert len(queries) == 1  # tool_use result is not a new query; both assistant msgs share query
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
just test tests/test_indexer.py
```

Expected: all fail with `ModuleNotFoundError: No module named 'claudemon.indexer'`

- [ ] **Step 4: Implement `claudemon/indexer.py`**

```python
import json
import os
from pathlib import Path

import claudemon.db as db


def _parse_timestamp(ts_str: str) -> int:
    """Convert ISO 8601 string to unix milliseconds."""
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def _is_new_query(record: dict) -> bool:
    """True if this user record starts a new query (not a tool result or meta)."""
    return (
        record.get("type") == "user"
        and not record.get("isMeta", False)
        and not record.get("toolUseResult")
        and record.get("isSidechain") is False
    )


def _is_clear_command(record: dict) -> bool:
    """True if this user record is a /clear command."""
    content = record.get("message", {}).get("content", [])
    if isinstance(content, list):
        text = "".join(
            c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"
        )
    elif isinstance(content, str):
        text = content
    else:
        return False
    return text.strip() == "/clear"


def _extract_content_text(record: dict) -> str:
    content = record.get("message", {}).get("content", [])
    if isinstance(content, list):
        return "".join(
            c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"
        )
    return str(content) if content else ""


def index_file(
    conn,
    file_path: Path,
    task_gap_minutes: int = 30,
) -> None:
    """Parse a JSONL session file and write new records to the DB.

    Uses byte-offset cursor for incremental parsing: only reads bytes
    appended since the last call.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return

    stat = os.stat(file_path)
    cursor = db.get_cursor(conn, str(file_path))

    if cursor and cursor["last_modified"] == stat.st_mtime:
        return  # file unchanged

    session_id = file_path.stem
    project = file_path.parent.name  # slug like "-Users-foo-bar-MyProject"

    # Restore incremental state from cursor
    last_offset = cursor["last_offset"] if cursor else 0
    task_num = cursor["last_task_num"] if cursor else 0
    query_num = cursor["last_query_num"] if cursor else 0
    last_branch = cursor["last_branch"] if cursor else None
    last_timestamp = cursor["last_timestamp"] if cursor else 0

    # If file shrank (shouldn't happen but be safe), reset
    if last_offset > stat.st_size:
        last_offset = 0
        task_num = 0
        query_num = 0
        last_branch = None
        last_timestamp = 0

    gap_ms = task_gap_minutes * 60 * 1000
    current_query_id: str | None = None
    session_project: str | None = None
    session_started_at: int | None = None
    pending_title: str | None = None

    # On first parse (no cursor), initialise task/query to 0 so first user msg increments to 1
    if task_num == 0:
        # Will be set to 1 on first query
        pass

    with open(file_path, "rb") as f:
        if last_offset > 0:
            f.seek(last_offset)

        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            rec_type = record.get("type")

            # Extract project from cwd on first record that has it
            if session_project is None and record.get("cwd"):
                session_project = Path(record["cwd"]).name or project

            # Track session timestamps
            ts_str = record.get("timestamp")
            ts = _parse_timestamp(ts_str) if ts_str else None
            if ts and session_started_at is None:
                session_started_at = ts

            if rec_type == "ai-title":
                pending_title = record.get("aiTitle")
                continue

            if rec_type == "user" and _is_new_query(record):
                branch = record.get("gitBranch")
                is_clear = _is_clear_command(record)

                # Determine if this user message is a task boundary
                is_new_task = (
                    task_num == 0  # first task
                    or is_clear
                    or (branch and last_branch and branch != last_branch)
                    or (ts and last_timestamp and (ts - last_timestamp) > gap_ms)
                )

                if is_new_task:
                    task_num += 1
                    query_num = 1
                else:
                    query_num += 1

                short_id = session_id[:6]
                current_query_id = f"{short_id}:{task_num}:{query_num}"

                last_branch = branch
                if ts:
                    last_timestamp = ts
                continue

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
                query_id = current_query_id or f"{short_id}:{task_num}:1"

                db.insert_message(
                    conn, session_id, task_id, query_id, ts, model,
                    input_tokens, output_tokens, cache_creation, cache_read,
                )

                if ts:
                    last_timestamp = ts

        new_offset = f.tell()

    # If title arrived after all assistant messages, update session
    if pending_title:
        db.upsert_session(
            conn, session_id, session_project or project, pending_title,
            session_started_at or 0, last_timestamp, last_branch,
        )

    db.update_cursor(
        conn, str(file_path), new_offset, stat.st_mtime,
        task_num, query_num, last_branch, last_timestamp,
    )


def index_all(conn, projects_dir: Path, task_gap_minutes: int = 30) -> None:
    """Index every JSONL file under projects_dir."""
    for jsonl_file in sorted(projects_dir.glob("**/*.jsonl")):
        index_file(conn, jsonl_file, task_gap_minutes=task_gap_minutes)
```

- [ ] **Step 5: Run tests**

```bash
just test tests/test_indexer.py
```

Expected: all 11 tests pass.

- [ ] **Step 6: Commit**

```bash
git add claudemon/indexer.py tests/fixtures/sample_session.jsonl tests/test_indexer.py
git commit -m "feat: JSONL indexer with task/query boundary detection"
```

---

## Task 4: File watcher (`watcher.py`)

**Files:**
- Create: `claudemon/watcher.py`

No unit tests for watcher (thin coordination layer; tested via integration). Manual smoke test instead.

- [ ] **Step 1: Implement `claudemon/watcher.py`**

```python
import logging
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class _JSONLHandler(FileSystemEventHandler):
    def __init__(self, on_jsonl_change: Callable[[Path], None]):
        self._on_jsonl_change = on_jsonl_change

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".jsonl"):
            self._on_jsonl_change(Path(event.src_path))

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".jsonl"):
            self._on_jsonl_change(Path(event.src_path))


class _SessionHandler(FileSystemEventHandler):
    def __init__(self, on_session_change: Callable[[], None]):
        self._on_session_change = on_session_change

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".json"):
            self._on_session_change()

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".json"):
            self._on_session_change()

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith(".json"):
            self._on_session_change()


class Watcher:
    """Watches Claude Code data directories and fires callbacks on changes."""

    def __init__(
        self,
        projects_dir: Path,
        sessions_dir: Path,
        on_jsonl_change: Callable[[Path], None],
        on_session_change: Callable[[], None],
    ):
        self._observer = Observer()
        self._observer.schedule(
            _JSONLHandler(on_jsonl_change),
            str(projects_dir),
            recursive=True,
        )
        self._observer.schedule(
            _SessionHandler(on_session_change),
            str(sessions_dir),
            recursive=False,
        )

    def start(self) -> None:
        self._observer.start()
        logger.info("File watcher started")

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
        logger.info("File watcher stopped")
```

- [ ] **Step 2: Commit**

```bash
git add claudemon/watcher.py
git commit -m "feat: file watcher for JSONL and session state changes"
```

---

## Task 5: HTTP server (`server.py`)

**Files:**
- Create: `claudemon/server.py`
- Create: `tests/test_server.py`

- [ ] **Step 1: Write failing tests in `tests/test_server.py`**

```python
import json
import time
import threading
import urllib.request
import pytest
import claudemon.db as db
from claudemon.server import start_server
from tests.conftest import FIXTURES_DIR


@pytest.fixture
def seeded_conn(conn):
    """DB with known data for server tests."""
    now = int(time.time() * 1000)
    day = (now // 86400000) * 86400000

    db.upsert_session(conn, "s1", "proj-a", "Session One", day - 3600000, day, "main")
    db.insert_message(conn, "s1", "s1:1", "s1:1:1", day - 3000000, "claude-sonnet-4-6",
                      10, 50, 500, 200)
    db.insert_message(conn, "s1", "s1:1", "s1:1:2", day - 2000000, "claude-sonnet-4-6",
                      15, 60, 0, 700)
    db.insert_message(conn, "s1", "s1:2", "s1:2:1", day - 1000000, "claude-haiku-4-5-20251001",
                      20, 80, 800, 0)
    return conn


@pytest.fixture
def server(seeded_conn, tmp_path):
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<html><body>dashboard</body></html>")
    config_path = tmp_path / "config.json"
    config_path.write_text('{"weekly_output_budget": 8000000, "task_gap_minutes": 30}')
    port = start_server(seeded_conn, config_path, dashboard_dir)
    time.sleep(0.1)  # allow server thread to bind
    yield f"http://127.0.0.1:{port}"


def _get(url: str) -> dict:
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def test_dashboard_html(server):
    with urllib.request.urlopen(server + "/") as r:
        assert b"dashboard" in r.read()


def test_stats_endpoint(server):
    data = _get(server + "/api/stats?range=all")
    assert data["sessions"] == 1
    assert data["tasks"] == 2
    assert data["queries"] == 3
    assert data["output_tokens"] == 190
    assert data["input_tokens"] == 45
    assert len(data["model_breakdown"]) == 2


def test_timeline_endpoint(server):
    data = _get(server + "/api/timeline?range=all&bucket=1d")
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "input_tokens" in data[0]
    assert "output_tokens" in data[0]
    assert "cache_hit_rate" in data[0]


def test_tasks_endpoint(server):
    data = _get(server + "/api/tasks?range=all")
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "tasks" in data[0]
    assert "avg_tokens_per_task" in data[0]


def test_sessions_endpoint(server):
    data = _get(server + "/api/sessions?range=all")
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["title"] == "Session One"
    assert data[0]["output_tokens"] == 190
    assert data[0]["task_count"] == 2
    assert data[0]["query_count"] == 3


def test_config_get(server):
    data = _get(server + "/api/config")
    assert data["weekly_output_budget"] == 8000000


def test_config_post(server):
    body = json.dumps({"weekly_output_budget": 5000000}).encode()
    req = urllib.request.Request(
        server + "/api/config",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
    assert result["weekly_output_budget"] == 5000000
    # Verify persisted
    data = _get(server + "/api/config")
    assert data["weekly_output_budget"] == 5000000


def test_unknown_route_404(server):
    import urllib.error
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(server + "/api/nonexistent")
    assert exc_info.value.code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test tests/test_server.py
```

Expected: all fail with `ModuleNotFoundError: No module named 'claudemon.server'`

- [ ] **Step 3: Implement `claudemon/server.py`**

```python
import json
import socket
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import claudemon.db as db


def _range_to_timestamps(range_str: str) -> tuple[int, int]:
    now = int(time.time() * 1000)
    today_start = int(
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp() * 1000
    )
    match range_str:
        case "today":
            return today_start, now
        case "7d":
            return now - 7 * 24 * 3600 * 1000, now
        case "30d":
            return now - 30 * 24 * 3600 * 1000, now
        case _:
            return 0, now


def _make_handler(
    conn: sqlite3.Connection,
    config_path: Path,
    dashboard_dir: Path,
):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)

            if parsed.path == "/":
                index = dashboard_dir / "index.html"
                body = index.read_bytes()
                self._respond(200, "text/html; charset=utf-8", body)
                return

            if not parsed.path.startswith("/api/"):
                self._json_error(404, "not found")
                return

            range_str = qs.get("range", ["7d"])[0]
            range_ts = _range_to_timestamps(range_str)

            try:
                if parsed.path == "/api/stats":
                    self._json(db.query_stats(conn, range_ts))

                elif parsed.path == "/api/timeline":
                    bucket = qs.get("bucket", ["1d"])[0]
                    self._json(db.query_timeline(conn, range_ts, bucket))

                elif parsed.path == "/api/tasks":
                    self._json(db.query_tasks(conn, range_ts))

                elif parsed.path == "/api/sessions":
                    limit = int(qs.get("limit", ["5"])[0])
                    active_only = qs.get("active", ["false"])[0].lower() == "true"
                    self._json(db.query_sessions(conn, range_ts, limit=limit, active_only=active_only))

                elif parsed.path == "/api/config":
                    if config_path.exists():
                        self._json(json.loads(config_path.read_text()))
                    else:
                        self._json({})

                else:
                    self._json_error(404, "not found")

            except Exception as exc:
                self._json_error(500, str(exc))

        def do_POST(self):
            if self.path != "/api/config":
                self._json_error(404, "not found")
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                incoming = json.loads(body)
                existing = json.loads(config_path.read_text()) if config_path.exists() else {}
                merged = {**existing, **incoming}
                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_text(json.dumps(merged, indent=2))
                self._json(merged)
            except Exception as exc:
                self._json_error(500, str(exc))

        def _json(self, data):
            body = json.dumps(data).encode()
            self._respond(200, "application/json", body)

        def _json_error(self, code: int, msg: str):
            body = json.dumps({"error": msg}).encode()
            self._respond(code, "application/json", body)

        def _respond(self, code: int, content_type: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass  # suppress request logging

    return Handler


def start_server(
    conn: sqlite3.Connection,
    config_path: Path,
    dashboard_dir: Path,
    port: int = 0,
) -> int:
    """Start HTTP server on localhost. Returns the port it bound to."""
    if port == 0:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

    handler = _make_handler(conn, config_path, dashboard_dir)
    server = HTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return port
```

- [ ] **Step 4: Run tests**

```bash
just test tests/test_server.py
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add claudemon/server.py tests/test_server.py
git commit -m "feat: local HTTP server with JSON API endpoints"
```

---

## Task 6: Dashboard HTML/CSS/JS

**Files:**
- Create: `claudemon/dashboard/index.html`
- Create: `claudemon/dashboard/style.css`
- Create: `claudemon/dashboard/app.js`

No unit tests. Verified manually in Task 9 when the full app runs.

- [ ] **Step 1: Create `claudemon/dashboard/style.css`**

```css
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif;
  background: #16161e;
  color: #e8e8f0;
  font-size: 13px;
  overflow-x: hidden;
}

.banner {
  background: rgba(34,197,94,0.08);
  border-bottom: 1px solid rgba(34,197,94,0.15);
  padding: 7px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #86efac;
}
.banner.hidden { display: none; }
.pulse {
  width: 7px; height: 7px; border-radius: 50%;
  background: #22c55e; box-shadow: 0 0 6px #22c55e;
  flex-shrink: 0;
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.5; transform: scale(0.85); }
}
.banner-meta { color: rgba(134,239,172,0.45); margin-left: auto; font-size: 10px; }

.header {
  padding: 12px 16px 10px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  display: flex; justify-content: space-between; align-items: center;
}
.header h1 { font-size: 15px; font-weight: 600; color: #f0f0f8; }

.tabs { display: flex; gap: 2px; background: rgba(255,255,255,0.05); border-radius: 6px; padding: 2px; }
.tab {
  font-size: 10px; font-weight: 500; padding: 3px 8px;
  border-radius: 4px; color: #555; cursor: pointer; border: none;
  background: transparent;
}
.tab.active { background: rgba(167,139,250,0.15); color: #a78bfa; }

.stats {
  display: grid; grid-template-columns: repeat(4,1fr);
  gap: 1px; background: rgba(255,255,255,0.04);
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.stat { background: #16161e; padding: 10px; }
.stat-val { font-size: 14px; font-weight: 700; color: #f0f0f8; letter-spacing: -.02em; }
.stat-lbl { font-size: 9px; font-weight: 500; color: #555; text-transform: uppercase; letter-spacing: .06em; margin-top: 2px; }
.stat-delta { font-size: 10px; margin-top: 2px; color: #34d399; }

section {
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.sec-hdr {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 5px;
}
.sec-title { font-size: 10px; font-weight: 600; color: #555; text-transform: uppercase; letter-spacing: .08em; }
.legend { display: flex; gap: 10px; }
.leg { display: flex; align-items: center; gap: 4px; font-size: 9px; color: #555; }
.leg-dot { width: 6px; height: 6px; border-radius: 2px; }
.leg-line { width: 12px; height: 2px; border-radius: 1px; }
.axis-labels { display: flex; justify-content: space-between; margin-bottom: 2px; }
.axis-lbl { font-size: 9px; color: #2e2e3e; font-weight: 500; }
.chart-wrap { height: 80px; position: relative; }
.chart-wrap.tall { height: 130px; }

.budget-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; }
.budget-lbl { font-size: 11px; color: #666; }
.budget-val { font-size: 11px; font-weight: 600; color: #c4b5fd; }
.budget-track { height: 4px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; }
.budget-fill { height: 100%; border-radius: 3px; background: linear-gradient(90deg, #7c3aed, #a78bfa); }
.budget-sub { font-size: 10px; color: #333; margin-top: 4px; }

.model-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
.model-track { flex: 1; height: 3px; background: rgba(255,255,255,0.06); border-radius: 2px; overflow: hidden; }
.model-fill { height: 100%; border-radius: 2px; }
.model-name { font-size: 11px; color: #bbb; font-weight: 500; width: 76px; flex-shrink: 0; }
.model-toks { font-size: 10px; color: #444; text-align: right; white-space: nowrap; width: 96px; flex-shrink: 0; }

.s-row {
  display: flex; align-items: center; gap: 8px; padding: 5px 0;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.s-row:last-child { border-bottom: none; }
.s-dot { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; }
.s-info { flex: 1; min-width: 0; }
.s-title { font-size: 11px; color: #ccc; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.s-proj { font-size: 10px; color: #444; margin-top: 1px; }
.s-right { text-align: right; flex-shrink: 0; }
.s-tokens { font-size: 10px; color: #555; white-space: nowrap; }
.s-tasks { font-size: 10px; color: #3a3a50; white-space: nowrap; margin-top: 1px; }

footer {
  padding: 9px 16px;
  display: flex; justify-content: space-between; align-items: center;
  border-bottom: none;
}
.footer-stat { font-size: 10px; color: #333; }
#quit-btn { font-size: 11px; color: #444; background: none; border: none; cursor: pointer; }
```

- [ ] **Step 2: Create `claudemon/dashboard/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>claudemon</title>
  <link rel="stylesheet" href="style.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
</head>
<body>

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

<section>
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
  <div class="sec-hdr">
    <div class="sec-title">Queries + tokens/query</div>
    <div class="legend">
      <div class="leg"><div class="leg-dot" style="background:rgba(251,146,60,0.8)"></div>queries</div>
      <div class="leg"><div class="leg-line" style="background:#fcd34d"></div>tok/query</div>
    </div>
  </div>
  <div class="axis-labels"><div class="axis-lbl">← queries</div><div class="axis-lbl">tok/query →</div></div>
  <div class="chart-wrap"><canvas id="query-chart"></canvas></div>
</section>

<section>
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
      <div class="leg"><div class="leg-line" style="background:#fcd34d"></div>tok/task</div>
    </div>
  </div>
  <div class="axis-labels"><div class="axis-lbl">← queries</div><div class="axis-lbl">tok/task →</div></div>
  <div class="chart-wrap tall"><canvas id="task-chart"></canvas></div>
</section>

<section>
  <div class="budget-row">
    <div class="budget-lbl">Weekly output budget</div>
    <div class="budget-val" id="budget-val">—</div>
  </div>
  <div class="budget-track"><div class="budget-fill" id="budget-fill" style="width:0%"></div></div>
  <div class="budget-sub">Personal soft limit · edit in settings</div>
</section>

<section>
  <div class="sec-title" style="margin-bottom:6px">Model breakdown</div>
  <div id="models-list"></div>
</section>

<section>
  <div class="sec-title" style="margin-bottom:4px">Recent sessions</div>
  <div id="sessions-list"></div>
</section>

<footer>
  <div class="footer-stat" id="footer-stat">—</div>
  <button id="quit-btn">Quit</button>
</footer>

<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create `claudemon/dashboard/app.js`**

```javascript
const PALETTE = [
  'rgba(167,139,250,0.82)', 'rgba(56,189,248,0.82)',  'rgba(52,211,153,0.82)',
  'rgba(251,146,60,0.82)',  'rgba(251,191,36,0.82)',  'rgba(232,121,249,0.82)',
  'rgba(99,202,183,0.82)',  'rgba(253,164,175,0.82)', 'rgba(129,140,248,0.82)',
  'rgba(74,222,128,0.82)',  'rgba(250,204,21,0.82)',  'rgba(217,119,6,0.82)',
  'rgba(168,85,247,0.82)',  'rgba(14,165,233,0.82)',
];

const CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false }, tooltip: {
    backgroundColor: '#1c1c28',
    borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1,
    titleColor: '#888', bodyColor: '#ddd', padding: 8,
  }},
};

const SCALE_LEFT = {
  position: 'left',
  grid: { color: 'rgba(255,255,255,0.04)' },
  ticks: { color: '#555', font: { size: 9 },
    callback: v => v >= 1e6 ? (v/1e6).toFixed(0)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v },
  border: { display: false },
};
const SCALE_RIGHT = (color, fmt) => ({
  position: 'right',
  grid: { drawOnChartArea: false },
  ticks: { color, font: { size: 9 }, callback: fmt },
  border: { display: false },
});
const SCALE_X = {
  grid: { display: false },
  ticks: { color: '#555', font: { size: 9 } },
  border: { display: false },
};

function fmt(n) {
  if (n >= 1e9) return (n/1e9).toFixed(1)+'B';
  if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
  if (n >= 1e3) return (n/1e3).toFixed(0)+'k';
  return String(n);
}

function fmtDuration(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${m % 60}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

function fmtDate(ts) {
  return new Date(ts).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

// ── API ──────────────────────────────────────────────────────────────────────

const api = {
  async get(path) {
    const r = await fetch(path);
    return r.json();
  },
  stats(range)    { return api.get(`/api/stats?range=${range}`); },
  timeline(range) { return api.get(`/api/timeline?range=${range}&bucket=${range === 'today' ? '1h' : '1d'}`); },
  tasks(range)    { return api.get(`/api/tasks?range=${range}`); },
  sessions(range) { return api.get(`/api/sessions?range=${range}&limit=5`); },
  active()        { return api.get(`/api/sessions?range=all&limit=1&active=true`); },
  config()        { return api.get(`/api/config`); },
};

// ── Charts (module-level so we can update them) ──────────────────────────────

let tokenChart, queryChart, taskChart;

function initCharts() {
  tokenChart = new Chart(document.getElementById('token-chart'), {
    data: { labels: [], datasets: [] },
    options: { ...CHART_DEFAULTS, scales: { x: SCALE_X, yLeft: { ...SCALE_LEFT, yAxisID: 'yLeft' }, yRight: { ...SCALE_RIGHT('#34d399', v => v + '%'), yAxisID: 'yRight' } } },
  });

  queryChart = new Chart(document.getElementById('query-chart'), {
    data: { labels: [], datasets: [] },
    options: { ...CHART_DEFAULTS, scales: { x: SCALE_X, yLeft: { ...SCALE_LEFT, yAxisID: 'yLeft' }, yRight: { ...SCALE_RIGHT('#fcd34d', v => v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v), yAxisID: 'yRight' } } },
  });

  taskChart = new Chart(document.getElementById('task-chart'), {
    data: { labels: [], datasets: [] },
    options: {
      ...CHART_DEFAULTS,
      plugins: { ...CHART_DEFAULTS.plugins, tooltip: {
        ...CHART_DEFAULTS.plugins.tooltip,
        filter: item => item.raw !== null && item.raw !== 0,
        callbacks: {
          title: items => {
            const d = items[0];
            return d.label;
          },
          label: item => {
            if (item.dataset.label === 'tok/task') return ` avg tok/task: ${fmt(item.raw)}`;
            return ` ${item.dataset.label}: ${item.raw} quer${item.raw === 1 ? 'y' : 'ies'}`;
          },
        },
      }},
      scales: {
        x: SCALE_X,
        yLeft: { ...SCALE_LEFT, stacked: true, yAxisID: 'yLeft' },
        yRight: { ...SCALE_RIGHT('#fcd34d', v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v), yAxisID: 'yRight' },
      },
    },
  });
}

// ── Render helpers ────────────────────────────────────────────────────────────

function renderStats(stats) {
  document.getElementById('stat-sessions').textContent = stats.sessions;
  document.getElementById('stat-input').textContent    = fmt(stats.input_tokens);
  document.getElementById('stat-output').textContent   = fmt(stats.output_tokens);
  document.getElementById('stat-cache').textContent    = stats.cache_hit_rate + '%';
}

function renderTokenChart(timeline) {
  const labels = timeline.map(b => new Date(b.date).toLocaleDateString(undefined, { weekday: 'short' }));
  tokenChart.data.labels = labels;
  tokenChart.data.datasets = [
    { type: 'bar', label: 'Output', data: timeline.map(b => b.output_tokens),
      backgroundColor: 'rgba(167,139,250,0.65)', borderRadius: 3, borderSkipped: false, yAxisID: 'yLeft', order: 2 },
    { type: 'bar', label: 'Input',  data: timeline.map(b => b.input_tokens),
      backgroundColor: 'rgba(56,189,248,0.65)',  borderRadius: 3, borderSkipped: false, yAxisID: 'yLeft', order: 2 },
    { type: 'line', label: 'Cache %', data: timeline.map(b => b.cache_hit_rate),
      borderColor: '#34d399', borderWidth: 1.5, pointRadius: 2.5, pointBackgroundColor: '#34d399',
      tension: 0.4, yAxisID: 'yRight', order: 1 },
  ];
  tokenChart.update();
}

function renderQueryChart(timeline, stats) {
  // timeline doesn't have per-bucket query data; use stats for total,
  // approximate daily distribution from output token distribution
  const labels = timeline.map(b => new Date(b.date).toLocaleDateString(undefined, { weekday: 'short' }));
  const totalOut = timeline.reduce((s, b) => s + b.output_tokens, 0) || 1;
  queryChart.data.labels = labels;
  queryChart.data.datasets = [
    { type: 'bar', label: 'Queries',
      data: timeline.map(b => Math.round((b.output_tokens / totalOut) * (stats?.queries || 0))),
      backgroundColor: 'rgba(251,146,60,0.7)', borderRadius: 3, borderSkipped: false, yAxisID: 'yLeft', order: 2 },
    { type: 'line', label: 'Tok/query',
      data: timeline.map(() => stats?.tokens_per_query || 0),
      borderColor: '#fcd34d', borderWidth: 1.5, pointRadius: 0, tension: 0, yAxisID: 'yRight', order: 1 },
  ];
  queryChart.update();
}

function renderTaskChart(tasksData) {
  if (!tasksData.length) return;
  const labels = tasksData.map(d => new Date(d.date).toLocaleDateString(undefined, { weekday: 'short' }));
  const maxTasks = Math.max(...tasksData.map(d => d.tasks.length));

  const stackDatasets = Array.from({ length: maxTasks }, (_, i) => ({
    type: 'bar',
    label: `Task ${i + 1}`,
    data: tasksData.map(d => d.tasks[i]?.queries ?? null),
    backgroundColor: PALETTE[i % PALETTE.length],
    borderColor: 'rgba(0,0,0,0.12)', borderWidth: 0.5,
    borderRadius: i === 0 ? { bottomLeft: 3, bottomRight: 3 } : 0,
    borderSkipped: false, stack: 'tasks', yAxisID: 'yLeft', order: 2,
  }));

  taskChart.data.labels = labels;
  taskChart.data.datasets = [
    ...stackDatasets,
    { type: 'line', label: 'tok/task',
      data: tasksData.map(d => d.avg_tokens_per_task),
      borderColor: '#fcd34d', borderWidth: 2,
      pointRadius: 3, pointBackgroundColor: '#fcd34d',
      pointBorderColor: '#16161e', pointBorderWidth: 1.5,
      tension: 0.4, yAxisID: 'yRight', order: 1 },
  ];
  taskChart.update();
}

function renderBudget(stats, config) {
  const budget = config?.weekly_output_budget || 0;
  if (!budget) return;
  const pct = Math.min(100, Math.round((stats.output_tokens / budget) * 100));
  document.getElementById('budget-val').textContent =
    `${fmt(stats.output_tokens)} / ${fmt(budget)} (${pct}%)`;
  document.getElementById('budget-fill').style.width = pct + '%';
}

function renderModels(stats) {
  const el = document.getElementById('models-list');
  const total = stats.model_breakdown.reduce((s, m) => s + m.messages, 0) || 1;
  el.innerHTML = stats.model_breakdown.map((m, i) => {
    const pct = Math.round((m.messages / total) * 100);
    const color = PALETTE[i % PALETTE.length];
    const name = m.model.replace('claude-', '').replace(/-\d{8}$/, '');
    return `<div class="model-row">
      <div class="model-name">${name}</div>
      <div class="model-track"><div class="model-fill" style="width:${pct}%;background:${color}"></div></div>
      <div class="model-toks">${fmt(m.input_tokens)} in / ${fmt(m.output_tokens)} out</div>
    </div>`;
  }).join('');
}

function renderSessions(sessions, activeIds = new Set()) {
  const el = document.getElementById('sessions-list');
  if (!sessions.length) { el.innerHTML = '<div style="color:#444;font-size:11px;padding:4px 0">No sessions</div>'; return; }
  el.innerHTML = sessions.map(s => {
    const isActive = activeIds.has(s.session_id);
    const dot = isActive
      ? `style="background:#22c55e;box-shadow:0 0 4px #22c55e"`
      : `style="background:#3a3a4a"`;
    const dur = s.ended_at ? fmtDuration(s.ended_at - s.started_at) : 'active';
    return `<div class="s-row">
      <div class="s-dot" ${dot}></div>
      <div class="s-info">
        <div class="s-title">${s.title || 'Untitled session'}</div>
        <div class="s-proj">${s.project} · ${dur}</div>
      </div>
      <div class="s-right">
        <div class="s-tokens">${fmt(s.input_tokens)} in / ${fmt(s.output_tokens)} out</div>
        <div class="s-tasks">${s.task_count} task${s.task_count !== 1 ? 's' : ''} · ${s.query_count} queries</div>
      </div>
    </div>`;
  }).join('');
}

function renderBanner(activeSessions) {
  const banner = document.getElementById('banner');
  if (!activeSessions.length) { banner.classList.add('hidden'); return; }
  const s = activeSessions[0];
  banner.classList.remove('hidden');
  document.getElementById('banner-project').textContent = s.project;
  const elapsed = s.started_at ? fmtDuration(Date.now() - s.started_at) : '';
  document.getElementById('banner-meta').textContent =
    `${elapsed} · ${fmt(s.input_tokens)} in / ${fmt(s.output_tokens)} out · ${s.task_count} tasks`;
}

function renderFooter(stats) {
  // Query all-time cache reads from a separate "all" stats call would be expensive;
  // show session count from current range instead.
  document.getElementById('footer-stat').textContent =
    `${stats.sessions} sessions · ${stats.queries} queries`;
}

// ── Main refresh loop ─────────────────────────────────────────────────────────

let currentRange = '7d';

async function refresh() {
  const [stats, timeline, tasks, sessions, config] = await Promise.all([
    api.stats(currentRange),
    api.timeline(currentRange),
    api.tasks(currentRange),
    api.sessions(currentRange),
    api.config(),
  ]);
  renderStats(stats);
  renderTokenChart(timeline);
  renderQueryChart(timeline, stats);
  renderTaskChart(tasks);
  renderBudget(stats, config);
  renderModels(stats);
  renderSessions(sessions);
  renderFooter(stats);
}

async function refreshBanner() {
  const active = await api.active();
  renderBanner(active);
}

document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  refresh();
  refreshBanner();

  setInterval(refresh, 30_000);
  setInterval(refreshBanner, 5_000);

  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      currentRange = tab.dataset.range;
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      refresh();
    });
  });

  document.getElementById('quit-btn').addEventListener('click', () => {
    fetch('/api/quit', { method: 'POST' }).catch(() => {});
  });
});
```

- [ ] **Step 4: Commit**

```bash
git add claudemon/dashboard/
git commit -m "feat: dashboard HTML/CSS/JS with Chart.js"
```

---

## Task 7: Menu bar status item (`statusitem.py`)

**Files:**
- Create: `claudemon/statusitem.py`

No unit tests (macOS UI; requires running app). Verified in Task 9.

- [ ] **Step 1: Implement `claudemon/statusitem.py`**

```python
import threading
import time
from pathlib import Path

import rumps

import claudemon.db as db

# State dot unicode + color CSS (rendered as colored NSAttributedString via rumps title)
_STATES = {
    "none":    "⬤",   # drawn muted via title color
    "idle":    "⬤",
    "working": "⬤",
}

_CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"


def _read_session_state() -> str:
    """Return 'working', 'idle', or 'none' based on ~/.claude/sessions/*.json."""
    try:
        json_files = list(_CLAUDE_SESSIONS_DIR.glob("*.json"))
    except OSError:
        return "none"
    if not json_files:
        return "none"
    import json
    for p in json_files:
        try:
            data = json.loads(p.read_text())
            if data.get("status") == "busy":
                return "working"
        except (OSError, ValueError):
            continue
    return "idle"


class StatusItem:
    """Manages the rumps menu bar status item: icon + token count + state dot."""

    def __init__(self, conn, app: rumps.App):
        self._conn = conn
        self._app = app
        self._state = "none"
        self._tokens = 0
        self._pulse_thread: threading.Thread | None = None
        self._running = False
        self._update()

    def on_jsonl_change(self, _path=None) -> None:
        """Called by watcher when JSONL files change."""
        self._tokens = db.query_today_output_tokens(self._conn)
        self._refresh_title()

    def on_session_change(self) -> None:
        """Called by watcher when session state files change."""
        new_state = _read_session_state()
        if new_state != self._state:
            self._state = new_state
            self._manage_pulse(new_state)
        self._refresh_title()

    def _update(self) -> None:
        self._tokens = db.query_today_output_tokens(self._conn)
        self._state = _read_session_state()
        self._manage_pulse(self._state)
        self._refresh_title()

    def _refresh_title(self) -> None:
        dot = {"none": "○", "idle": "●", "working": "●"}[self._state]
        tok = self._fmt_tokens(self._tokens)
        self._app.title = f"◆ {tok} {dot}"

    def _manage_pulse(self, state: str) -> None:
        if state == "working" and self._pulse_thread is None:
            self._running = True
            self._pulse_thread = threading.Thread(target=self._pulse_loop, daemon=True)
            self._pulse_thread.start()
        elif state != "working":
            self._running = False
            self._pulse_thread = None
            self._refresh_title()

    def _pulse_loop(self) -> None:
        """Alternate the dot character to simulate pulsing in the menu bar text."""
        chars = ["●", "○"]
        i = 0
        while self._running and self._state == "working":
            dot = chars[i % 2]
            tok = self._fmt_tokens(self._tokens)
            self._app.title = f"◆ {tok} {dot}"
            i += 1
            time.sleep(0.6)

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.0f}k"
        return str(n)
```

- [ ] **Step 2: Commit**

```bash
git add claudemon/statusitem.py
git commit -m "feat: menu bar status item with session state dot"
```

---

## Task 8: NSPopover + WKWebView (`popover.py`)

**Files:**
- Create: `claudemon/popover.py`

No unit tests (macOS UI). Verified in Task 9.

- [ ] **Step 1: Implement `claudemon/popover.py`**

```python
from pathlib import Path

import objc
from AppKit import NSApplication, NSRect, NSSize, NSZeroPoint
from Foundation import NSObject, NSURL, NSURLRequest
from WebKit import WKWebView, WKWebViewConfiguration
from AppKit import NSPopover, NSPopoverBehaviorTransient, NSRectEdgeMinY


class Popover:
    """NSPopover containing a WKWebView that loads the local dashboard."""

    WIDTH = 380
    HEIGHT = 620

    def __init__(self, port: int):
        self._url = f"http://127.0.0.1:{port}/"
        self._popover = self._build_popover()

    def _build_popover(self) -> NSPopover:
        config = WKWebViewConfiguration.alloc().init()
        frame = NSRect(NSZeroPoint, NSSize(self.WIDTH, self.HEIGHT))
        webview = WKWebView.alloc().initWithFrame_configuration_(frame, config)

        from AppKit import NSViewController
        vc = NSViewController.alloc().init()
        vc.setView_(webview)
        vc.view().setFrameSize_(NSSize(self.WIDTH, self.HEIGHT))

        popover = NSPopover.alloc().init()
        popover.setContentViewController_(vc)
        popover.setBehavior_(NSPopoverBehaviorTransient)
        popover.setContentSize_(NSSize(self.WIDTH, self.HEIGHT))

        self._webview = webview
        return popover

    def toggle(self, sender) -> None:
        """Show or close the popover anchored to the status item button."""
        if self._popover.isShown():
            self._popover.close()
        else:
            # Load/reload dashboard URL every open so content is fresh
            url = NSURL.URLWithString_(self._url)
            self._webview.loadRequest_(NSURLRequest.requestWithURL_(url))

            # Anchor to the status item's button view
            button = sender._status_item.button() if hasattr(sender, '_status_item') else None
            if button:
                self._popover.showRelativeToRect_ofView_preferredEdge_(
                    button.bounds(), button, NSRectEdgeMinY
                )

    def close(self) -> None:
        if self._popover.isShown():
            self._popover.close()
```

- [ ] **Step 2: Commit**

```bash
git add claudemon/popover.py
git commit -m "feat: NSPopover + WKWebView for dashboard panel"
```

---

## Task 9: App entry point and integration (`app.py`)

**Files:**
- Create: `claudemon/app.py`

- [ ] **Step 1: Implement `claudemon/app.py`**

```python
import json
import logging
import os
from pathlib import Path

import rumps

import claudemon.db as db
from claudemon.indexer import index_all, index_file
from claudemon.popover import Popover
from claudemon.server import start_server
from claudemon.statusitem import StatusItem
from claudemon.watcher import Watcher

logging.basicConfig(level=logging.INFO)

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
CLAUDEMON_DIR = Path.home() / ".claudemon"
DB_PATH = CLAUDEMON_DIR / "claudemon.db"
CONFIG_PATH = CLAUDEMON_DIR / "config.json"
DASHBOARD_DIR = Path(__file__).parent / "dashboard"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except ValueError:
            pass
    return {"weekly_output_budget": 8_000_000, "task_gap_minutes": 30, "server_port": 0}


class ClaudemonApp(rumps.App):
    def __init__(self):
        super().__init__("claudemon", title="◆ — ○", quit_button=None)
        self._config = _load_config()
        self._conn = db.connect(DB_PATH)

        # Full index on startup
        logging.info("Indexing existing sessions…")
        index_all(
            self._conn,
            CLAUDE_PROJECTS_DIR,
            task_gap_minutes=self._config.get("task_gap_minutes", 30),
        )
        logging.info("Initial index complete")

        # Start HTTP server
        port = self._config.get("server_port", 0)
        self._port = start_server(self._conn, CONFIG_PATH, DASHBOARD_DIR, port=port)
        logging.info("Dashboard at http://127.0.0.1:%d", self._port)

        # Status item
        self._status = StatusItem(self._conn, self)

        # Popover
        self._popover = Popover(self._port)

        # File watcher
        self._watcher = Watcher(
            CLAUDE_PROJECTS_DIR,
            CLAUDE_SESSIONS_DIR,
            on_jsonl_change=self._on_jsonl_change,
            on_session_change=self._status.on_session_change,
        )
        self._watcher.start()

        # Quit menu item
        self.menu = [rumps.MenuItem("Quit claudemon", callback=self._quit)]

    @rumps.clicked("claudemon")
    def _on_icon_click(self, sender):
        self._popover.toggle(sender)

    def _on_jsonl_change(self, path: Path) -> None:
        index_file(
            self._conn, path,
            task_gap_minutes=self._config.get("task_gap_minutes", 30),
        )
        self._status.on_jsonl_change(path)

    def _quit(self, _sender=None):
        self._watcher.stop()
        rumps.quit_application()


def main():
    ClaudemonApp().run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run full test suite to confirm everything still passes**

```bash
just coverage
```

Expected: all tests pass, coverage ≥ 80%.

- [ ] **Step 3: Smoke-test the running app**

```bash
python -m claudemon.app
```

Expected:
- Menu bar shows `◆ Xk ○` (or `M` if you have heavy today usage)
- Click icon → popover opens with dashboard
- Charts render with real data from your `~/.claude` history
- Opening a Claude Code session turns the dot amber, then green when it starts working
- Token count updates within seconds of Claude generating output

- [ ] **Step 4: Commit**

```bash
git add claudemon/app.py
git commit -m "feat: app entry point, wires all components together"
```

---

## Task 10: Coverage check and pre-push hook

- [ ] **Step 1: Run coverage and verify ≥ 80%**

```bash
just coverage
```

Expected output contains something like:
```
TOTAL    xxx    xx    82%
```

If below 80%: identify uncovered lines (`--cov-report=term-missing` shows them), add targeted tests for any important logic branches in `indexer.py` or `db.py` that are missing coverage.

- [ ] **Step 2: Install pre-push hook**

```bash
just install-pre-push
```

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: install pre-push hook, verify coverage gate"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ Tech stack (rumps, PyObjC NSPopover, WKWebView, watchdog, SQLite, http.server, Chart.js)
- ✅ All 8 modules (app, db, indexer, watcher, server, statusitem, popover, dashboard/)
- ✅ SQLite schema (sessions, messages, file_cursors with all columns incl. task_id, query_id)
- ✅ Task boundary detection: session start, /clear, git branch change, 30-min gap
- ✅ Query definition (non-meta, non-tool-result user message)
- ✅ Menu bar: icon + today output tokens + state dot (none/idle/working)
- ✅ Session state from ~/.claude/sessions/*.json status field
- ✅ All 10 dashboard sections incl. active session banner, 3 charts, budget bar, model breakdown, sessions list
- ✅ All 7 API endpoints (/api/stats, /api/timeline, /api/tasks, /api/sessions, /api/config GET+POST)
- ✅ Config file at ~/.claudemon/config.json
- ✅ 5-second banner poll, 30-second full refresh
- ✅ Incremental indexing via byte-offset cursors
- ✅ Full re-index on startup
- ✅ Tests: unit (db, indexer, server), integration pipeline, ≥80% coverage
- ✅ /api/quit referenced in app.js — **gap**: server.py doesn't handle POST /api/quit. Fix: add a `do_POST` handler for `/api/quit` that calls `os.kill(os.getpid(), signal.SIGTERM)`.

**Fix for /api/quit gap** — add to the `do_POST` method in `server.py` before the `/api/config` handler:

```python
if self.path == "/api/quit":
    import os, signal
    self._json({"ok": True})
    os.kill(os.getpid(), signal.SIGTERM)
    return
```
