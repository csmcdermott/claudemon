# Self-Update + Active Range Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add GitHub release update-checking with an in-place update flow to the dashboard, and persist the user's selected time range across sessions.

**Architecture:** A new `updater.py` module handles all GitHub API calls, caching (1-hour TTL), and the download/install/relaunch sequence. `server.py` gains a module-level CSRF token (fixes all POST endpoints), two new GET routes, and one new POST route. The dashboard gets an update banner above the stats, a two-step confirm flow, and active-range saving on tab click.

**Tech Stack:** Python stdlib only (`secrets`, `urllib.request`, `tempfile`, `subprocess`, `shutil`). JS changes are vanilla (no new libraries). `ditto` CLI (macOS built-in).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `claudemon/updater.py` | Create | Version compare, GitHub API cache, perform_update |
| `tests/test_updater.py` | Create | Unit tests for updater module |
| `claudemon/server.py` | Modify | CSRF token, 3 new routes, CSRF check on all POSTs |
| `claudemon/dashboard/index.html` | Modify | CSRF meta tag placeholder, `#update-banner` element |
| `claudemon/dashboard/style.css` | Modify | `.update-banner` and related styles |
| `claudemon/dashboard/app.js` | Modify | CSRF reading, update banner JS, active range persistence |
| `tests/test_server.py` | Modify | Update fixture, CSRF helper, new route tests |

---

## Task 1: `updater.py` — version parsing and `check_for_updates`

**Files:**
- Create: `claudemon/updater.py`
- Create: `tests/test_updater.py`

- [ ] **Step 1: Create `tests/test_updater.py` with autouse reset fixture and version-parsing tests**

```python
# tests/test_updater.py
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

import claudemon.updater as updater


@pytest.fixture(autouse=True)
def reset_updater():
    updater._update_cache["data"] = None
    updater._update_cache["checked_at"] = None
    updater._update_status["state"] = "idle"
    updater._update_status["error"] = None
    yield


def _make_release_body(tag: str, has_zip: bool = True) -> bytes:
    url = (
        f"https://objects.githubusercontent.com/releases/{tag}/claudemon-{tag}.zip"
    )
    assets = (
        [{"name": f"claudemon-{tag}.zip", "browser_download_url": url}]
        if has_zip
        else []
    )
    return json.dumps({"tag_name": tag, "assets": assets}).encode()


def _mock_resp(body: bytes):
    m = MagicMock()
    m.read.return_value = body
    m.__enter__ = MagicMock(return_value=m)
    m.__exit__ = MagicMock(return_value=False)
    return m


def test_parse_version_with_v_prefix():
    assert updater._parse_version("v0.5.13") == (0, 5, 13)


def test_parse_version_without_prefix():
    assert updater._parse_version("0.5.13") == (0, 5, 13)


def test_parse_version_prerelease_suffix():
    assert updater._parse_version("v0.6.0-rc1") == (0, 6, 0)


def test_check_for_updates_newer_version():
    body = _make_release_body("v99.0.0")
    with patch("claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)):
        result = updater.check_for_updates()
    assert result["available"] is True
    assert result["version"] == "99.0.0"
    assert result["asset_url"] is not None
    assert updater._update_cache["checked_at"] is not None


def test_check_for_updates_same_version():
    tag = f"v{updater._APP_VERSION}"
    body = _make_release_body(tag)
    with patch("claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)):
        result = updater.check_for_updates()
    assert result["available"] is False


def test_check_for_updates_older_version():
    body = _make_release_body("v0.0.1")
    with patch("claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)):
        result = updater.check_for_updates()
    assert result["available"] is False


def test_check_for_updates_cache_ttl():
    body = _make_release_body("v99.0.0")
    with patch(
        "claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)
    ) as mock_open:
        updater.check_for_updates()
        updater.check_for_updates()  # second call should hit cache
    assert mock_open.call_count == 1


def test_check_for_updates_network_error():
    with patch(
        "claudemon.updater.urllib.request.urlopen",
        side_effect=urllib.error.URLError("no network"),
    ):
        result = updater.check_for_updates()
    assert result["available"] is False


def test_check_for_updates_no_zip_asset():
    body = _make_release_body("v99.0.0", has_zip=False)
    with patch("claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)):
        result = updater.check_for_updates()
    assert result["available"] is True
    assert result["asset_url"] is None


def test_check_for_updates_null_assets():
    body = json.dumps({"tag_name": "v99.0.0", "assets": None}).encode()
    with patch("claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)):
        result = updater.check_for_updates()
    assert result["available"] is True
    assert result["asset_url"] is None
```

- [ ] **Step 2: Run tests to confirm they all fail**

```bash
.venv/bin/pytest tests/test_updater.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'claudemon.updater'`

- [ ] **Step 3: Create `claudemon/updater.py` with the module skeleton and `check_for_updates`**

```python
# claudemon/updater.py
import json
import threading
import time
import urllib.error
import urllib.request

from claudemon._version import __version__ as _APP_VERSION

GITHUB_REPO = "csmcdermott/claudemon"
CACHE_TTL = 3_600  # 1 hour
_TRUSTED_HOSTS = frozenset({"github.com", "objects.githubusercontent.com"})

_update_cache: dict = {"data": None, "checked_at": None}
_update_status: dict = {"state": "idle", "error": None}
_UPDATE_LOCK = threading.Lock()


def _parse_version(tag: str) -> tuple[int, ...]:
    """Parse 'v0.5.13' or '0.5.13-rc1' → (0, 5, 13). Strips pre-release suffix."""
    clean = tag.lstrip("v").split("-")[0]
    return tuple(int(x) for x in clean.split("."))


def check_for_updates() -> dict:
    """Return update state, hitting GitHub API at most once per CACHE_TTL."""
    with _UPDATE_LOCK:
        now = time.time()
        if (
            _update_cache["checked_at"] is not None
            and now - _update_cache["checked_at"] < CACHE_TTL
        ):
            return dict(_update_cache["data"])

    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "claudemon",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            release = json.loads(resp.read().decode())

        tag = release.get("tag_name", "")
        latest = _parse_version(tag)
        current = _parse_version(_APP_VERSION)

        assets = release.get("assets") or []
        zip_asset = next(
            (
                a
                for a in assets
                if isinstance(a, dict) and str(a.get("name", "")).endswith(".zip")
            ),
            None,
        )
        asset_url = zip_asset["browser_download_url"] if zip_asset else None

        if latest > current:
            result = {
                "available": True,
                "version": tag.lstrip("v"),
                "asset_url": asset_url,
            }
        else:
            result = {"available": False, "version": _APP_VERSION}

    except Exception:
        result = {"available": False}

    with _UPDATE_LOCK:
        _update_cache["data"] = result
        _update_cache["checked_at"] = time.time()

    return dict(result)
```

- [ ] **Step 4: Run tests to confirm they all pass**

```bash
.venv/bin/pytest tests/test_updater.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add claudemon/updater.py tests/test_updater.py
git commit -m "feat: add updater module with check_for_updates"
```

---

## Task 2: `updater.py` — query functions

**Files:**
- Modify: `claudemon/updater.py`
- Modify: `tests/test_updater.py`

- [ ] **Step 1: Add tests for the three query functions to `tests/test_updater.py`**

Append after the existing tests:

```python
# --- get_update_asset_url ---

def test_get_update_asset_url_empty_cache():
    assert updater.get_update_asset_url() is None


def test_get_update_asset_url_no_update():
    updater._update_cache["data"] = {"available": False, "version": "0.5.0"}
    assert updater.get_update_asset_url() is None


def test_get_update_asset_url_asset_none():
    updater._update_cache["data"] = {
        "available": True, "version": "99.0.0", "asset_url": None
    }
    assert updater.get_update_asset_url() is None


def test_get_update_asset_url_returns_url():
    updater._update_cache["data"] = {
        "available": True,
        "version": "99.0.0",
        "asset_url": "https://objects.githubusercontent.com/foo/bar.zip",
    }
    assert updater.get_update_asset_url() == (
        "https://objects.githubusercontent.com/foo/bar.zip"
    )


# --- get_update_state_for_response ---

def test_get_update_state_for_response_excludes_asset_url():
    updater._update_cache["data"] = {
        "available": True,
        "version": "99.0.0",
        "asset_url": "https://objects.githubusercontent.com/foo/bar.zip",
    }
    result = updater.get_update_state_for_response()
    assert "asset_url" not in result
    assert result["available"] is True
    assert result["version"] == "99.0.0"


def test_get_update_state_for_response_empty_cache():
    result = updater.get_update_state_for_response()
    assert result == {"available": False}


# --- get_update_status ---

def test_get_update_status_initial():
    assert updater.get_update_status() == {"state": "idle", "error": None}
```

- [ ] **Step 2: Run tests to confirm new ones fail**

```bash
.venv/bin/pytest tests/test_updater.py -v
```

Expected: 7 new tests FAIL with `AttributeError: module 'claudemon.updater' has no attribute 'get_update_asset_url'`.

- [ ] **Step 3: Add the three query functions to `claudemon/updater.py`**

Append after `check_for_updates`:

```python
def get_update_asset_url() -> str | None:
    """Return the cached asset download URL if an update is available, else None."""
    with _UPDATE_LOCK:
        data = _update_cache.get("data") or {}
    if data.get("available") and data.get("asset_url"):
        return data["asset_url"]
    return None


def get_update_state_for_response() -> dict:
    """Return cached update state without asset_url (safe for HTTP responses)."""
    with _UPDATE_LOCK:
        data = _update_cache.get("data") or {"available": False}
    return {k: v for k, v in data.items() if k != "asset_url"}


def get_update_status() -> dict:
    """Return current update process status."""
    with _UPDATE_LOCK:
        return dict(_update_status)
```

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/pytest tests/test_updater.py -v
```

Expected: all 18 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add claudemon/updater.py tests/test_updater.py
git commit -m "feat: add updater query functions"
```

---

## Task 3: `updater.py` — `perform_update`

**Files:**
- Modify: `claudemon/updater.py`

No tests for this function — marked `# pragma: no cover`.

- [ ] **Step 1: Add imports and `perform_update` to `claudemon/updater.py`**

Add to the import block at the top of `claudemon/updater.py`:

```python
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse
```

Then append `perform_update` after `get_update_status`:

```python
def perform_update(asset_url: str) -> None:  # pragma: no cover
    """Download, extract, install update to /Applications/claudemon.app, relaunch, quit.

    Runs in a non-daemon thread. If running from a path other than
    /Applications/claudemon.app (e.g. dist/), creates a new copy there.
    """
    with _UPDATE_LOCK:
        _update_status["state"] = "running"
        _update_status["error"] = None

    try:
        parsed = urlparse(asset_url)
        if parsed.scheme != "https" or parsed.netloc not in _TRUSTED_HOSTS:
            raise ValueError(f"Untrusted asset URL: {asset_url}")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "claudemon.zip"

            req = urllib.request.Request(
                asset_url, headers={"User-Agent": "claudemon"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                zip_path.write_bytes(resp.read())

            subprocess.run(
                ["ditto", "-x", "-k", str(zip_path), tmp],
                check=True,
            )

            app_tmp = tmp_path / "claudemon.app"
            if not app_tmp.is_dir() or app_tmp.is_symlink():
                raise RuntimeError(
                    f"Extracted bundle is not a real directory: {app_tmp}"
                )

            subprocess.run(
                ["ditto", str(app_tmp), "/Applications/claudemon.app"],
                check=True,
            )

            # Explicit cleanup before SIGTERM — TemporaryDirectory.__exit__
            # won't run after os.kill terminates the process.
            shutil.rmtree(tmp, ignore_errors=True)

        subprocess.Popen(["open", "/Applications/claudemon.app"])
        os.kill(os.getpid(), signal.SIGTERM)

    except Exception as exc:
        print(f"[claudemon] update failed: {exc}", file=sys.stderr)
        with _UPDATE_LOCK:
            _update_status["state"] = "failed"
            _update_status["error"] = str(exc)
```

- [ ] **Step 2: Run full test suite to confirm nothing broke**

```bash
.venv/bin/pytest tests/test_updater.py -v
```

Expected: all 18 tests PASS (perform_update is not exercised by any test).

- [ ] **Step 3: Commit**

```bash
git add claudemon/updater.py
git commit -m "feat: add perform_update to updater"
```

---

## Task 4: `server.py` — CSRF token, `index.html` injection, `do_POST` check

**Files:**
- Modify: `claudemon/server.py`
- Modify: `claudemon/dashboard/index.html`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Add CSRF meta tag placeholder to `claudemon/dashboard/index.html`**

Insert as the first line inside `<head>`, immediately after `<meta charset="UTF-8">`:

```html
  <meta name="csrf-token" content="{{CSRF_TOKEN}}">
```

So the top of `<head>` now reads:
```html
<head>
  <meta charset="UTF-8">
  <meta name="csrf-token" content="{{CSRF_TOKEN}}">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
```

- [ ] **Step 2: Add new CSRF tests and a `_post` helper to `tests/test_server.py`**

After the existing `_get` helper (line 71), add:

```python
def _post(url: str, data: bytes = b"", extra_headers: dict | None = None) -> dict:
    """POST with the server's CSRF token. Raises HTTPError on non-2xx."""
    headers = {
        "Content-Type": "application/json",
        "X-CSRF-Token": srv._CSRF_TOKEN,
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())
```

Update the `server` fixture at line 50 to include the CSRF placeholder:

```python
    (dashboard_dir / "index.html").write_bytes(
        b"<html><head>"
        b"<meta name='csrf-token' content='{{CSRF_TOKEN}}'>"
        b"</head><body>dashboard</body></html>"
    )
```

Also update the `tools_server` fixture at line 359 the same way:
```python
    (dashboard_dir / "index.html").write_bytes(
        b"<html><head>"
        b"<meta name='csrf-token' content='{{CSRF_TOKEN}}'>"
        b"</head><body>dashboard</body></html>"
    )
```

Add these new tests (place them after `test_static_403_for_path_traversal`):

```python
# ── CSRF tests ────────────────────────────────────────────────────────────────


def test_index_html_injects_csrf_token(server):
    with urllib.request.urlopen(server + "/") as r:
        body = r.read().decode()
    assert srv._CSRF_TOKEN in body
    assert "{{CSRF_TOKEN}}" not in body


def test_post_without_csrf_token_returns_403(server):
    req = urllib.request.Request(
        server + "/api/config", data=b"{}", method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 403


def test_post_with_wrong_csrf_token_returns_403(server):
    req = urllib.request.Request(
        server + "/api/config",
        data=b"{}",
        headers={"X-CSRF-Token": "wrong"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 403
```

Update `test_config_post` (line 130) to use `_post`:

```python
def test_config_post(server):
    body = json.dumps({"weekly_output_budget": 5000000}).encode()
    result = _post(server + "/api/config", data=body)
    assert result["weekly_output_budget"] == 5000000
    data = _get(server + "/api/config")
    assert data["weekly_output_budget"] == 5000000
```

Update `test_quit_endpoint_sends_sigterm` (line 403) to use `_post`:

```python
def test_quit_endpoint_sends_sigterm(server):
    called = {}

    def fake_kill(pid, sig):
        called["pid"] = pid
        called["sig"] = sig

    with patch("os.kill", side_effect=fake_kill):
        result = _post(server + "/api/quit")
        assert result == {"ok": True}

        deadline = time.time() + 1.0
        while time.time() < deadline and "pid" not in called:
            time.sleep(0.01)

        assert called.get("pid") == os.getpid()
        assert called.get("sig") == signal.SIGTERM
```

- [ ] **Step 3: Run tests — expect the CSRF tests to fail and existing POST tests to fail**

```bash
.venv/bin/pytest tests/test_server.py -v -k "csrf or config_post or quit"
```

Expected: 3 CSRF tests FAIL (403 not returned), `test_config_post` FAIL (no CSRF header), `test_quit_endpoint_sends_sigterm` FAIL.

- [ ] **Step 4: Update `claudemon/server.py` — add imports, CSRF token, injection, and `do_POST` check**

Add to the existing imports at the top of `server.py`:

```python
import secrets
import sys
```

Add module-level constant immediately after the `_USAGE_LOCK` line:

```python
_CSRF_TOKEN: str = secrets.token_hex(32)
```

In `do_GET`, modify the `parsed.path == "/"` block (lines 116–124). Replace:

```python
            if parsed.path == "/":
                index = dashboard_dir / "index.html"
                try:
                    body = index.read_bytes()
                except OSError:
                    self._json_error(404, "dashboard not found")
                    return
                self._respond(200, "text/html; charset=utf-8", body)
                return
```

With:

```python
            if parsed.path == "/":
                index = dashboard_dir / "index.html"
                try:
                    body = index.read_bytes().replace(
                        b"{{CSRF_TOKEN}}", _CSRF_TOKEN.encode()
                    )
                except OSError:
                    self._json_error(404, "dashboard not found")
                    return
                self._respond(200, "text/html; charset=utf-8", body)
                return
```

In `do_POST`, add the CSRF check as the very first thing (before the `path = urlparse(...)` line):

```python
        def do_POST(self):
            if self.headers.get("X-CSRF-Token") != _CSRF_TOKEN:
                self._json_error(403, "CSRF token mismatch")
                return
            path = urlparse(self.path).path
            ...  # rest of do_POST unchanged
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_server.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add claudemon/server.py claudemon/dashboard/index.html tests/test_server.py
git commit -m "feat: add CSRF token to server and inject into index.html"
```

---

## Task 5: `server.py` — `GET /api/update-check`

**Files:**
- Modify: `claudemon/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Add tests to `tests/test_server.py`**

Add these imports at the top of `test_server.py`:

```python
import sys as _sys
from unittest.mock import patch

import claudemon.updater as updater
```

Add an autouse fixture after the existing `_reset_usage_cache` helper:

```python
@pytest.fixture(autouse=True)
def reset_updater_cache():
    updater._update_cache["data"] = None
    updater._update_cache["checked_at"] = None
    updater._update_status["state"] = "idle"
    updater._update_status["error"] = None
    yield
```

Add update-check tests (place after the CSRF tests added in Task 4):

```python
# ── /api/update-check tests ───────────────────────────────────────────────────


def test_update_check_shape(server):
    data = _get(server + "/api/update-check")
    assert "available" in data
    assert "bundle" in data
    assert "asset_url" not in data


def test_update_check_bundle_flag_is_false_in_test(server):
    data = _get(server + "/api/update-check")
    assert data["bundle"] is False


def test_update_check_bundle_flag_true_when_frozen(server):
    with patch.object(_sys, "frozen", True, create=True):
        data = _get(server + "/api/update-check")
    assert data["bundle"] is True


def test_update_check_no_asset_url_in_response(server):
    updater._update_cache["data"] = {
        "available": True, "version": "99.0.0",
        "asset_url": "https://objects.githubusercontent.com/foo/bar.zip",
    }
    updater._update_cache["checked_at"] = time.time()
    data = _get(server + "/api/update-check")
    assert data["available"] is True
    assert "asset_url" not in data
```

- [ ] **Step 2: Run new tests — expect them to fail**

```bash
.venv/bin/pytest tests/test_server.py -v -k "update_check"
```

Expected: 4 tests FAIL with 404.

- [ ] **Step 3: Add `GET /api/update-check` route to `server.py`**

Add the import for `updater` at the top of `server.py` (with the other claudemon imports):

```python
import claudemon.updater as updater
```

In `do_GET`, add this `elif` branch after the `elif parsed.path == "/api/tools":` block (before the final `else`):

```python
                elif parsed.path == "/api/update-check":
                    state = updater.check_for_updates()
                    public = {k: v for k, v in state.items() if k != "asset_url"}
                    self._json({**public, "bundle": bool(getattr(sys, "frozen", False))})
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_server.py -v -k "update_check"
```

Expected: all 4 PASS.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add claudemon/server.py tests/test_server.py
git commit -m "feat: add GET /api/update-check endpoint"
```

---

## Task 6: `server.py` — `GET /api/update-status` and `POST /api/update`

**Files:**
- Modify: `claudemon/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Add tests for both routes to `tests/test_server.py`**

```python
# ── /api/update-status tests ──────────────────────────────────────────────────


def test_update_status_idle(server):
    data = _get(server + "/api/update-status")
    assert data == {"state": "idle", "error": None}


def test_update_status_reflects_updater_state(server):
    updater._update_status["state"] = "failed"
    updater._update_status["error"] = "ditto exit 1"
    data = _get(server + "/api/update-status")
    assert data["state"] == "failed"
    assert data["error"] == "ditto exit 1"


# ── /api/update tests ─────────────────────────────────────────────────────────


def test_update_post_no_csrf_returns_403(server):
    req = urllib.request.Request(server + "/api/update", data=b"", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 403


def test_update_post_not_frozen_returns_400(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server + "/api/update")
    assert exc.value.code == 400


def test_update_post_no_update_in_cache_returns_400(server):
    with patch.object(_sys, "frozen", True, create=True):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(server + "/api/update")
    assert exc.value.code == 400


def test_update_post_asset_url_none_returns_400(server):
    updater._update_cache["data"] = {
        "available": True, "version": "99.0.0", "asset_url": None
    }
    updater._update_cache["checked_at"] = time.time()
    with patch.object(_sys, "frozen", True, create=True):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(server + "/api/update")
    assert exc.value.code == 400


def test_update_post_starts_thread(server):
    updater._update_cache["data"] = {
        "available": True,
        "version": "99.0.0",
        "asset_url": "https://objects.githubusercontent.com/foo/bar.zip",
    }
    updater._update_cache["checked_at"] = time.time()

    with patch.object(_sys, "frozen", True, create=True), \
         patch("claudemon.updater.perform_update") as mock_perform:
        result = _post(server + "/api/update")

    assert result == {"status": "started"}
    deadline = time.time() + 1.0
    while time.time() < deadline and not mock_perform.called:
        time.sleep(0.01)
    mock_perform.assert_called_once_with(
        "https://objects.githubusercontent.com/foo/bar.zip"
    )
```

- [ ] **Step 2: Run new tests — expect them to fail**

```bash
.venv/bin/pytest tests/test_server.py -v -k "update_status or update_post"
```

Expected: all 7 FAIL with 404 (routes don't exist yet).

- [ ] **Step 3: Add both routes to `server.py`**

In `do_GET`, add after the `elif parsed.path == "/api/update-check":` block:

```python
                elif parsed.path == "/api/update-status":
                    self._json(updater.get_update_status())
```

In `do_POST`, add a new branch after the CSRF check and before the `path = urlparse(...)` line. Replace the current `do_POST` body (after the CSRF check) with:

```python
            path = urlparse(self.path).path

            if path == "/api/quit":
                self._json({"ok": True})
                threading.Thread(
                    target=lambda: os.kill(os.getpid(), signal.SIGTERM),
                    daemon=True,
                ).start()
                return

            if path == "/api/update":
                if not getattr(sys, "frozen", False):
                    self._json_error(400, "Update only available in .app bundle")
                    return
                asset_url = updater.get_update_asset_url()
                if asset_url is None:
                    self._json_error(400, "No update available")
                    return
                threading.Thread(
                    target=updater.perform_update,
                    args=(asset_url,),
                    daemon=False,
                ).start()
                self._json({"status": "started"})
                return

            if path != "/api/config":
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
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_server.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full suite including updater tests**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add claudemon/server.py tests/test_server.py
git commit -m "feat: add GET /api/update-status and POST /api/update endpoints"
```

---

## Task 7: Dashboard — `index.html` update banner + `style.css`

**Files:**
- Modify: `claudemon/dashboard/index.html`
- Modify: `claudemon/dashboard/style.css`

No automated tests for HTML/CSS.

- [ ] **Step 1: Add `#update-banner` to `claudemon/dashboard/index.html`**

Add immediately after the closing `</div>` of `#banner` (currently on line ~16):

```html
<div id="update-banner" class="update-banner hidden">
  <span id="update-msg"></span>
  <div id="update-actions">
    <button id="update-confirm-btn" class="update-btn">Update now</button>
    <button id="update-dismiss-btn" class="update-dismiss">✕</button>
  </div>
  <span id="update-progress" class="hidden"></span>
</div>
```

- [ ] **Step 2: Add styles to `claudemon/dashboard/style.css`**

Append at the end of the file:

```css
/* ── Update banner ────────────────────────────────────────────────────── */
.update-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: rgba(59, 130, 246, 0.12);
  border-bottom: 1px solid rgba(59, 130, 246, 0.25);
  font-size: 13px;
  color: var(--text);
}

.update-banner #update-msg {
  flex: 1;
}

#update-actions {
  display: flex;
  gap: 6px;
  align-items: center;
}

.update-btn {
  font-size: 12px;
  padding: 3px 10px;
  background: #3b82f6;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.update-btn:hover {
  background: #2563eb;
}

.update-dismiss {
  font-size: 14px;
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  padding: 2px 6px;
  line-height: 1;
}

.update-dismiss:hover {
  color: var(--text);
}

#update-progress {
  flex: 1;
  font-size: 12px;
  color: var(--muted);
}
```

- [ ] **Step 3: Commit**

```bash
git add claudemon/dashboard/index.html claudemon/dashboard/style.css
git commit -m "feat: add update banner HTML and CSS to dashboard"
```

---

## Task 8: `app.js` — CSRF token, `fetchUpdateCheck`, `renderUpdateBanner`

**Files:**
- Modify: `claudemon/dashboard/app.js`

No automated tests — see manual QA checklist at end of plan.

- [ ] **Step 1: Add CSRF token constant near the top of `app.js`**

Add immediately after the `const esc = ...` helper (around line 49):

```js
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content ?? '';
```

- [ ] **Step 2: Add `X-CSRF-Token` header to all existing `fetch` POST calls in `app.js`**

In `saveCollapseState` (around line 699), update the fetch:

```js
  fetch('/api/config', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': CSRF_TOKEN,
    },
    body: JSON.stringify({ section_collapse_state: state }),
  });
```

In `saveSectionOrder` (around line 709), update the fetch:

```js
  fetch('/api/config', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': CSRF_TOKEN,
    },
    body: JSON.stringify({ section_order: order }),
  });
```

In the quit-btn click handler (near the bottom of the IIFE):

```js
  document.getElementById('quit-btn').addEventListener('click', () => {
    fetch('/api/quit', {
      method: 'POST',
      headers: { 'X-CSRF-Token': CSRF_TOKEN },
    }).catch(() => {});
  });
```

- [ ] **Step 3: Add `fetchUpdateCheck` and `renderUpdateBanner`**

Add after `saveSectionOrder` and before `applySectionOrder`:

```js
async function fetchUpdateCheck() {
  try {
    const data = await fetch('/api/update-check').then(r => r.json());
    renderUpdateBanner(data);
  } catch (_) {
    // silent fail — update check is best-effort
  }
}

function renderUpdateBanner(data) {
  const banner = document.getElementById('update-banner');
  if (!data.available) {
    banner.classList.add('hidden');
    return;
  }
  const dismissed = sessionStorage.getItem('update-dismissed');
  if (dismissed === data.version) {
    banner.classList.add('hidden');
    return;
  }

  document.getElementById('update-msg').textContent =
    'claudemon ' + esc(data.version) + ' is available';

  const confirmBtn = document.getElementById('update-confirm-btn');
  const dismissBtn = document.getElementById('update-dismiss-btn');

  if (data.bundle) {
    confirmBtn.style.display = '';
    confirmBtn.textContent = 'Update now';
    dismissBtn.style.display = '';
    dismissBtn.textContent = '✕';
  } else {
    confirmBtn.style.display = 'none';
    dismissBtn.style.display = 'none';
    const note = document.createElement('span');
    note.textContent = 'Run just build && just install-app to update.';
    note.style.color = 'var(--muted)';
    note.style.fontSize = '12px';
    document.getElementById('update-actions').appendChild(note);
  }

  banner.classList.remove('hidden');
}
```

- [ ] **Step 4: Call `fetchUpdateCheck` inside the `_stateRestored` block in `refresh()`**

The `_stateRestored` block in `refresh()` is around line 744. It currently looks like:

```js
  if (!_stateRestored) {
    applySectionOrder(config.section_order);
    if (config.section_collapse_state) {
      ...
    }
    _stateRestored = true;
  }
```

Add the `fetchUpdateCheck()` call at the bottom of that block, just before `_stateRestored = true`:

```js
  if (!_stateRestored) {
    applySectionOrder(config.section_order);
    if (config.section_collapse_state) {
      document.querySelectorAll('.csec[data-section-id]').forEach(el => {
        const id = el.dataset.sectionId;
        if (id in config.section_collapse_state) {
          el.classList.toggle('open', config.section_collapse_state[id]);
        }
      });
    }
    fetchUpdateCheck();  // ← add this line
    _stateRestored = true;
  }
```

- [ ] **Step 5: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat: add CSRF token and update banner JS to dashboard"
```

---

## Task 9: `app.js` — update confirmation flow and status polling

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Add the update confirmation state machine and `pollUpdateStatus`**

Add after `renderUpdateBanner`, before `applySectionOrder`:

```js
function initUpdateBanner() {
  const confirmBtn = document.getElementById('update-confirm-btn');
  const dismissBtn = document.getElementById('update-dismiss-btn');
  const actions = document.getElementById('update-actions');
  const progress = document.getElementById('update-progress');

  // Dismiss (State 1 only) — stores version to suppress for this session
  dismissBtn.addEventListener('click', () => {
    const msg = document.getElementById('update-msg').textContent;
    // Extract version from "claudemon X.Y.Z is available"
    const match = msg.match(/claudemon (\S+) is available/);
    if (match) sessionStorage.setItem('update-dismissed', match[1]);
    document.getElementById('update-banner').classList.add('hidden');
    // Reset for next time banner is shown
    confirmBtn.textContent = 'Update now';
    dismissBtn.textContent = '✕';
  });

  let inConfirmState = false;

  confirmBtn.addEventListener('click', async () => {
    if (!inConfirmState) {
      // State 1 → State 2
      inConfirmState = true;
      confirmBtn.textContent = 'Confirm update';
      dismissBtn.textContent = 'Cancel';
      return;
    }

    // State 2 → State 3
    inConfirmState = false;
    actions.classList.add('hidden');
    progress.classList.remove('hidden');
    progress.textContent = 'Updating… app will restart shortly';

    try {
      await fetch('/api/update', {
        method: 'POST',
        headers: { 'X-CSRF-Token': CSRF_TOKEN },
      });
      pollUpdateStatus();
    } catch (err) {
      progress.textContent = 'Update request failed: ' + err.message;
      actions.classList.remove('hidden');
      progress.classList.add('hidden');
      confirmBtn.textContent = 'Update now';
      dismissBtn.textContent = '✕';
    }
  });
}

function pollUpdateStatus() {
  const progress = document.getElementById('update-progress');
  const actions = document.getElementById('update-actions');
  const confirmBtn = document.getElementById('update-confirm-btn');
  const dismissBtn = document.getElementById('update-dismiss-btn');

  const interval = setInterval(async () => {
    try {
      const data = await fetch('/api/update-status').then(r => r.json());
      if (data.state === 'failed') {
        clearInterval(interval);
        progress.textContent = 'Update failed: ' + (data.error || 'unknown error');
        actions.classList.remove('hidden');
        confirmBtn.textContent = 'Retry';
        dismissBtn.textContent = '✕';
      }
      // If 'running' — keep polling. If app restarts, fetch will fail → clearInterval.
    } catch (_) {
      // Connection lost — app is restarting.
      clearInterval(interval);
    }
  }, 2000);
}
```

- [ ] **Step 2: Call `initUpdateBanner()` in the IIFE at the bottom of `app.js`**

At the bottom of the IIFE (just before the closing `})();`), add:

```js
  initUpdateBanner();
```

This goes after the `document.getElementById('quit-btn').addEventListener(...)` call.

- [ ] **Step 3: Run the full test suite to confirm nothing broke**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests PASS (JS changes have no automated tests).

- [ ] **Step 4: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat: add update confirmation flow and status polling"
```

---

## Task 10: `app.js` — active range persistence

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Save `active_range` on tab click**

The tab click handler is near the bottom of the IIFE (around line 836):

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

Add a config POST after setting `currentRange` and before `refresh()`:

```js
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      if (!tab.dataset.range) return;
      currentRange = tab.dataset.range;
      customPicker.style.display = 'none';
      document.getElementById('custom-tab').textContent = 'Custom';
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      // Persist named range (not custom — its dates are ephemeral)
      fetch('/api/config', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': CSRF_TOKEN,
        },
        body: JSON.stringify({ active_range: currentRange }),
      }).catch(() => {});
      refresh();
    });
  });
```

- [ ] **Step 2: Restore `active_range` on first load**

In `refresh()`, inside the `if (!_stateRestored)` block, add range restoration before `fetchUpdateCheck()`:

```js
  if (!_stateRestored) {
    applySectionOrder(config.section_order);
    if (config.section_collapse_state) {
      document.querySelectorAll('.csec[data-section-id]').forEach(el => {
        const id = el.dataset.sectionId;
        if (id in config.section_collapse_state) {
          el.classList.toggle('open', config.section_collapse_state[id]);
        }
      });
    }
    // Restore last selected named range
    const saved = config.active_range;
    const validRanges = ['today', '7d', '30d', 'all'];
    if (saved && validRanges.includes(saved) && saved !== currentRange) {
      currentRange = saved;
      document.querySelectorAll('.tab').forEach(t => {
        t.classList.toggle('active', t.dataset.range === saved);
      });
    }
    fetchUpdateCheck();
    _stateRestored = true;
  }
```

- [ ] **Step 3: Run the full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat: persist active range to config and restore on dashboard load"
```

---

## Task 11: Bump minor version, lint, coverage, final verification

- [ ] **Step 1: Bump minor version**

```bash
just bump-minor
```

- [ ] **Step 2: Run lint**

```bash
just lint
```

Expected: no errors.

- [ ] **Step 3: Run full test suite with coverage**

```bash
just coverage
```

Expected: all tests PASS, coverage ≥ 80%.

- [ ] **Step 4: Commit**

```bash
git add claudemon/_version.py pyproject.toml
git commit -m "chore: bump minor version for self-update and active range persistence"
```

---

## Manual QA Checklist

Before merging, verify in the running `.app` bundle:

- [ ] Open dashboard — if a new version is available on GitHub, update banner appears at top
- [ ] "Update now" click → button text changes to "Confirm update", dismiss text changes to "Cancel"
- [ ] "Cancel" click → banner resets to State 1, nothing written to sessionStorage
- [ ] "Confirm update" click → banner shows "Updating… app will restart shortly", old panel disappears, new version launches
- [ ] Failed update (e.g. network down after confirm) → banner shows error, Retry button visible
- [ ] Dismiss banner → banner hides, reopen panel → banner still hidden (version in sessionStorage)
- [ ] Relaunch app → banner reappears (sessionStorage cleared on WKWebView restart)
- [ ] Running in dev (not frozen) → banner shows version text, no Update button
- [ ] Release with no .zip asset → banner shows version text, no Update button
- [ ] Select 30d tab, close panel, reopen → 30d tab is active
- [ ] Select Custom range, close panel, reopen → previous named range is active (not custom)
- [ ] Check `/api/update-check` response in browser: no `asset_url` field
- [ ] Check `GET /` response source: CSRF token is substituted, no `{{CSRF_TOKEN}}` literal
- [ ] POST to `/api/update` without CSRF header → 403

---

## Spec Coverage Cross-Check

| Spec requirement | Task |
|---|---|
| `updater.py` with version parsing, CACHE_TTL=1h, TRUSTED_HOSTS | Tasks 1–3 |
| `check_for_updates` with schema guard, pre-release strip, cache | Task 1 |
| `get_update_asset_url`, `get_update_state_for_response`, `get_update_status` | Task 2 |
| `perform_update`: URL validate, TemporaryDirectory, ditto, symlink check, rmtree, launch, quit | Task 3 |
| CSRF token: module-level, injected into index.html, checked on all POSTs | Task 4 |
| `GET /api/update-check`: no asset_url in response, bundle flag | Task 5 |
| `GET /api/update-status`: idle/running/failed | Task 6 |
| `POST /api/update`: CSRF, frozen, asset_url guards, non-daemon thread | Task 6 |
| `#update-banner` HTML + CSS | Task 7 |
| CSRF_TOKEN constant, fetchUpdateCheck, renderUpdateBanner, sessionStorage dismiss | Task 8 |
| Two-step confirm (States 1→2→3), pollUpdateStatus, error recovery | Task 9 |
| Active range persistence: save on tab click, restore on first refresh | Task 10 |
| `test_updater.py` with autouse fixture, all listed test cases | Tasks 1–2 |
| `test_server.py` additions: CSRF tests, update-check tests, update-status, update POST tests | Tasks 4–6 |
| `just bump-minor` before commit | Task 11 |
