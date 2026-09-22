"""Watch a folder for newly written scan images and emit their paths."""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, Signal
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class _Handler(FileSystemEventHandler):
    def __init__(self, patterns: Iterable[str], on_new):
        super().__init__()
        self._patterns = tuple(p.lower() for p in patterns)
        self._on_new = on_new

    def _matches(self, path: str) -> bool:
        name = Path(path).name.lower()
        return any(fnmatch.fnmatch(name, pat) for pat in self._patterns)

    def on_created(self, event):
        if not event.is_directory and self._matches(event.src_path):
            self._on_new(event.src_path)

    def on_moved(self, event):
        # Some apps write to a temp name then rename into place.
        dest = getattr(event, "dest_path", None)
        if dest and self._matches(dest):
            self._on_new(dest)


class FolderWatcher(QObject):
    """Emits ``new_image(path)`` for each new matching file (watchdog thread)."""

    new_image = Signal(str)

    def __init__(self, folder: str, patterns: Iterable[str], parent=None):
        super().__init__(parent)
        self._folder = folder
        self._patterns = tuple(patterns)
        self._observer: Observer | None = None

    def start(self) -> None:
        if self._observer is not None:
            return
        handler = _Handler(self._patterns, self._emit)
        self._observer = Observer()
        self._observer.schedule(handler, self._folder, recursive=False)
        self._observer.start()

    def _emit(self, path: str) -> None:
        # Runs on the watchdog thread; Qt delivers the signal to the GUI thread.
        self.new_image.emit(path)

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None
