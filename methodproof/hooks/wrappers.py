"""Shell wrappers for AI CLI tools — captures prompts and outcomes.

Installs shell functions that wrap `codex`, `gemini`, `aider`, etc.
Each wrapper: logs the invocation to the bridge before + after execution.

The wrappers call the real binary (resolved at install time via `which`)
so there's no infinite recursion.
"""

import os
import shutil
from pathlib import Path

from methodproof.config import DIR

MARKER = "# methodproof-ai-wrappers"

# Tools to wrap: (function_name, cli_binary_name)
TOOLS = [
    ("codex", "codex"),
    ("gemini", "gemini"),
    ("aider", "aider"),
]

_WRAPPER_TEMPLATE = '''
_mp_{name}() {{
  local real="{binary}"
  local prompt="$*"
  local ts_start=$(date +%s)

  # Log invocation to bridge (pre)
  curl -s --max-time 1 -X POST http://localhost:9877/events \
    -H "Content-Type: application/json" \
    -d '{{"events":[{{"type":"ai_cli_start","timestamp":'$ts_start',"metadata":{{"tool":"{name}","prompt_preview":"'"$(echo "$prompt" | head -c 200 | sed 's/"/\\\\"/g')"'","prompt_length":'${{#prompt}}' }}}}]}}' \
    >/dev/null 2>&1 || true

  # Run the real binary
  "$real" "$@"
  local ec=$?
  local ts_end=$(date +%s)
  local dur=$(( (ts_end - ts_start) * 1000 ))

  # Log result to bridge (post)
  curl -s --max-time 1 -X POST http://localhost:9877/events \
    -H "Content-Type: application/json" \
    -d '{{"events":[{{"type":"ai_cli_end","timestamp":'$ts_end',"metadata":{{"tool":"{name}","exit_code":'$ec',"duration_ms":'$dur'}}}}]}}' \
    >/dev/null 2>&1 || true

  return $ec
}}
'''


def install() -> list[str]:
    """Install AI CLI wrappers into the user's shell rc file. Returns list of wrapped tools."""
    shell = os.environ.get("SHELL", "/bin/bash")
    rc = Path.home() / (".zshrc" if "zsh" in shell else ".bashrc")

    # Check which tools exist
    available: list[tuple[str, str]] = []
    for name, binary in TOOLS:
        real_path = shutil.which(binary)
        if real_path:
            available.append((name, real_path))

    if not available:
        return []

    # Build wrapper block
    block_lines = [MARKER]
    for name, binary in available:
        wrapper = _WRAPPER_TEMPLATE.format(name=name, binary=binary)
        block_lines.append(wrapper)
        # Alias the function name to shadow the binary
        block_lines.append(f"alias {name}='_mp_{name}'")
    block_lines.append(f"# end {MARKER}")
    block = "\n".join(block_lines)

    # Check if already installed
    if rc.exists() and MARKER in rc.read_text():
        return [name for name, _ in available]

    with rc.open("a") as f:
        f.write("\n" + block + "\n")

    return [name for name, _ in available]


def is_installed() -> bool:
    shell = os.environ.get("SHELL", "/bin/bash")
    rc = Path.home() / (".zshrc" if "zsh" in shell else ".bashrc")
    return rc.exists() and MARKER in rc.read_text()
