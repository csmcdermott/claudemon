import json
import logging
import sys
from pathlib import Path

import rumps
from Foundation import NSBundle, NSObject
from rumps import events as rumps_events

import claudemon.db as db
from claudemon.indexer import index_all, index_file
from claudemon.popover import Popover
from claudemon.server import start_server
from claudemon.statusitem import StatusItem
from claudemon.watcher import Watcher

# Module-level ref so the ObjC handler can call back into Python without a
# circular reference on the App instance.
_app_instance: "ClaudemonApp | None" = None


class _ClickHandler(NSObject):
    """ObjC target wired to the NSStatusItem button's action."""

    def handleClick_(self, sender):  # noqa: N802
        if _app_instance is not None:
            _app_instance._on_status_click()

logging.basicConfig(level=logging.INFO)

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
CLAUDEMON_DIR = Path.home() / ".claudemon"
CONFIG_PATH = CLAUDEMON_DIR / "config.json"

# When frozen (py2app .app bundle), dashboard lives in Contents/Resources/.
# In development it's a sibling directory of this file.
if getattr(sys, "frozen", False):
    DASHBOARD_DIR = Path(NSBundle.mainBundle().resourcePath()) / "dashboard"
else:
    DASHBOARD_DIR = Path(__file__).parent / "dashboard"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except ValueError:
            pass
    return {"weekly_output_budget": 8_000_000, "task_gap_minutes": 30, "server_port": 0}


class ClaudemonApp(rumps.App):
    def __init__(self):
        global _app_instance
        _app_instance = self

        super().__init__("claudemon", title="◆ — ○", quit_button=None)
        self._config = _load_config()
        self._conn = db.connect()

        # Full index on startup
        logging.info("Indexing existing sessions…")
        index_all(
            self._conn,
            CLAUDE_PROJECTS_DIR,
            task_gap_minutes=self._config.get("task_gap_minutes", 30),
        )
        logging.info("Initial index complete")

        # Start HTTP server
        port = self._config.get("server_port", 0)
        self._port = start_server(self._conn, CONFIG_PATH, DASHBOARD_DIR, port=port)
        logging.info("Dashboard at http://127.0.0.1:%d", self._port)

        # Status item
        self._status = StatusItem(self._conn, self)

        # Popover
        self._popover = Popover(self._port)

        # File watcher
        self._watcher = Watcher(
            CLAUDE_PROJECTS_DIR,
            CLAUDE_SESSIONS_DIR,
            on_jsonl_change=self._on_jsonl_change,
            on_session_change=self._status.on_session_change,
        )
        self._watcher.start()

        # nsstatusitem doesn't exist until run() → initializeStatusBar().
        # Register to wire the button action once it's available.
        rumps_events.before_start.register(self._wire_button_click)

    def _wire_button_click(self) -> None:
        """Called by rumps after initializeStatusBar() — nsstatusitem exists here."""
        self._click_handler = _ClickHandler.alloc().init()
        btn = self._nsapp.nsstatusitem.button()
        btn.setAction_("handleClick:")
        btn.setTarget_(self._click_handler)
        # Remove the dropdown menu so the action fires on direct click.
        # Quit is available via the dashboard's Quit button (POST /api/quit).
        self._nsapp.nsstatusitem.setMenu_(None)
        # Hand the button to StatusItem so it can use setAttributedTitle_ for colors.
        self._status.set_button(btn)

    def _on_status_click(self) -> None:
        try:
            self._popover.toggle(self._nsapp.nsstatusitem.button())
        except Exception:
            logging.exception("status click error")

    def _on_jsonl_change(self, path: Path) -> None:
        index_file(
            self._conn, path,
            task_gap_minutes=self._config.get("task_gap_minutes", 30),
        )
        self._status.on_jsonl_change(path)

    def _quit(self, _sender=None):
        self._watcher.stop()
        rumps.quit_application()


def main():
    ClaudemonApp().run()


if __name__ == "__main__":
    main()
