import json
import os
import secrets
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import claudemon.db as db
import claudemon.updater as updater
from claudemon import keychain
from claudemon._version import __version__ as _APP_VERSION

_usage_cache: dict = {"data": None, "fetched_at": None}
_USAGE_LOCK = threading.Lock()
_CSRF_TOKEN: str = secrets.token_hex(32)


def _call_usage_api(token: str) -> dict:
    """Call Anthropic OAuth usage API. Returns parsed JSON dict."""
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _handle_usage() -> dict:
    """Return /api/usage response dict. Success is cached 115s; errors are not."""
    with _USAGE_LOCK:
        now = time.time()
        cached_ok = (
            _usage_cache["fetched_at"] is not None
            and now - _usage_cache["fetched_at"] < 115
        )
        cached_data = _usage_cache["data"] if cached_ok else None
    if cached_data is not None:
        return cached_data
    try:
        token = keychain.read_access_token()
        raw = _call_usage_api(token)
        result = {
            "available": True,
            "five_hour": raw.get("five_hour"),
            "seven_day": raw.get("seven_day"),
        }
        with _USAGE_LOCK:
            _usage_cache["data"] = result
            _usage_cache["fetched_at"] = time.time()
        return result
    except keychain.KeychainError:
        return {
            "available": False,
            "error": "Token not found — run any claude command to refresh credentials",
        }
    except urllib.error.HTTPError as e:
        msg = (
            "Token expired — run any claude command to refresh"
            if e.code == 401
            else f"Usage API error (HTTP {e.code})"
        )
        return {"available": False, "error": msg}
    except json.JSONDecodeError:
        return {"available": False, "error": "Usage API error — unexpected response format"}
    except (urllib.error.URLError, OSError):
        return {"available": False, "error": "Network error — check your connection"}


def _tz_offset_ms() -> int:
    """Local UTC offset in ms, DST-aware (e.g. -25_200_000 for UTC-7)."""
    return int(datetime.now().astimezone().utcoffset().total_seconds() * 1000)


def _range_to_timestamps(range_str: str) -> tuple[int, int]:
    now = int(time.time() * 1000)
    match range_str:
        case "today":
            return now - 12 * 3600 * 1000, now
        case "7d":
            return now - 7 * 24 * 3600 * 1000, now
        case "30d":
            return now - 30 * 24 * 3600 * 1000, now
        case s if s.startswith("day:"):
            # day:<local_midnight_utc_ms> — return the full local calendar day
            day_start_ms = int(s.split(":", 1)[1])
            day_start_dt = datetime.fromtimestamp(day_start_ms / 1000).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_end_ms = int((day_start_dt + timedelta(days=1)).timestamp() * 1000) - 1
            return day_start_ms, day_end_ms
        case s if s.startswith("custom:"):
            parts = s.split(":")
            return int(parts[1]), int(parts[2])
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
                try:
                    body = index.read_bytes().replace(
                        b"{{CSRF_TOKEN}}", _CSRF_TOKEN.encode()
                    )
                except OSError:
                    self._json_error(404, "dashboard not found")
                    return
                self._respond(200, "text/html; charset=utf-8", body)
                return

            if not parsed.path.startswith("/api/"):
                # Serve static dashboard files (style.css, app.js, etc.)
                rel = parsed.path.lstrip("/")
                candidate = (dashboard_dir / rel).resolve()
                try:
                    candidate.relative_to(dashboard_dir.resolve())
                except ValueError:
                    self._json_error(403, "forbidden")
                    return
                if candidate.is_file():
                    _TYPES = {
                        ".css": "text/css",
                        ".js": "application/javascript",
                        ".html": "text/html; charset=utf-8",
                    }
                    ct = _TYPES.get(candidate.suffix, "application/octet-stream")
                    self._respond(200, ct, candidate.read_bytes())
                else:
                    self._json_error(404, "not found")
                return

            range_str = qs.get("range", ["7d"])[0]
            range_ts = _range_to_timestamps(range_str)

            try:
                if parsed.path == "/api/stats":
                    self._json(db.query_stats(conn, range_ts))

                elif parsed.path == "/api/timeline":
                    bucket = qs.get("bucket", ["1d"])[0]
                    self._json(db.query_timeline(conn, range_ts, bucket, _tz_offset_ms()))

                elif parsed.path == "/api/tasks":
                    bucket = qs.get("bucket", ["1d"])[0]
                    result = db.query_tasks(
                        conn, range_ts, bucket=bucket, tz_offset_ms=_tz_offset_ms()
                    )
                    self._json(result)

                elif parsed.path == "/api/queries":
                    bucket = qs.get("bucket", ["1d"])[0]
                    self._json(db.query_query_breakdown(conn, range_ts, bucket, _tz_offset_ms()))

                elif parsed.path == "/api/sessions":
                    limit = int(qs.get("limit", ["5"])[0])
                    active_only = qs.get("active", ["false"])[0].lower() == "true"
                    result = db.query_sessions(conn, range_ts, limit=limit, active_only=active_only)
                    self._json(result)

                elif parsed.path == "/api/config":
                    config = json.loads(config_path.read_text()) if config_path.exists() else {}
                    self._json({**config, "_version": _APP_VERSION})

                elif parsed.path == "/api/usage":
                    self._json(_handle_usage())

                elif parsed.path == "/api/tools":
                    self._json(db.query_tool_usage(conn, range_ts))

                elif parsed.path == "/api/update-check":
                    updater.check_for_updates()
                    public = updater.get_update_state_for_response()
                    self._json({**public, "bundle": bool(getattr(sys, "frozen", False))})

                elif parsed.path == "/api/update-status":
                    self._json(updater.get_update_status())

                else:
                    self._json_error(404, "not found")

            except Exception as exc:
                self._json_error(500, str(exc))

        def do_POST(self):
            if self.headers.get("X-CSRF-Token") != _CSRF_TOKEN:
                self._json_error(403, "CSRF token mismatch")
                return
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
            self.send_header("Cache-Control", "no-store")
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
    """Start HTTP server on localhost. Returns the port it bound to.

    Uses ThreadingHTTPServer so a slow `/api/usage` (10s upstream timeout) does
    not block other dashboard endpoints. Concurrent cache-miss requests may
    race into duplicate Anthropic calls — benign, the cache then catches up.
    """
    handler = _make_handler(conn, config_path, dashboard_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return port
