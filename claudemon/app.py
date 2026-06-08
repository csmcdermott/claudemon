import json
import logging
from pathlib import Path

import rumps

import claudemon.db as db
from claudemon.indexer import index_all, index_file
from claudemon.popover import Popover
from claudemon.server import start_server
from claudemon.statusitem import StatusItem
from claudemon.watcher import Watcher

logging.basicConfig(level=logging.INFO)

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
CLAUDEMON_DIR = Path.home() / ".claudemon"
DB_PATH = CLAUDEMON_DIR / "claudemon.db"
CONFIG_PATH = CLAUDEMON_DIR / "config.json"
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
        super().__init__("claudemon", title="◆ — ○", quit_button=None)
        self._config = _load_config()
        self._conn = db.connect(DB_PATH)

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

        # Quit menu item
        self.menu = [rumps.MenuItem("Quit claudemon", callback=self._quit)]

    @rumps.clicked("claudemon")
    def _on_icon_click(self, sender):
        self._popover.toggle(sender)

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
