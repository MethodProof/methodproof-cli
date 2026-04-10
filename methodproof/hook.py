"""Shell hook installer — logs commands to ~/.methodproof/commands.jsonl."""

import os
import sys
from pathlib import Path

MARKER = "# methodproof-hook"

_BASH = '''
# methodproof-hook
_mp_pre() { _MP_CMD="$BASH_COMMAND"; _MP_T=$SECONDS; }
_mp_post() {
  local ec=$? cmd="$_MP_CMD" dur=$(( (SECONDS - ${_MP_T:-$SECONDS}) * 1000 ))
  [ -z "$cmd" ] && return
  cmd="${cmd//\\\\/\\\\\\\\}"; cmd="${cmd//\\"/\\\\\\"}"
  echo "{\\"command\\":\\"$cmd\\",\\"exit_code\\":$ec,\\"duration_ms\\":$dur}" >> ~/.methodproof/commands.jsonl
  unset _MP_CMD
}
trap '_mp_pre' DEBUG
PROMPT_COMMAND="_mp_post${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
'''

_ZSH = '''
# methodproof-hook
_mp_pre() { _MP_CMD="$1"; _MP_T=$SECONDS; }
_mp_post() {
  local ec=$? cmd="$_MP_CMD" dur=$(( (SECONDS - ${_MP_T:-$SECONDS}) * 1000 ))
  [[ -z "$cmd" ]] && return
  cmd="${cmd//\\\\/\\\\\\\\}"; cmd="${cmd//\\"/\\\\\\"}"
  echo "{\\"command\\":\\"$cmd\\",\\"exit_code\\":$ec,\\"duration_ms\\":$dur}" >> ~/.methodproof/commands.jsonl
  unset _MP_CMD
}
autoload -Uz add-zsh-hook
add-zsh-hook preexec _mp_pre
add-zsh-hook precmd _mp_post
'''

_POWERSHELL = '''
# methodproof-hook
$global:_mpCmd = $null
$global:_mpT = $null

Set-PSReadLineOption -AddToHistoryHandler {
    param($line)
    $global:_mpCmd = $line
    $global:_mpT = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    return $true
}

function prompt {
    $ec = $LASTEXITCODE
    if ($global:_mpCmd) {
        $dur = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - $global:_mpT
        $cmd = $global:_mpCmd -replace '\\\\','\\\\\\\\' -replace '"','\\"'
        $line = "{`"command`":`"$cmd`",`"exit_code`":$ec,`"duration_ms`":$dur}"
        $logPath = Join-Path $HOME ".methodproof" "commands.jsonl"
        Add-Content -Path $logPath -Value $line
        $global:_mpCmd = $null
    }
    "PS $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) "
}
'''


def get_shell_rc() -> tuple[Path, str]:
    """Returns (rc_file_path, hook_text) for the current platform/shell."""
    if sys.platform == "win32":
        ps7 = Path.home() / "Documents" / "PowerShell"
        ps5 = Path.home() / "Documents" / "WindowsPowerShell"
        rc = (ps7 if ps7.exists() else ps5) / "Microsoft.PowerShell_profile.ps1"
        return rc, _POWERSHELL

    shell = os.environ.get("SHELL", "/bin/bash")
    is_zsh = "zsh" in shell
    rc = Path.home() / (".zshrc" if is_zsh else ".bashrc")
    return rc, _ZSH if is_zsh else _BASH


def install() -> str:
    rc, hook_text = get_shell_rc()
    shell = "PowerShell" if sys.platform == "win32" else os.path.basename(os.environ.get("SHELL", "bash"))
    if rc.exists() and MARKER in rc.read_text():
        return f"already installed ({shell}: {rc})"
    rc.parent.mkdir(parents=True, exist_ok=True)
    with rc.open("a") as f:
        f.write(hook_text)
    return f"{shell}: {rc}"


def is_installed() -> bool:
    rc, _ = get_shell_rc()
    return rc.exists() and MARKER in rc.read_text()
