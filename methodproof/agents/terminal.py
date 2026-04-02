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
}

_PYTEST_RE = re.compile(r"(\d+) passed(?:.*?(\d+) failed)?")
_JEST_RE = re.compile(r"Tests:\s+(?:(\d+) failed,\s+)?(\d+) passed")
_CARGO_RE = re.compile(r"(\d+) passed.*?(\d+) failed")


def _detect_test(command: str) -> str | None:
    for name, pattern in TEST_FRAMEWORKS.items():
        if pattern.search(command):
            return name
    return None


def _parse_test_results(output: str, framework: str, exit_code: int) -> tuple[int, int]:
    """Extract pass/fail counts from test output. Falls back to exit code heuristic."""
    if framework == "pytest":
        m = _PYTEST_RE.search(output)
        if m:
            return int(m.group(1)), int(m.group(2) or 0)
    elif framework == "jest":
        m = _JEST_RE.search(output)
        if m:
            return int(m.group(2) or 0), int(m.group(1) or 0)
    elif framework == "go_test":
        return output.count("--- PASS"), output.count("--- FAIL")
    elif framework == "cargo_test":
        m = _CARGO_RE.search(output)
        if m:
            return int(m.group(1)), int(m.group(2))
    # Fallback: exit code 0 = all passed, non-zero = at least 1 failure
    if exit_code == 0:
        return 1, 0
    return 0, 1


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
    output = entry.get("output", "")[:500]
    # Redact output if it contains secrets
    if SENSITIVE.search(output):
        output = "[redacted — contains sensitive content]"

    base.emit("terminal_cmd", {
        "command": command, "exit_code": exit_code,
        "output_snippet": output, "duration_ms": duration,
    })

    framework = _detect_test(command)
    if framework:
        passed, failed = _parse_test_results(output, framework, exit_code)
        base.emit("test_run", {
            "framework": framework, "passed": passed, "failed": failed,
            "duration_ms": duration,
        })
