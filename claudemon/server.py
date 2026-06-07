import json
import os
import signal
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
                try:
                    body = index.read_bytes()
                except OSError:
                    self._json_error(404, "dashboard not found")
                    return
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
                    result = db.query_sessions(conn, range_ts, limit=limit, active_only=active_only)
                    self._json(result)

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
            path = urlparse(self.path).path
            if path == "/api/quit":
                self._json({"ok": True})
                threading.Thread(
                    target=lambda: os.kill(os.getpid(), signal.SIGTERM),
                    daemon=True,
                ).start()
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
    handler = _make_handler(conn, config_path, dashboard_dir)
    server = HTTPServer(("127.0.0.1", port), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return port
