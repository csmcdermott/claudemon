# claudemon/updater.py
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from claudemon._version import __version__ as _APP_VERSION

GITHUB_REPO = "csmcdermott/claudemon"
CACHE_TTL = 3_600  # 1 hour
# URLs served by GitHub releases redirect through objects.githubusercontent.com.
# Both hosts are validated in perform_update before download.
_TRUSTED_HOSTS = frozenset({"github.com", "objects.githubusercontent.com"})

_update_cache: dict = {"data": None, "checked_at": None}
_update_status: dict = {"state": "idle", "error": None}
_UPDATE_LOCK = threading.Lock()


def _parse_version(tag: str) -> tuple[int, ...]:
    """Parse 'v0.5.13' or '0.5.13-rc1' → (0, 5, 13). Strips pre-release suffix."""
    clean = tag.lstrip("v").split("-")[0]
    return tuple(int(x) for x in clean.split("."))


def check_for_updates() -> dict:
    """Return update state, hitting GitHub API at most once per CACHE_TTL.

    Two simultaneous cache-miss callers may both hit the GitHub API — benign,
    the last writer wins and the cache catches up (same pattern as _handle_usage).
    """
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

        # asset_url is validated against _TRUSTED_HOSTS in perform_update
        # before any network request is made to that URL.
        if latest > current:
            result = {
                "available": True,
                "version": tag.lstrip("v"),
                "asset_url": asset_url,
            }
        else:
            result = {"available": False, "version": _APP_VERSION}

    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        result = {"available": False}
    except (json.JSONDecodeError, ValueError, KeyError):
        result = {"available": False}

    with _UPDATE_LOCK:
        _update_cache["data"] = result
        _update_cache["checked_at"] = time.time()

    return dict(result)


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
