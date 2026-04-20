"""IGNORE_PATTERNS — watcher exclusions for runtime log output.

Regression guards for the 8c21 prod symptom: the platform's own log
file ``methodproof-platform/logs/methodproof-platform.jsonl`` captured
as file_edit events, polluting both thread and step distributions with
15,269 spurious events.
"""

from methodproof.agents.watcher import IGNORE_PATTERNS


def _ignored(path: str) -> bool:
    return bool(IGNORE_PATTERNS.search(path))


# ── log-output directories excluded ──────────────────────────────────

def test_jsonl_log_in_logs_dir_excluded() -> None:
    """The 8c21 pathology: jsonl logs under ``logs/`` must not capture."""
    assert _ignored("/repo/methodproof-platform/logs/methodproof-platform.jsonl")


def test_log_file_in_logs_dir_excluded() -> None:
    assert _ignored("/repo/project/logs/app.log")


def test_arbitrary_extension_in_logs_dir_excluded() -> None:
    """Any file under ``logs/`` — txt, out, ndjson, etc. — is runtime output."""
    assert _ignored("/repo/project/logs/events.ndjson")
    assert _ignored("/repo/project/logs/stdout.txt")


def test_nested_logs_dir_excluded() -> None:
    """Deeper logs dirs still match (watchdog sees absolute paths)."""
    assert _ignored("/repo/pkg/sub/logs/trace.jsonl")


# ── legit source files with similar names NOT excluded ─────────────

def test_source_file_named_logs_not_excluded() -> None:
    """A source file named ``logs.py`` is not under ``/logs/`` and stays captured."""
    assert not _ignored("/repo/project/app/logs.py")


def test_logger_module_file_not_excluded() -> None:
    """``app/logging/formatter.py`` has ``logging`` in path but no ``/logs/``."""
    assert not _ignored("/repo/project/app/logging/formatter.py")


# ── existing exclusions still work ──────────────────────────────────

def test_log_extension_still_excluded() -> None:
    """The original ``\\.log$`` check still fires on top-level .log files."""
    assert _ignored("/repo/project/app.log")


def test_lock_extension_still_excluded() -> None:
    assert _ignored("/repo/project/package-lock.lock")


def test_node_modules_still_excluded() -> None:
    """Sanity — don't break the other exclusions."""
    assert _ignored("/repo/project/node_modules/react/index.js")
