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
