"""~/.methodproof/ directory and config.json management."""

import json
from pathlib import Path
from typing import Any

DIR = Path.home() / ".methodproof"
CONFIG = DIR / "config.json"
DB_PATH = DIR / "methodproof.db"
CMD_LOG = DIR / "commands.jsonl"

_DEFAULTS: dict[str, Any] = {
    "api_url": "https://api.methodproof.com",
    "token": "",
    "email": "",
    "active_session": None,
    "e2e_key": "",
    "capture": {
        "terminal_commands": True,
        "command_output": True,
        "test_results": True,
        "file_changes": True,
        "git_commits": True,
        "ai_prompts": True,
        "ai_responses": True,
        "browser": True,
        "music": True,
    },
}

# Descriptions shown during interactive consent
CAPTURE_DESCRIPTIONS: dict[str, str] = {
    "terminal_commands": "Commands you run and their exit codes",
    "command_output": "First 500 chars of command output (secrets auto-filtered)",
    "test_results": "Pass/fail counts from pytest, jest, go test, cargo test",
    "file_changes": "File create, edit, and delete events with paths and line counts",
    "git_commits": "Commit hashes, messages, and changed file lists",
    "ai_prompts": "Text you send to AI tools (Claude Code, OpenClaw, codex, etc.)",
    "ai_responses": "Text AI tools respond with, including tool calls",
    "browser": "Page visits, tab switches, searches, copy events (via extension)",
    "music": "Now Playing track and artist (Spotify, Apple Music, etc.)",
}


def ensure_dirs() -> None:
    DIR.mkdir(exist_ok=True)


def load() -> dict[str, Any]:
    if not CONFIG.exists():
        return dict(_DEFAULTS)
    return {**_DEFAULTS, **json.loads(CONFIG.read_text())}


def save(cfg: dict[str, Any]) -> None:
    ensure_dirs()
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")
    CONFIG.chmod(0o600)
