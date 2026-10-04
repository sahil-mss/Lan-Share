"""Filesystem Watcher for Local Tracked Files.

Features:
- Windows-friendly file watching using watchdog
- Debounce and coalescing for rapid editor saves, temporary atomic swaps (.tmp -> file)
- Stability check before reading/hashing
- Emits clean on_change(local_path, new_hash) events
"""

import os
import time
import threading
from pathlib import Path
from typing import Dict, Set, Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileMovedEvent, FileDeletedEvent

from client.workspace import compute_file_sha256

class DebouncedChangeHandler(FileSystemEventHandler):
    def __init__(
        self,
        watched_paths_provider: Callable[[], Set[str]],
        on_change_callback: Callable[[str, Optional[str]], None],
        debounce_seconds: float = 0.3
    ):
        super().__init__()
        self.watched_paths_provider = watched_paths_provider
        self.on_change_callback = on_change_callback
        self.debounce_seconds = debounce_seconds
        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _normalize(self, path: str) -> str:
        try:
            return str(Path(path).resolve())
        except Exception:
            return os.path.abspath(path)

    def _is_relevant(self, norm_path: str) -> bool:
        watched = self.watched_paths_provider()
        return norm_path in watched

    def _trigger(self, src_path: str):
        norm = self._normalize(src_path)
        if not self._is_relevant(norm):
            return

        with self._lock:
            if norm in self._timers:
                self._timers[norm].cancel()

            timer = threading.Timer(self.debounce_seconds, self._process_change, args=[norm])
            self._timers[norm] = timer
            timer.daemon = True
            timer.start()

    def _process_change(self, norm_path: str):
        with self._lock:
            self._timers.pop(norm_path, None)

        # File stability check: wait for writer to release lock/finish writing
        p = Path(norm_path)
        if not p.exists():
            self.on_change_callback(norm_path, None)
            return

        # Attempt to read hash, retrying briefly if file is locked by editor
        attempts = 5
        cur_hash = None
        for _ in range(attempts):
            try:
                cur_hash = compute_file_sha256(p)
                if cur_hash is not None:
                    break
            except Exception:
                pass
            time.sleep(0.05)

        self.on_change_callback(norm_path, cur_hash)

    def on_modified(self, event):
        if not event.is_directory:
            self._trigger(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._trigger(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            norm = self._normalize(event.src_path)
            if self._is_relevant(norm):
                self._trigger(event.src_path)

    def on_moved(self, event):
        # Handle atomic save renames (e.g., .tmp -> file or file -> old)
        if not event.is_directory:
            self._trigger(event.src_path)
            if hasattr(event, "dest_path"):
                self._trigger(event.dest_path)


class LocalFileWatcher:
    def __init__(self, on_change_callback: Callable[[str, Optional[str]], None], debounce_seconds: float = 0.3):
        self.on_change_callback = on_change_callback
        self.debounce_seconds = debounce_seconds
        self._watched_files: Set[str] = set()
        self._watched_dirs: Set[str] = set()
        self._observer: Optional[Observer] = None
        self._handler = DebouncedChangeHandler(
            watched_paths_provider=self.get_watched_files,
            on_change_callback=self.on_change_callback,
            debounce_seconds=self.debounce_seconds
        )
        self._lock = threading.Lock()

    def get_watched_files(self) -> Set[str]:
        with self._lock:
            return set(self._watched_files)

    def start(self):
        with self._lock:
            if self._observer is None:
                self._observer = Observer()
                self._observer.daemon = True
                # Schedule watches for all existing watched dirs
                for d in self._watched_dirs:
                    if os.path.exists(d):
                        self._observer.schedule(self._handler, d, recursive=True)
                self._observer.start()

    def stop(self):
        with self._lock:
            if self._observer is not None:
                try:
                    self._observer.stop()
                    self._observer.join(timeout=2)
                except Exception:
                    pass
                self._observer = None

    def watch_file(self, local_path: str):
        norm = str(Path(local_path).resolve())
        parent_dir = str(Path(local_path).resolve().parent)
        with self._lock:
            self._watched_files.add(norm)
            if parent_dir not in self._watched_dirs:
                self._watched_dirs.add(parent_dir)
                if self._observer and os.path.exists(parent_dir):
                    self._observer.schedule(self._handler, parent_dir, recursive=True)

    def unwatch_file(self, local_path: str):
        norm = str(Path(local_path).resolve())
        with self._lock:
            self._watched_files.discard(norm)
