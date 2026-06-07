import json
import time
import urllib.request

import pytest

import claudemon.db as db
from claudemon.server import start_server


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
