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
