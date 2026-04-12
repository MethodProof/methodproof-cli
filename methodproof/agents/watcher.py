"""File watcher agent — captures file changes and git commits."""

import hashlib
import os
import re
import subprocess
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from methodproof.agents import base

IGNORE_PATTERNS = re.compile(
    # Version control
    r"(\.git/|\.hg/|\.svn/"
    # OS / editor artifacts
    r"|\.DS_Store|Thumbs\.db|\.swp|\.swo|~$|\.idea/|\.vscode/"
    # Python
    r"|__pycache__|\.pyc|\.pyo|\.egg-info/|\.eggs/|\.tox/"
    r"|\.venv/|venv/|\.env/|env/|\.mypy_cache/|\.pytest_cache/|\.ruff_cache/"
    r"|\.coverage|htmlcov/|\.nox/"
    # JavaScript / TypeScript
    r"|node_modules/|\.next/|\.nuxt/|\.expo/|\.turbo/|\.parcel-cache/"
    r"|\.svelte-kit/|\.angular/|\.cache/"
    # Rust
    r"|/target/|\.cargo/"
    # Go
    r"|vendor/"
    # Java / Kotlin / JVM
    r"|\.gradle/|\.m2/|/out/"
    # Ruby
    r"|\.bundle/|\.gem/"
    # PHP
    r"|/vendor/|\.phpunit/"
    # .NET / C#
    r"|/bin/|/obj/|\.nuget/"
    # Swift / Xcode
    r"|\.build/|DerivedData/|Pods/"
    # Build output / artifacts
    r"|dist/|build/|\.output/"
    # Logs and locks
    r"|\.lock$|\.log$)"
)


_MAX_DIFF_BYTES = 50_000


def _git_diff_stats(repo: str, path: str) -> tuple[int, int]:
    """Run git diff --stat for a file, return (lines_added, lines_removed)."""
    try:
        result = subprocess.run(
            ["git", "-C", repo, "diff", "--numstat", "--", path],
            capture_output=True, text=True, timeout=5,
        )
        line = result.stdout.strip()
        if not line:
            return 0, 0
        parts = line.split("\t")
        added = int(parts[0]) if parts[0] != "-" else 0
        removed = int(parts[1]) if parts[1] != "-" else 0
        return added, removed
    except Exception:
        return 0, 0


def _git_diff_content(repo: str, path: str) -> str:
    """Get full diff content for a file, capped at 50KB."""
    try:
        result = subprocess.run(
            ["git", "-C", repo, "diff", "--", path],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout[:_MAX_DIFF_BYTES]
    except Exception:
        return ""


def _git_show_diff(repo: str, sha: str) -> str:
    """Get full diff for a commit, capped at 50KB."""
    try:
        result = subprocess.run(
            ["git", "-C", repo, "show", "--format=", sha],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout[:_MAX_DIFF_BYTES]
    except Exception:
        return ""


class _Handler(FileSystemEventHandler):
    def __init__(self, watch_dir: str) -> None:
        self._root = watch_dir
        self._hashes: dict[str, str] = {}

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
        # Skip if content unchanged (watchdog fires on metadata changes)
        try:
            content = Path(event.src_path).read_bytes()
        except OSError:
            return
        path = self._relpath(event.src_path)
        h = hashlib.md5(content).hexdigest()
        if self._hashes.get(path) == h:
            return
        self._hashes[path] = h

        added, removed = _git_diff_stats(self._root, path)
        lang = Path(event.src_path).suffix.lstrip(".")
        meta: dict[str, object] = {
            "path": path, "language": lang,
            "lines_added": added, "lines_removed": removed,
        }
        diff = _git_diff_content(self._root, path)
        if diff:
            meta["diff"] = diff
        base.emit("file_edit", meta)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or IGNORE_PATTERNS.search(event.src_path):
            return
        path = self._relpath(event.src_path)
        self._hashes.pop(path, None)
        lang = Path(event.src_path).suffix.lstrip(".")
        base.emit("file_delete", {"path": path, "language": lang})


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
                    if len(seen) > 1:
                        _log_commit(watch_dir, sha)
        except OSError:
            pass
        stop.wait(2)


def _log_commit(watch_dir: str, sha: str) -> None:
    try:
        # Single git call: subject\x00author\x00email\x00iso_date\x00parent_hash\x00full_body
        fmt = subprocess.run(
            ["git", "-C", watch_dir, "log", "-1",
             "--format=%s%x00%an%x00%ae%x00%ai%x00%P%x00%B", sha],
            capture_output=True, text=True, timeout=5,
        ).stdout
        parts = fmt.split("\x00", 5)
        subject = parts[0].strip() if len(parts) > 0 else ""
        author = parts[1].strip() if len(parts) > 1 else ""
        author_email = parts[2].strip() if len(parts) > 2 else ""
        committed_at = parts[3].strip() if len(parts) > 3 else ""
        parent_hash = parts[4].strip()[:7] if len(parts) > 4 else ""
        body = parts[5].strip() if len(parts) > 5 else ""
        files = subprocess.run(
            ["git", "-C", watch_dir, "diff-tree", "--no-commit-id", "-r", "--name-only", sha],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()
    except Exception:
        subject, author, author_email, committed_at, parent_hash, body, files = "", "", "", "", "", "", []
    meta: dict[str, object] = {
        "hash": sha[:7], "message": subject, "files_changed": files,
        "author": author, "author_email": author_email, "committed_at": committed_at,
    }
    if parent_hash:
        meta["parent_hash"] = parent_hash
    if body and body != subject:
        meta["body"] = body[:2000]
    diff = _git_show_diff(watch_dir, sha)
    if diff:
        meta["diff"] = diff
    base.emit("git_commit", meta)


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
