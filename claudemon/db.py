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


def query_stats(conn: sqlite3.Connection, range_ts: tuple[int, int]) -> dict:
    start_ms, end_ms = range_ts
    row = conn.execute("""
        SELECT
            COUNT(DISTINCT session_id)              AS sessions,
            COUNT(DISTINCT task_id)                 AS tasks,
            COUNT(DISTINCT query_id)                AS queries,
            COALESCE(SUM(input_tokens), 0)          AS input_tokens,
            COALESCE(SUM(output_tokens), 0)         AS output_tokens,
            COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation,
            COALESCE(SUM(cache_read_tokens), 0)     AS cache_read
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
    """Return per-day task breakdown for stacked chart."""
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
    extra_params = (int(time.time() * 1000) - 60000,) if active_only else ()

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
    from datetime import datetime, timezone
    today_start = int(
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp() * 1000
    )
    now = int(time.time() * 1000)
    row = conn.execute(
        "SELECT COALESCE(SUM(output_tokens), 0) AS total"
        " FROM messages WHERE timestamp BETWEEN ? AND ?",
        (today_start, now),
    ).fetchone()
    return row["total"]
