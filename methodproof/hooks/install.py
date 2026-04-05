"""Install MethodProof hooks into AI coding tools.

Supports: Claude Code, Codex CLI, Gemini CLI, Kiro, Cline, OpenCode,
plus MCP registration for Cursor, Windsurf, Roo, Kilo, Goose, Amp, Warp, Junie.
"""

import json
import shutil
import sys
import time
from pathlib import Path

_HOOKS_DIR = Path(__file__).parent
_LOG_FILE = Path.home() / ".methodproof" / "hook_install.log"

# --- Claude Code ---
CLAUDE_DIR = Path.home() / ".claude"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
_HOOK_SH = _HOOKS_DIR / "claude_code.sh"
_HOOK_PY = _HOOKS_DIR / "claude_code.py"
HOOK_SCRIPT = _HOOK_PY if sys.platform == "win32" else _HOOK_SH

HOOK_EVENTS = [
    "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "SubagentStart", "SubagentStop",
    "TaskCreated", "TaskCompleted", "SessionStart",
]

# --- Codex CLI ---
_CODEX_DIR = Path.home() / ".codex"
_CODEX_HOOK = _HOOKS_DIR / "codex_hook.sh"
_CODEX_EVENTS = ["PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionStart", "Stop"]

# --- Gemini CLI ---
_GEMINI_DIR = Path.home() / ".gemini"
_GEMINI_HOOK = _HOOKS_DIR / "gemini_hook.sh"
_GEMINI_EVENTS = ["BeforeTool", "AfterTool", "SessionStart", "SessionEnd"]

# --- Kiro ---
_KIRO_DIR = Path.home() / ".kiro"
_KIRO_HOOK = _HOOKS_DIR / "kiro_hook.sh"
_KIRO_EVENTS = [
    "preToolUse", "postToolUse", "preTaskExecution",
    "postTaskExecution", "agentSpawn", "userPromptSubmit", "stop",
]

# --- Cline ---
_CLINE_GLOBAL_DIR = Path.home() / "Documents" / "Cline" / "Rules" / "Hooks"
_CLINE_HOOK = _HOOKS_DIR / "cline_hook.sh"

# --- OpenCode ---
_OPENCODE_PLUGIN = _HOOKS_DIR / "opencode_plugin.js"


def _log(msg: str) -> None:
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_FILE.open("a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def install() -> str | None:
    """Add MethodProof hooks to ~/.claude/settings.json. Returns None if Claude Code not found."""
    if not shutil.which("claude"):
        return None

    CLAUDE_DIR.mkdir(exist_ok=True)
    # On Windows, invoke via python; on Unix, use the shell script directly
    if sys.platform == "win32":
        script = f"{sys.executable} {HOOK_SCRIPT}"
    else:
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


# --- Generic hook installer for Claude-Code-style tools ---

def _install_hooks_json(
    tool: str, binary: str, config_dir: Path, config_file: str,
    hook_script: Path, events: list[str], hooks_key: str = "hooks",
) -> str | None:
    """Install hooks into a tool's JSON config. Returns config path or None."""
    if not shutil.which(binary):
        return None
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / config_file
    script = str(hook_script)

    settings: dict = {}
    if config_path.exists():
        try:
            settings = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            backup = config_path.with_suffix(".json.bak")
            backup.write_text(config_path.read_text())
            settings = {}

    hooks = settings.get(hooks_key, {})
    changed = False
    for event in events:
        entry = {"type": "command", "command": script}
        if event not in hooks:
            hooks[event] = [{"matcher": "", "hooks": [entry]}]
            changed = True
        else:
            existing = [h.get("command", "") for g in hooks[event] for h in g.get("hooks", [])]
            if script not in existing:
                hooks[event].append({"matcher": "", "hooks": [entry]})
                changed = True

    if changed:
        settings[hooks_key] = hooks
        config_path.write_text(json.dumps(settings, indent=2) + "\n")
        _log(f"installed {tool} hooks → {config_path}")
        return str(config_path)
    return "already installed"


# --- Tool-specific installers ---

def install_codex_hooks() -> str | None:
    """Install hooks for OpenAI Codex CLI."""
    return _install_hooks_json(
        "codex", "codex", _CODEX_DIR, "hooks.json", _CODEX_HOOK, _CODEX_EVENTS,
    )


def install_gemini_hooks() -> str | None:
    """Install hooks for Google Gemini CLI."""
    return _install_hooks_json(
        "gemini", "gemini", _GEMINI_DIR, "settings.json", _GEMINI_HOOK, _GEMINI_EVENTS,
    )


def install_kiro_hooks() -> str | None:
    """Install hooks for AWS Kiro."""
    return _install_hooks_json(
        "kiro", "kiro", _KIRO_DIR, "hooks.json", _KIRO_HOOK, _KIRO_EVENTS,
    )


def install_cline_hooks() -> str | None:
    """Install Cline hook script into global hooks directory."""
    if not shutil.which("cline"):
        return None
    _CLINE_GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    target = _CLINE_GLOBAL_DIR / "methodproof.sh"
    if target.exists():
        return "already installed"
    shutil.copy2(_CLINE_HOOK, target)
    target.chmod(0o755)
    _log(f"installed cline hook → {target}")
    return str(target)


def install_opencode_plugin() -> str | None:
    """Install OpenCode JS plugin."""
    if not shutil.which("opencode"):
        return None
    plugin_dir = Path.home() / ".config" / "opencode" / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    target = plugin_dir / "methodproof.js"
    if target.exists():
        return "already installed"
    shutil.copy2(_OPENCODE_PLUGIN, target)
    _log(f"installed opencode plugin → {target}")
    return str(target)


def install_all_hooks() -> dict[str, str | None]:
    """Install hooks for all detected AI tools. Returns {tool: status}."""
    results: dict[str, str | None] = {}
    results["claude_code"] = install()
    results["codex"] = install_codex_hooks()
    results["gemini"] = install_gemini_hooks()
    results["kiro"] = install_kiro_hooks()
    results["cline"] = install_cline_hooks()
    results["opencode"] = install_opencode_plugin()

    from methodproof.hooks.wrappers import install as install_wrappers
    wrapped = install_wrappers()
    results["wrappers"] = f"{len(wrapped)} tools" if wrapped else None

    try:
        from methodproof.hooks.mcp_register import install_all as install_mcp
        mcp_results = install_mcp()
        results.update(mcp_results)
    except ImportError:
        pass

    _log(f"install_all_hooks: {json.dumps({k: bool(v) for k, v in results.items()})}")
    return results
