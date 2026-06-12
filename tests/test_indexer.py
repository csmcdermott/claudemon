from pathlib import Path

import claudemon.db as db
import claudemon.indexer as indexer
from tests.conftest import FIXTURES_DIR

FIXTURE_JSONL = FIXTURES_DIR / "abc123.jsonl"


def test_index_file_creates_session(conn):
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    row = conn.execute("SELECT * FROM sessions WHERE session_id='abc123'").fetchone()
    assert row is not None
    assert row["project"] == "test-project"
    assert row["title"] == "Test session for indexing"


def test_index_file_inserts_messages(conn):
    indexer.index_file(conn, FIXTURE_JSONL, task_gap_minutes=30)
    rows = conn.execute(
        "SELECT * FROM messages WHERE session_id='abc123' ORDER BY timestamp"
    ).fetchall()
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


def test_index_file_nonexistent(conn):
    indexer.index_file(conn, Path("/tmp/nonexistent_abc.jsonl"), task_gap_minutes=30)
    count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert count == 0


def test_index_file_malformed_json(conn, tmp_path):
    jsonl = tmp_path / "bad.jsonl"
    jsonl.write_text(
        'not json\n'
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"hi"}]},'
        '"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"m1","uuid":"u1",'
        '"parentUuid":null,"cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":10},"stop_reason":"end_turn","content":[]},'
        '"timestamp":"2026-06-01T10:00:05.000Z","sessionId":"m1","uuid":"a1",'
        '"parentUuid":"u1","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
    )
    indexer.index_file(conn, jsonl, task_gap_minutes=30)
    # Malformed line skipped; valid assistant still indexed
    count = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id='m1'").fetchone()[0]
    assert count == 1


def test_is_clear_command_string_content():
    record = {"message": {"content": "/clear"}}
    assert indexer._is_clear_command(record)


def test_is_clear_command_non_string_non_list_content():
    record = {"message": {"content": 42}}
    assert not indexer._is_clear_command(record)


def test_index_file_assistant_no_timestamp(conn, tmp_path):
    jsonl = tmp_path / "no_ts.jsonl"
    jsonl.write_text(
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"hi"}]},'
        '"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"n1","uuid":"u1",'
        '"parentUuid":null,"cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":10},"stop_reason":"end_turn","content":[]},'
        '"sessionId":"n1","uuid":"a1","parentUuid":"u1","cwd":"/p","gitBranch":"main",'
        '"isSidechain":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
    )
    # No timestamp on assistant — should be skipped, no crash
    indexer.index_file(conn, jsonl, task_gap_minutes=30)
    count = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id='n1'").fetchone()[0]
    assert count == 0


def test_index_all(conn, tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    jsonl = project_dir / "sess1.jsonl"
    jsonl.write_text(
        '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"hi"}]},'
        '"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1","uuid":"u1",'
        '"parentUuid":null,"cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"isMeta":false,"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
        '{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{'
        '"input_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
        '"output_tokens":10},"stop_reason":"end_turn","content":[]},'
        '"timestamp":"2026-06-01T10:00:05.000Z","sessionId":"s1","uuid":"a1",'
        '"parentUuid":"u1","cwd":"/p","gitBranch":"main","isSidechain":false,'
        '"entrypoint":"cli","userType":"external","version":"2.1.0"}\n'
    )
    indexer.index_all(conn, tmp_path, task_gap_minutes=30)
    count = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id='s1'").fetchone()[0]
    assert count == 1


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
