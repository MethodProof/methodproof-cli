"""Install MethodProof hook and skill into OpenClaw."""

import json
import shutil
from pathlib import Path

OPENCLAW_DIR = Path.home() / ".openclaw"
HOOKS_DIR = OPENCLAW_DIR / "hooks" / "methodproof"
SKILLS_DIR = OPENCLAW_DIR / "skills" / "methodproof"
CONFIG_FILE = OPENCLAW_DIR / "config.json"
SOURCE_HOOK_DIR = Path(__file__).parent / "openclaw"
SOURCE_SKILL_DIR = Path(__file__).parent.parent / "skills" / "methodproof"


def _has_openclaw() -> bool:
    return shutil.which("openclaw") is not None


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_config(cfg: dict) -> None:
    OPENCLAW_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")


def install() -> str | None:
    """Install MethodProof hook into OpenClaw. Returns None if OpenClaw not found."""
    if not _has_openclaw():
        return None

    if is_installed():
        return "already installed"

    # Copy hook directory
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    for src in SOURCE_HOOK_DIR.iterdir():
        if src.is_file():
            shutil.copy2(src, HOOKS_DIR / src.name)

    # Enable in config
    cfg = _load_config()
    hooks = cfg.setdefault("hooks", {})
    internal = hooks.setdefault("internal", {"enabled": True})
    entries = internal.setdefault("entries", {})
    entries["methodproof"] = {"enabled": True}
    _save_config(cfg)

    return str(HOOKS_DIR)


def is_installed() -> bool:
    if not HOOKS_DIR.exists():
        return False
    if not (HOOKS_DIR / "handler.ts").exists():
        return False
    cfg = _load_config()
    return cfg.get("hooks", {}).get("internal", {}).get("entries", {}).get("methodproof", {}).get("enabled", False)


def install_skill() -> str | None:
    """Install MethodProof skill into OpenClaw. Returns None if OpenClaw not found."""
    if not _has_openclaw():
        return None

    if SKILLS_DIR.exists() and (SKILLS_DIR / "SKILL.md").exists():
        return "already installed"

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    src = SOURCE_SKILL_DIR / "SKILL.md"
    if src.exists():
        shutil.copy2(src, SKILLS_DIR / "SKILL.md")
        return str(SKILLS_DIR)
    return None
