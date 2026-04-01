"""MethodProof MCP server — captures LLM prompts/completions as telemetry.

Exposes an `llm_query` tool that Claude Code can route through. Every call
logs the prompt and completion to the local bridge for graph construction.

Start: methodproof mcp-serve
Register: added to .claude/settings.local.json by `methodproof init`
"""

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

BRIDGE = "http://localhost:9877"


def _emit(event_type: str, metadata: dict[str, Any]) -> None:
    """Post event to local bridge. Fail silently."""
    try:
        data = json.dumps({"events": [{
            "type": event_type,
            "timestamp": time.time(),
            "metadata": metadata,
        }]}).encode()
        req = urllib.request.Request(
            f"{BRIDGE}/events", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


def serve() -> None:
    """Run the MCP server (stdio transport for Claude Code)."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("MCP server requires the 'mcp' package: pip install mcp", file=sys.stderr)
        sys.exit(1)

    mcp = FastMCP("methodproof")

    @mcp.tool()
    def llm_query(
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Query an LLM with telemetry capture. MethodProof records the prompt and response."""
        _emit("llm_prompt", {
            "model": model,
            "prompt_text": prompt[:5000],
            "token_count": len(prompt.split()),
            "temperature": temperature,
            "tools_available": [],
        })

        # This is a passthrough tool — Claude Code itself is the LLM.
        # The tool exists so the prompt/completion flow is captured.
        # Return a marker that tells Claude to proceed with its own reasoning.
        response = f"[MethodProof: prompt logged ({len(prompt)} chars, model={model})]"

        _emit("llm_completion", {
            "model": model,
            "response_text": response[:5000],
            "token_count": 0,
            "finish_reason": "tool_passthrough",
            "latency_ms": 0,
        })
        return response

    @mcp.tool()
    def log_thought(thought: str) -> str:
        """Log a reasoning step for process analysis."""
        _emit("user_prompt", {
            "prompt_preview": thought[:200],
            "prompt_length": len(thought),
        })
        return "Logged."

    mcp.run(transport="stdio")


def register_with_claude() -> str | None:
    """Add MethodProof MCP server to .claude/settings.local.json."""
    import shutil
    from pathlib import Path

    if not shutil.which("claude"):
        return None

    claude_dir = Path.home() / ".claude"
    settings_file = claude_dir / "settings.local.json"
    claude_dir.mkdir(exist_ok=True)

    settings: dict = {}
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
        except json.JSONDecodeError:
            settings = {}

    servers = settings.get("mcpServers", {})
    if "methodproof" in servers:
        return "already registered"

    mp_bin = shutil.which("methodproof")
    if not mp_bin:
        # Fallback: use python -m methodproof
        import sys
        mp_bin = sys.executable
        servers["methodproof"] = {
            "command": mp_bin,
            "args": ["-m", "methodproof", "mcp-serve"],
        }
    else:
        servers["methodproof"] = {
            "command": mp_bin,
            "args": ["mcp-serve"],
        }
    settings["mcpServers"] = servers
    settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    return str(settings_file)
