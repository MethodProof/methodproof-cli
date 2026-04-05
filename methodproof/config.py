"""~/.methodproof/ directory and config.json management."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

DIR = Path.home() / ".methodproof"
CONFIG = DIR / "config.json"
DB_PATH = DIR / "methodproof.db"
CMD_LOG = DIR / "commands.jsonl"

_DEFAULTS: dict[str, Any] = {
    "api_url": "https://api.methodproof.com",
    "token": "",
    "refresh_token": "",
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
        "environment_analysis": True,
        "code_capture": False,
    },
    "research_consent": False,
    "journal_mode": False,
    "publish_redact": {
        "command_output": True,
        "ai_prompts": True,
        "ai_responses": True,
        "code_capture": True,
    },
}

# The 10 standard categories (excludes code_capture)
STANDARD_CATEGORIES = [
    "terminal_commands", "command_output", "test_results", "file_changes",
    "git_commits", "ai_prompts", "ai_responses", "browser", "music",
    "environment_analysis",
]

# Descriptions shown during interactive consent
CAPTURE_DESCRIPTIONS: dict[str, str] = {
    "terminal_commands": "Commands you run and their exit codes",
    "command_output": "First 500 chars of command output (secrets auto filtered)",
    "test_results": "Pass/fail counts from pytest, jest, go test, cargo test",
    "file_changes": "File create, edit, and delete events with paths and line counts",
    "git_commits": "Commit hashes, messages, and changed file lists",
    "ai_prompts": "Your interactions with AI agents: prompts, slash commands, mode switches, and tool management. Captured as graph nodes (Claude Code, codex, aider, etc.)",
    "ai_responses": "AI agent responses, tool calls, and results. Captured as AI Agent Graph edges",
    "browser": "Page visits, tab switches, searches, copy events (via extension)",
    "music": "Now Playing track and artist (Spotify, Apple Music, etc.)",
    "environment_analysis": "Structural profile of your AI dev environment: instruction file sizes, tool counts, config fingerprints (no file content stored)",
    "code_capture": "Full file diffs and git patches (Pro only, encrypted, private by default)",
}

# Content fields that Journal Mode unlocks. When journal_mode is OFF (default),
# these fields are stripped — only structural equivalents remain (lengths, counts, types).
# When journal_mode is ON (Pro+), EVERYTHING is persisted and encrypted.
# Journal = the complete, explicit record of the session.
JOURNAL_CONTENT_FIELDS: list[tuple[str, str]] = [
    # AI prompts — full prompt text
    ("llm_prompt", "prompt_text"),
    ("agent_prompt", "prompt_preview"),
    ("user_prompt", "prompt_preview"),
    # AI responses — full completion text
    ("llm_completion", "response_text"),
    ("agent_completion", "response_preview"),
    ("agent_tool_dispatch", "tool_input_preview"),
    ("agent_tool_result", "result_preview"),
    ("agent_skill_invoke", "skill_input_preview"),
    # Terminal — full command output
    ("terminal_cmd", "output_snippet"),
    ("terminal_cmd", "command"),
    # Code — full diffs and commit messages
    ("file_edit", "diff"),
    ("git_commit", "diff"),
    ("git_commit", "message"),
    # Web — full search queries, URLs, page titles
    ("web_search", "query"),
    ("web_search", "clicked_results"),
    ("web_visit", "url"),
    ("web_visit", "title"),
    # Browser — full search queries, URLs, copy content, AI chat input
    ("browser_search", "query"),
    ("browser_visit", "url"),
    ("browser_visit", "title"),
    ("browser_copy", "text_snippet"),
    ("browser_ai_chat", "detected_input"),
    ("browser_ai_chat", "url"),
    # Inline completions — provider detail
    ("inline_completion_accepted", "text_length"),
]


def ensure_dirs() -> None:
    DIR.mkdir(exist_ok=True)


def secure_file(path: Path) -> None:
    """Best-effort owner-only permissions. Uses icacls on Windows, chmod on Unix."""
    if sys.platform == "win32":
        try:
            username = os.environ.get("USERNAME", "")
            if username:
                subprocess.run(
                    ["icacls", str(path), "/inheritance:r", "/grant:r", f"{username}:F"],
                    capture_output=True, timeout=5,
                )
        except Exception:
            pass
    else:
        path.chmod(0o600)


def load() -> dict[str, Any]:
    if not CONFIG.exists():
        return dict(_DEFAULTS)
    return {**_DEFAULTS, **json.loads(CONFIG.read_text())}


def save(cfg: dict[str, Any]) -> None:
    ensure_dirs()
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")
    secure_file(CONFIG)
