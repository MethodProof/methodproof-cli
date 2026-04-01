"""Terminal monitor — captures commands from shell hook JSONL log."""

import json
import os
import re
import threading
import time

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


def _detect_test(command: str) -> str | None:
    for name, pattern in TEST_FRAMEWORKS.items():
        if pattern.search(command):
            return name
    return None


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

    base.emit("terminal_cmd", {
        "command": command, "exit_code": exit_code,
        "output_snippet": output, "duration_ms": duration,
    })

    framework = _detect_test(command)
    if framework:
        base.emit("test_run", {
            "framework": framework, "passed": 0, "failed": 0,
            "duration_ms": duration,
        })
