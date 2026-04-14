"""Git repo detection for session context."""

import os
import subprocess


def detect_repo(directory: str) -> str | None:
    """Return the git remote fetch URL for `directory`, or None if not a git repo."""
    return _remote_url(directory)


def enumerate_sub_repos(watch_dir: str, max_depth: int = 2) -> list[dict[str, str]]:
    """Walk `watch_dir` up to `max_depth` levels deep and return one entry per
    nested git repo found.

    Each entry: {"remote_url": str, "rel_path": str} where rel_path is the
    directory's path relative to watch_dir (empty string for watch_dir itself).

    Designed for monorepo workflows where `watch_dir` contains multiple
    independently-versioned sub-repos (e.g., BLACKBOX/methodproof/ contains
    methodproof-platform/, methodproof-dashboard/, etc).
    """
    found: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    def visit(path: str, depth: int) -> None:
        if not os.path.isdir(path):
            return
        if os.path.isdir(os.path.join(path, ".git")):
            url = _remote_url(path)
            if url and url not in seen_urls:
                rel = os.path.relpath(path, watch_dir)
                found.append({"remote_url": url, "rel_path": "" if rel == "." else rel})
                seen_urls.add(url)
        if depth >= max_depth:
            return
        try:
            entries = os.listdir(path)
        except OSError:
            return
        for name in entries:
            if name.startswith("."):
                continue
            child = os.path.join(path, name)
            if os.path.isdir(child) and not os.path.islink(child):
                visit(child, depth + 1)

    visit(os.path.abspath(watch_dir), 0)
    return found


def _remote_url(directory: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", directory, "remote", "-v"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        first_fetch: str | None = None
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "(fetch)" in line:
                if parts[0] == "origin":
                    return parts[1]
                if first_fetch is None:
                    first_fetch = parts[1]
        return first_fetch
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
