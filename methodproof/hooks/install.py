"""Install MethodProof hooks into Claude Code settings."""

import json
import shutil
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
HOOK_SCRIPT = Path(__file__).parent / "claude_code.sh"

HOOK_EVENTS = [
    "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "SubagentStart", "SubagentStop",
    "TaskCreated", "TaskCompleted", "SessionStart",
]


def install() -> str | None:
    """Add MethodProof hooks to ~/.claude/settings.json. Returns None if Claude Code not found."""
    if not shutil.which("claude"):
        return None

    CLAUDE_DIR.mkdir(exist_ok=True)
    script = str(HOOK_SCRIPT)

    # Load existing settings (backup before modifying)
    settings: dict = {}
    if SETTINGS_FILE.exists():
        raw = SETTINGS_FILE.read_text()
        try:
            settings = json.loads(raw)
        except json.JSONDecodeError:
            # Corrupted settings — backup and start fresh
            backup = SETTINGS_FILE.with_suffix(".json.bak")
            backup.write_text(raw)
            settings = {}

    hooks = settings.get("hooks", {})
    changed = False

    for event in HOOK_EVENTS:
        entry = {"type": "command", "command": script}
        if event not in hooks:
            hooks[event] = [{"matcher": "", "hooks": [entry]}]
            changed = True
        else:
            # Check if our hook is already installed
            existing_cmds = [
                h.get("command", "")
                for group in hooks[event]
                for h in group.get("hooks", [])
            ]
            if script not in existing_cmds:
                hooks[event].append({"matcher": "", "hooks": [entry]})
                changed = True

    if changed:
        settings["hooks"] = hooks
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2) + "\n")
        return str(SETTINGS_FILE)
    return "already installed"


def is_installed() -> bool:
    """Check if MethodProof hooks are in Claude Code settings."""
    if not SETTINGS_FILE.exists():
        return False
    try:
        settings = json.loads(SETTINGS_FILE.read_text())
    except json.JSONDecodeError:
        return False
    hooks = settings.get("hooks", {})
    script = str(HOOK_SCRIPT)
    for event in HOOK_EVENTS:
        if event not in hooks:
            return False
        cmds = [h.get("command", "") for g in hooks[event] for h in g.get("hooks", [])]
        if script not in cmds:
            return False
    return True
