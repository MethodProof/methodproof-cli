"""Shell wrappers for AI CLI tools — captures prompts and outcomes.

Installs shell functions that wrap `codex`, `gemini`, `aider`, etc.
Each wrapper: logs the invocation to the bridge before + after execution.

The wrappers call the real binary (resolved at install time via `which`)
so there's no infinite recursion.
"""

import shutil
import sys

from methodproof.hook import get_shell_rc

MARKER = "# methodproof-ai-wrappers"

# Tools to wrap: (function_name, cli_binary_name)
TOOLS = [
    ("codex", "codex"),
    ("gemini", "gemini"),
    ("aider", "aider"),
]

_WRAPPER_TEMPLATE_UNIX = '''
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

_WRAPPER_TEMPLATE_PS = '''
function _mp_{name} {{
    $real = "{binary}"
    $prompt = $args -join ' '
    $tsStart = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    try {{
        $preview = $prompt.Substring(0, [Math]::Min(200, $prompt.Length)) -replace '"','\\"'
        $body = '{{"events":[{{"type":"ai_cli_start","timestamp":' + $tsStart + ',"metadata":{{"tool":"{name}","prompt_preview":"' + $preview + '","prompt_length":' + $prompt.Length + '}}}}]}}'
        Invoke-RestMethod -Uri http://localhost:9877/events -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 1 -ErrorAction SilentlyContinue | Out-Null
    }} catch {{}}
    & $real @args
    $ec = $LASTEXITCODE
    $tsEnd = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $dur = ($tsEnd - $tsStart) * 1000
    try {{
        $bodyEnd = '{{"events":[{{"type":"ai_cli_end","timestamp":' + $tsEnd + ',"metadata":{{"tool":"{name}","exit_code":' + $ec + ',"duration_ms":' + $dur + '}}}}]}}'
        Invoke-RestMethod -Uri http://localhost:9877/events -Method Post -Body $bodyEnd -ContentType 'application/json' -TimeoutSec 1 -ErrorAction SilentlyContinue | Out-Null
    }} catch {{}}
    return $ec
}}
'''


def install() -> list[str]:
    """Install AI CLI wrappers into the user's shell rc file. Returns list of wrapped tools."""
    rc, _ = get_shell_rc()
    is_windows = sys.platform == "win32"
    template = _WRAPPER_TEMPLATE_PS if is_windows else _WRAPPER_TEMPLATE_UNIX

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
        block_lines.append(template.format(name=name, binary=binary))
        if is_windows:
            block_lines.append(f"Set-Alias {name} _mp_{name}")
        else:
            block_lines.append(f"alias {name}='_mp_{name}'")
    block_lines.append(f"# end {MARKER}")
    block = "\n".join(block_lines)

    if rc.exists() and MARKER in rc.read_text():
        return [name for name, _ in available]

    rc.parent.mkdir(parents=True, exist_ok=True)
    with rc.open("a") as f:
        f.write("\n" + block + "\n")

    return [name for name, _ in available]


def is_installed() -> bool:
    rc, _ = get_shell_rc()
    return rc.exists() and MARKER in rc.read_text()
