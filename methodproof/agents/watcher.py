"""File watcher agent — captures file changes and git commits."""

import os
import re
import subprocess
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from methodproof.agents import base

IGNORE_PATTERNS = re.compile(
    r"(__pycache__|\.pyc|\.git/|node_modules|\.DS_Store|\.swp|~$)"
)


class _Handler(FileSystemEventHandler):
    def __init__(self, watch_dir: str) -> None:
        self._root = watch_dir

    def _relpath(self, path: str) -> str:
        return os.path.relpath(path, self._root)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory or IGNORE_PATTERNS.search(event.src_path):
            return
        path = self._relpath(event.src_path)
        lang = Path(event.src_path).suffix.lstrip(".")
        try:
            size = os.path.getsize(event.src_path)
        except OSError:
            size = 0
        base.emit("file_create", {"path": path, "size": size, "language": lang})

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory or IGNORE_PATTERNS.search(event.src_path):
            return
        path = self._relpath(event.src_path)
        base.emit("file_edit", {
            "path": path, "diff": "", "lines_added": 0,
            "lines_removed": 0, "is_ai_generated": False,
        })

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or IGNORE_PATTERNS.search(event.src_path):
            return
        base.emit("file_delete", {"path": self._relpath(event.src_path)})


def _poll_git(watch_dir: str, stop: threading.Event) -> None:
    """Poll .git/refs for new commits every 2 seconds."""
    git_dir = Path(watch_dir) / ".git"
    if not git_dir.exists():
        return
    seen: set[str] = set()
    refs = git_dir / "refs" / "heads"
    while not stop.is_set():
        try:
            for ref in refs.iterdir():
                sha = ref.read_text().strip()
                if sha not in seen:
                    seen.add(sha)
                    if len(seen) > 1:  # skip initial read
                        _log_commit(watch_dir, sha)
        except OSError:
            pass
        stop.wait(2)


def _log_commit(watch_dir: str, sha: str) -> None:
    try:
        msg = subprocess.run(
            ["git", "-C", watch_dir, "log", "-1", "--format=%s", sha],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        files = subprocess.run(
            ["git", "-C", watch_dir, "diff-tree", "--no-commit-id", "-r", "--name-only", sha],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()
    except Exception:
        msg, files = "", []
    base.emit("git_commit", {"hash": sha[:7], "message": msg, "files_changed": files})


def start(watch_dir: str, stop: threading.Event) -> None:
    """Run file watcher + git poller until stop is set."""
    handler = _Handler(watch_dir)
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=True)
    observer.start()

    git_thread = threading.Thread(target=_poll_git, args=(watch_dir, stop), daemon=True)
    git_thread.start()

    base.log("info", "watcher.started", dir=watch_dir)
    stop.wait()
    observer.stop()
    observer.join(timeout=3)
    base.log("info", "watcher.stopped")
