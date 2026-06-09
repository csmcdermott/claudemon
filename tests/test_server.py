import json
import os
import signal
import time
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

import claudemon.db as db
import claudemon.server as srv
from claudemon.keychain import KeychainError
from claudemon.server import _range_to_timestamps, start_server


def test_range_custom_timestamps():
    start, end = _range_to_timestamps("custom:1000000:2000000")
    assert start == 1_000_000
    assert end == 2_000_000


def test_range_custom_via_endpoint(server):
    # custom range spanning the seeded data should return a result
    now = int(time.time() * 1000)
    data = _get(server + f"/api/stats?range=custom:0:{now}")
    assert data["sessions"] == 1


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
    (dashboard_dir / "style.css").write_text("body { color: red; }")
    (dashboard_dir / "app.js").write_text("console.log('hi');")
    config_path = tmp_path / "config.json"
    config_path.write_text('{"weekly_output_budget": 8000000, "task_gap_minutes": 30}')
    port = start_server(seeded_conn, config_path, dashboard_dir)
    base = f"http://127.0.0.1:{port}"
    # Poll until the server is responding (replaces fixed 100ms sleep).
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


def test_config_includes_version(server):
    data = _get(server + "/api/config")
    assert "_version" in data
    assert isinstance(data["_version"], str)
    assert data["_version"].count(".") == 2  # semver x.y.z


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
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(server + "/api/nonexistent")
    assert exc_info.value.code == 404


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


# ── /api/usage tests ─────────────────────────────────────────────────────────

_MOCK_API_RESPONSE = {
    "five_hour": {"utilization": 42.0, "resets_at": "2026-06-09T18:00:00Z"},
    "seven_day":  {"utilization": 67.0, "resets_at": "2026-06-13T00:00:00Z"},
}


def _reset_usage_cache():
    srv._usage_cache["data"] = None
    srv._usage_cache["fetched_at"] = None


def test_usage_returns_data(server):
    _reset_usage_cache()
    with patch("claudemon.keychain.read_access_token", return_value="tok"), \
         patch("claudemon.server._call_usage_api", return_value=_MOCK_API_RESPONSE):
        data = _get(server + "/api/usage")
    assert data["available"] is True
    assert data["five_hour"]["utilization"] == 42.0
    assert data["seven_day"]["utilization"] == 67.0


def test_usage_cache_hit(server):
    _reset_usage_cache()
    with patch("claudemon.keychain.read_access_token", return_value="tok") as mock_kc, \
         patch("claudemon.server._call_usage_api", return_value=_MOCK_API_RESPONSE) as mock_api:
        _get(server + "/api/usage")
        _get(server + "/api/usage")
    assert mock_kc.call_count == 1   # keychain read once
    assert mock_api.call_count == 1  # API called once, not twice


def test_usage_cache_miss_after_ttl(server):
    _reset_usage_cache()
    with patch("claudemon.keychain.read_access_token", return_value="tok"), \
         patch("claudemon.server._call_usage_api", return_value=_MOCK_API_RESPONSE):
        _get(server + "/api/usage")
    # Expire well beyond any plausible TTL — the test stays valid if TTL is later tuned.
    srv._usage_cache["fetched_at"] = time.time() - 10_000
    with patch("claudemon.keychain.read_access_token", return_value="tok") as mock_kc2, \
         patch("claudemon.server._call_usage_api", return_value=_MOCK_API_RESPONSE):
        _get(server + "/api/usage")
    assert mock_kc2.call_count == 1  # re-fetched after TTL


def test_usage_keychain_error(server):
    _reset_usage_cache()
    with patch("claudemon.keychain.read_access_token", side_effect=KeychainError("not found")):
        data = _get(server + "/api/usage")
    assert data["available"] is False
    assert "Token not found" in data["error"]


def test_usage_401(server):
    _reset_usage_cache()
    from io import BytesIO
    http_err = urllib.error.HTTPError(
        url="https://api.anthropic.com/api/oauth/usage",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=BytesIO(b""),
    )
    with patch("claudemon.keychain.read_access_token", return_value="tok"), \
         patch("claudemon.server._call_usage_api", side_effect=http_err):
        data = _get(server + "/api/usage")
    assert data["available"] is False
    assert "expired" in data["error"]


def test_usage_network_error(server):
    _reset_usage_cache()
    with patch("claudemon.keychain.read_access_token", return_value="tok"), \
         patch("claudemon.server._call_usage_api",
               side_effect=urllib.error.URLError("connection refused")):
        data = _get(server + "/api/usage")
    assert data["available"] is False
    assert "Network error" in data["error"]


def test_usage_non_401_http_error(server):
    _reset_usage_cache()
    from io import BytesIO
    http_err = urllib.error.HTTPError(
        url="https://api.anthropic.com/api/oauth/usage",
        code=429,
        msg="Too Many Requests",
        hdrs={},
        fp=BytesIO(b""),
    )
    with patch("claudemon.keychain.read_access_token", return_value="tok"), \
         patch("claudemon.server._call_usage_api", side_effect=http_err):
        data = _get(server + "/api/usage")
    assert data["available"] is False
    assert "429" in data["error"]


def test_call_usage_api_constructs_correct_request():
    """Verify the real HTTP request: URL, Bearer token, beta header, Accept, timeout.

    Every other usage test mocks _call_usage_api itself, so this is the only
    coverage of the actual urlopen call shape. Required by the OAuth endpoint.
    """
    captured = {}

    class _MockResponse:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"five_hour": {"utilization": 1.0}, "seven_day": {}}'

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["authorization"] = req.get_header("Authorization")
        captured["beta"] = req.get_header("Anthropic-beta")
        captured["accept"] = req.get_header("Accept")
        captured["timeout"] = timeout
        return _MockResponse()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = srv._call_usage_api("test-token")

    assert captured["url"] == "https://api.anthropic.com/api/oauth/usage"
    assert captured["authorization"] == "Bearer test-token"
    assert captured["beta"] == "oauth-2025-04-20"
    assert captured["accept"] == "application/json"
    assert captured["timeout"] == 10
    assert result == {"five_hour": {"utilization": 1.0}, "seven_day": {}}


# ── Static file handler tests ────────────────────────────────────────────────


def test_static_serves_css(server):
    with urllib.request.urlopen(server + "/style.css") as r:
        assert r.status == 200
        assert r.headers["Content-Type"] == "text/css"
        assert b"red" in r.read()


def test_static_404_for_missing_file(server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(server + "/does-not-exist.css")
    assert exc_info.value.code == 404


def test_static_403_for_path_traversal(server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(server + "/../etc/passwd")
    assert exc_info.value.code == 403


# ── /api/quit test ───────────────────────────────────────────────────────────


def test_quit_endpoint_sends_sigterm(server):
    """POST /api/quit returns ok and schedules SIGTERM on current pid."""
    called = {}

    def fake_kill(pid, sig):
        called["pid"] = pid
        called["sig"] = sig

    with patch("os.kill", side_effect=fake_kill):
        req = urllib.request.Request(server + "/api/quit", method="POST", data=b"")
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
        assert result == {"ok": True}

        # Wait inside the patch context for the daemon thread to fire.
        deadline = time.time() + 1.0
        while time.time() < deadline and "pid" not in called:
            time.sleep(0.01)

        assert called.get("pid") == os.getpid()
        assert called.get("sig") == signal.SIGTERM
