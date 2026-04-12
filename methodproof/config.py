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
    "e2e_key": "",  # legacy — new installs use keychain-derived keys
    "master_key_fingerprint": "",
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
    "contribution_level": None,
    "_pending_research_sync": False,
    "journal_mode": False,
    "journal_credits": 2,
    "e2e_mode": False,
    "e2e_fingerprint": "",
    "auto_update": False,
    "account_id": "",
    "username": "",
    "last_auth_at": 0,
    "local_ai_ports": [],  # user-configured localhost ports for local LLM capture
    "publish_redact": {
        "command_output": True,
        "ai_prompts": True,
        "ai_responses": True,
        "code_capture": True,
    },
    "profiles": {},
    "ui_mode": True,
}

FREE_JOURNAL_MAX_HOURS = 4

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
    # Tasks — subject reveals intent
    ("task_created", "subject"),
    # Claude Code hooks — tool input/output and raw user prompt
    ("user_prompt", "prompt_text"),
    ("tool_call", "tool_input_preview"),
    ("tool_result", "result_preview"),
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


LOCAL_API_URL = "http://localhost:8000"


def load(local: bool = False) -> dict[str, Any]:
    if not CONFIG.exists():
        cfg = dict(_DEFAULTS)
    else:
        cfg = {**_DEFAULTS, **json.loads(CONFIG.read_text())}
    env_url = os.environ.get("METHODPROOF_API_URL")
    if local:
        cfg["api_url"] = LOCAL_API_URL
    elif env_url:
        cfg["api_url"] = env_url
    return cfg


def save(cfg: dict[str, Any]) -> None:
    ensure_dirs()
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")
    secure_file(CONFIG)


# --- Multi-account profiles ---

_PROFILE_KEYS = [
    "token", "refresh_token", "email", "account_id", "username",
    "last_auth_at", "master_key_fingerprint",
    "e2e_mode", "e2e_fingerprint",
    "journal_mode", "journal_credits",
]


def save_active_profile(cfg: dict[str, Any]) -> None:
    """Stash current auth state into profiles dict, keyed by account_id."""
    aid = cfg.get("account_id")
    if not aid:
        return
    profiles = cfg.setdefault("profiles", {})
    profiles[aid] = {k: cfg.get(k, _DEFAULTS.get(k, "")) for k in _PROFILE_KEYS}
    save(cfg)


def restore_profile(cfg: dict[str, Any], account_id: str) -> bool:
    """Swap active auth state to a stored profile. Returns False if not found."""
    profiles = cfg.get("profiles", {})
    profile = profiles.get(account_id)
    if not profile:
        return False
    save_active_profile(cfg)
    for k in _PROFILE_KEYS:
        cfg[k] = profile.get(k, _DEFAULTS.get(k, ""))
    save(cfg)
    return True


def list_profiles(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Return stored profiles with 'active' flag on the current account."""
    active_id = cfg.get("account_id", "")
    profiles = cfg.get("profiles", {})
    result = []
    for aid, p in profiles.items():
        result.append({**p, "active": aid == active_id})
    if active_id and active_id not in profiles:
        result.append({
            k: cfg.get(k, _DEFAULTS.get(k, "")) for k in _PROFILE_KEYS
        } | {"active": True})
    return result


def find_profile(cfg: dict[str, Any], query: str) -> str | None:
    """Match a profile by email or account_id prefix. Returns account_id or None."""
    profiles = cfg.get("profiles", {})
    q = query.lower().strip()
    for aid, p in profiles.items():
        if p.get("email", "").lower() == q or aid.startswith(q):
            return aid
    return None
