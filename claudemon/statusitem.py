import json
import threading
import time
from pathlib import Path

import rumps
from AppKit import NSColor, NSMutableAttributedString, NSOperationQueue

import claudemon.db as db

# NSForegroundColorAttributeName is just the string "NSColor" in the ObjC runtime
_FG_COLOR = "NSColor"

_DOT_COLORS = {
    "none":    NSColor.colorWithSRGBRed_green_blue_alpha_(0.20, 0.20, 0.25, 0.5),  # muted
    "idle":    NSColor.colorWithSRGBRed_green_blue_alpha_(0.98, 0.62, 0.04, 1.0),  # amber
    "working": NSColor.colorWithSRGBRed_green_blue_alpha_(0.13, 0.77, 0.37, 1.0),  # green
}
# Claude brand orange (~#D97757)
_CLAUDE_COLOR = NSColor.colorWithSRGBRed_green_blue_alpha_(0.851, 0.467, 0.341, 1.0)

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
        self._button = None  # NSStatusBarButton; set via set_button() after run()
        self._update()

    def set_button(self, button) -> None:
        """Called after rumps initialises the status bar (before_start event)."""
        self._button = button
        self._refresh_title()

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
        tok = self._fmt_tokens(self._tokens)
        if self._button is not None:
            self._apply_title(tok, _DOT_COLORS[self._state])
        else:
            # Fallback before the button is available (during __init__)
            dot = {"none": "○", "idle": "●", "working": "●"}[self._state]
            self._app.title = f"✱ {tok} {dot}"

    def _apply_title(self, tok: str, dot_color) -> None:
        """Build a colored attributed title and dispatch it to the main queue."""
        text = f"✱ {tok} ●"
        attrs = NSMutableAttributedString.alloc().initWithString_(text)
        attrs.addAttribute_value_range_(_FG_COLOR, _CLAUDE_COLOR, (0, 1))
        attrs.addAttribute_value_range_(_FG_COLOR, dot_color, (len(text) - 1, 1))
        button = self._button
        NSOperationQueue.mainQueue().addOperationWithBlock_(
            lambda: button.setAttributedTitle_(attrs)
        )

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
        """Pulse the green dot by alternating full/half opacity."""
        opacities = [1.0, 0.35]
        i = 0
        while self._running and self._state == "working":
            tok = self._fmt_tokens(self._tokens)
            opacity = opacities[i % 2]
            if self._button is not None:
                color = NSColor.colorWithSRGBRed_green_blue_alpha_(0.13, 0.77, 0.37, opacity)
                self._apply_title(tok, color)
            else:
                dot = "●" if opacity > 0.5 else "○"
                self._app.title = f"✱ {tok} {dot}"
            i += 1
            time.sleep(0.6)

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.0f}k"
        return str(n)
