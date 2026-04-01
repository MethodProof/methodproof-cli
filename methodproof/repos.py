"""Git repo detection for session context."""

import subprocess


def detect_repo(directory: str) -> str | None:
    """Return the git remote fetch URL, or None if not a git repo."""
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
