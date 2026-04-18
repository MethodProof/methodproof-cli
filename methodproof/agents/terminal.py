"""Terminal monitor — captures commands from shell hook JSONL log."""

import json
import re
import threading

from methodproof.agents import base
from methodproof.config import CMD_LOG

SENSITIVE = re.compile(
    r"(^export\s|^set\s|password|token|secret|api[_-]?key|access[_-]?key"
    r"|credential|private[_-]?key|Authorization:\s*Bearer|ssh\s+-i\s"
    r"|postgres://\S+:\S+@|mysql://\S+:\S+@|--password|--secret|--token"
    r"|AKIA[0-9A-Z]{16}|sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36})",
    re.IGNORECASE,
)

TEST_FRAMEWORKS = {
    "pytest": re.compile(r"\bpytest\b"),
    "jest": re.compile(r"\bjest\b|npx jest|npm test"),
    "go_test": re.compile(r"\bgo test\b"),
    "cargo_test": re.compile(r"\bcargo test\b"),
    "vitest": re.compile(r"\bvitest\b|npx vitest"),
    "mocha": re.compile(r"\bmocha\b|npx mocha"),
    "rspec": re.compile(r"\brspec\b|bundle exec rspec"),
    "minitest": re.compile(r"\bruby\b.*test|rake test"),
    "phpunit": re.compile(r"\bphpunit\b|vendor/bin/phpunit"),
    "unittest": re.compile(r"python.*-m\s+unittest|python.*-m\s+nose"),
    "dotnet_test": re.compile(r"\bdotnet test\b"),
    "swift_test": re.compile(r"\bswift test\b"),
    "gradle_test": re.compile(r"\bgradle\b.*\btest\b|gradlew.*\btest\b"),
    "maven_test": re.compile(r"\bmvn\b.*\btest\b|mvnw.*\btest\b"),
    "exunit": re.compile(r"\bmix test\b"),
}

_PYTEST_RE = re.compile(r"(\d+) passed(?:.*?(\d+) failed)?(?:.*?(\d+) skipped)?")
_JEST_RE = re.compile(r"Tests:\s+(?:(\d+) failed,\s+)?(\d+) passed(?:,\s+(\d+) skipped)?")
_CARGO_RE = re.compile(r"(\d+) passed.*?(\d+) failed")
_VITEST_RE = re.compile(r"Tests\s+(\d+) passed(?:\s*\|\s*(\d+) failed)?(?:\s*\|\s*(\d+) skipped)?")
_RSPEC_RE = re.compile(r"(\d+) examples?,\s*(\d+) failures?(?:,\s*(\d+) pending)?")
_PHPUNIT_RE = re.compile(r"OK \((\d+) tests?|Tests:\s*(\d+).*?Failures:\s*(\d+)")
_DOTNET_RE = re.compile(r"Passed!\s+-\s+Failed:\s+(\d+),\s+Passed:\s+(\d+),\s+Skipped:\s+(\d+)")
_EXUNIT_RE = re.compile(r"(\d+) tests?,\s*(\d+) failures?(?:,\s*(\d+) excluded)?")


def _detect_test(command: str) -> str | None:
    for name, pattern in TEST_FRAMEWORKS.items():
        if pattern.search(command):
            return name
    return None


def _parse_test_results(output: str, framework: str, exit_code: int) -> tuple[int, int, int]:
    """Extract pass/fail/skipped counts from test output. Falls back to exit code heuristic."""
    if framework == "pytest":
        m = _PYTEST_RE.search(output)
        if m:
            return int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)
    elif framework in ("jest", "vitest"):
        pat = _VITEST_RE if framework == "vitest" else _JEST_RE
        m = pat.search(output)
        if m:
            if framework == "vitest":
                return int(m.group(1) or 0), int(m.group(2) or 0), int(m.group(3) or 0)
            return int(m.group(2) or 0), int(m.group(1) or 0), int(m.group(3) or 0)
    elif framework == "go_test":
        return output.count("--- PASS"), output.count("--- FAIL"), output.count("--- SKIP")
    elif framework == "cargo_test":
        m = _CARGO_RE.search(output)
        if m:
            return int(m.group(1)), int(m.group(2)), 0
    elif framework == "rspec":
        m = _RSPEC_RE.search(output)
        if m:
            return int(m.group(1)) - int(m.group(2)), int(m.group(2)), int(m.group(3) or 0)
    elif framework == "phpunit":
        m = _PHPUNIT_RE.search(output)
        if m:
            if m.group(1):
                return int(m.group(1)), 0, 0
            return int(m.group(2) or 0) - int(m.group(3) or 0), int(m.group(3) or 0), 0
    elif framework == "dotnet_test":
        m = _DOTNET_RE.search(output)
        if m:
            return int(m.group(2)), int(m.group(1)), int(m.group(3))
    elif framework == "exunit":
        m = _EXUNIT_RE.search(output)
        if m:
            return int(m.group(1)) - int(m.group(2)), int(m.group(2)), int(m.group(3) or 0)
    if exit_code == 0:
        return 1, 0, 0
    return 0, 1, 0


def start(stop: threading.Event) -> None:
    """Tail the command log and emit events until stop is set."""
    base.log("info", "terminal.started", log=str(CMD_LOG))
    pos = 0
    if CMD_LOG.exists():
        pos = CMD_LOG.stat().st_size

    while not stop.is_set():
        if not CMD_LOG.exists():
            stop.wait(1)
            continue
        size = CMD_LOG.stat().st_size
        if size <= pos:
            stop.wait(0.5)
            continue
        with open(CMD_LOG) as f:
            f.seek(pos)
            for line in f:
                _process(line.strip())
            pos = f.tell()

    base.log("info", "terminal.stopped")


def _process(line: str) -> None:
    if not line:
        return
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return
    command = entry.get("command", "")
    if not command or SENSITIVE.search(command):
        return
    exit_code = entry.get("exit_code", 0)
    duration = entry.get("duration_ms", 0)
    output = entry.get("output", "")
    if SENSITIVE.search(output):
        output = "[redacted — contains sensitive content]"
    cwd = entry.get("cwd", "")

    meta: dict = {
        "command": command, "exit_code": exit_code,
        "output_snippet": output, "duration_ms": duration,
    }
    if cwd:
        meta["cwd"] = cwd
    base.emit("terminal_cmd", meta)

    framework = _detect_test(command)
    if framework:
        passed, failed, skipped = _parse_test_results(output, framework, exit_code)
        test_meta: dict = {
            "framework": framework, "passed": passed, "failed": failed,
            "skipped": skipped, "duration_ms": duration,
        }
        if cwd:
            test_meta["cwd"] = cwd
        base.emit("test_run", test_meta)
