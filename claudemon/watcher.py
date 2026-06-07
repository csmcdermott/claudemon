import logging
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class _JSONLHandler(FileSystemEventHandler):
    def __init__(self, on_jsonl_change: Callable[[Path], None]):
        self._on_jsonl_change = on_jsonl_change

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".jsonl"):
            self._on_jsonl_change(Path(event.src_path))

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".jsonl"):
            self._on_jsonl_change(Path(event.src_path))


class _SessionHandler(FileSystemEventHandler):
    def __init__(self, on_session_change: Callable[[], None]):
        self._on_session_change = on_session_change

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".json"):
            self._on_session_change()

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".json"):
            self._on_session_change()

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith(".json"):
            self._on_session_change()


class Watcher:
    """Watches Claude Code data directories and fires callbacks on changes."""

    def __init__(
        self,
        projects_dir: Path,
        sessions_dir: Path,
        on_jsonl_change: Callable[[Path], None],
        on_session_change: Callable[[], None],
    ):
        self._observer = Observer()
        self._observer.schedule(
            _JSONLHandler(on_jsonl_change),
            str(projects_dir),
            recursive=True,
        )
        self._observer.schedule(
            _SessionHandler(on_session_change),
            str(sessions_dir),
            recursive=False,
        )
        self._running = False

    def start(self) -> None:
        self._running = True
        self._observer.start()
        logger.info("File watcher started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._observer.stop()
        self._observer.join(timeout=5)
        logger.info("File watcher stopped")
