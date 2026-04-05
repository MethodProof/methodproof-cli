"""Register MethodProof MCP server with AI tools that support MCP."""

import json
import shutil
import time
from pathlib import Path

_MCP_CMD = shutil.which("methodproof") or "methodproof"
_MCP_ARGS = ["mcp-serve"]
_LOG_FILE = Path.home() / ".methodproof" / "hook_install.log"

# Global config: (config_path, json_key)
_TOOL_CONFIGS = {
    "cursor": (Path.home() / ".cursor" / "mcp.json", "mcpServers"),
    "roo": (Path.home() / ".roo" / "mcp.json", "mcpServers"),
    "kilo": (Path.home() / ".kilo" / "mcp.json", "mcpServers"),
    "amp": (Path.home() / ".amp" / "settings.json", "mcpServers"),
    "junie": (Path.home() / ".junie" / "mcp" / "mcp.json", "mcpServers"),
    "goose": (Path.home() / ".config" / "goose" / "mcp.json", "mcpServers"),
    "warp": (Path.home() / ".warp" / "mcp.json", "mcpServers"),
    "windsurf": (Path.home() / ".windsurf" / "mcp.json", "mcpServers"),
}

# Project-level configs (relative to cwd)
_PROJECT_CONFIGS = {
    "cursor": ("mcp.json", "mcpServers"),
    "roo": ("mcp.json", "mcpServers"),
}

_SERVER_ENTRY = {"command": _MCP_CMD, "args": _MCP_ARGS}


def _log(msg: str) -> None:
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_FILE.open("a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def _tool_installed(name: str) -> bool:
    """Check if a tool is installed via binary or config directory."""
    if shutil.which(name):
        return True
    config_path = _TOOL_CONFIGS[name][0]
    return config_path.parent.exists()


def _register(config_path: Path, key: str) -> str:
    """Merge methodproof entry into a config file. Returns status string."""
    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            config = {}

    servers = config.get(key, {})
    if "methodproof" in servers:
        return "already registered"

    servers["methodproof"] = _SERVER_ENTRY
    config[key] = servers
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    return str(config_path)


def install_all() -> dict[str, str]:
    """Register MCP server with all detected global tool configs."""
    results: dict[str, str] = {}
    for name, (path, key) in _TOOL_CONFIGS.items():
        if not _tool_installed(name):
            results[name] = "not installed"
            continue
        status = _register(path, key)
        _log(f"mcp_register global {name}: {status}")
        results[name] = status
    return results


def install_project(cwd: Path) -> dict[str, str]:
    """Register MCP server in project-level configs under cwd."""
    results: dict[str, str] = {}
    for name, (filename, key) in _PROJECT_CONFIGS.items():
        dot_dir = cwd / f".{name}"
        if not dot_dir.exists():
            results[name] = "no project config"
            continue
        config_path = dot_dir / filename
        status = _register(config_path, key)
        _log(f"mcp_register project {name} ({cwd}): {status}")
        results[name] = status
    return results
