import json
import threading
import time
from pathlib import Path

import rumps

import claudemon.db as db

_CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"


def _read_session_state() -> str:
    """Return 'working', 'idle', or 'none' based on ~/.claude/sessions/*.json."""
    try:
        json_files = list(_CLAUDE_SESSIONS_DIR.glob("*.json"))
    except OSError:
        return "none"
    if not json_files:
        return "none"
    for p in json_files:
        try:
            data = json.loads(p.read_text())
            if data.get("status") == "busy":
                return "working"
        except (OSError, ValueError):
            continue
    return "idle"


class StatusItem:
    """Manages the rumps menu bar status item: icon + token count + state dot."""

    def __init__(self, conn, app: rumps.App):
        self._conn = conn
        self._app = app
        self._state = "none"
        self._tokens = 0
        self._pulse_thread: threading.Thread | None = None
        self._running = False
        self._update()

    def on_jsonl_change(self, _path=None) -> None:
        """Called by watcher when JSONL files change."""
        self._tokens = db.query_today_output_tokens(self._conn)
        self._refresh_title()

    def on_session_change(self) -> None:
        """Called by watcher when session state files change."""
        new_state = _read_session_state()
        if new_state != self._state:
            self._state = new_state
            self._manage_pulse(new_state)
        self._refresh_title()

    def _update(self) -> None:
        self._tokens = db.query_today_output_tokens(self._conn)
        self._state = _read_session_state()
        self._manage_pulse(self._state)
        self._refresh_title()

    def _refresh_title(self) -> None:
        dot = {"none": "○", "idle": "●", "working": "●"}[self._state]
        tok = self._fmt_tokens(self._tokens)
        self._app.title = f"◆ {tok} {dot}"

    def _manage_pulse(self, state: str) -> None:
        if state == "working" and self._pulse_thread is None:
            self._running = True
            self._pulse_thread = threading.Thread(target=self._pulse_loop, daemon=True)
            self._pulse_thread.start()
        elif state != "working":
            self._running = False
            self._pulse_thread = None
            self._refresh_title()

    def _pulse_loop(self) -> None:
        """Alternate the dot character to simulate pulsing in the menu bar text."""
        chars = ["●", "○"]
        i = 0
        while self._running and self._state == "working":
            dot = chars[i % 2]
            tok = self._fmt_tokens(self._tokens)
            self._app.title = f"◆ {tok} {dot}"
            i += 1
            time.sleep(0.6)

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.0f}k"
        return str(n)
