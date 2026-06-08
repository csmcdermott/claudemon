import time

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


def test_insert_message_idempotent(conn):
    """Inserting the same message twice must not double-count rows."""
    db.upsert_session(conn, "s1", "proj", None, 1000, 2000, "main")
    args = ("s1", "s1:1", "s1:1:1", 1500, "claude-sonnet-4-6", 10, 50, 0, 0)
    db.insert_message(conn, *args)
    db.insert_message(conn, *args)
    rows = conn.execute("SELECT * FROM messages WHERE session_id='s1'").fetchall()
    assert len(rows) == 1


def test_query_sessions_excludes_out_of_range(conn):
    """Sessions whose started_at is outside range_ts must not appear."""
    # Session started at 500, range is [1000, 2000] — should be excluded
    db.upsert_session(conn, "s1", "proj", "Old Session", 500, 600, "main")
    rows = db.query_sessions(conn, (1000, 2000), limit=5)
    assert len(rows) == 0


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
    toks_by_p50 = {b["p50_tokens_per_task"] for b in result}
    toks_by_max = {b["max_tokens_per_task"] for b in result}
    assert toks_by_p50 == {30, 70}
    assert toks_by_max == {30, 70}
