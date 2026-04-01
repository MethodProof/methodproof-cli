"""Shell hook installer — logs commands to ~/.methodproof/commands.jsonl."""

import os
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


def install() -> str:
    shell = os.environ.get("SHELL", "/bin/bash")
    is_zsh = "zsh" in shell
    rc = Path.home() / (".zshrc" if is_zsh else ".bashrc")
    hook = _ZSH if is_zsh else _BASH

    if rc.exists() and MARKER in rc.read_text():
        return f"Already installed in {rc}"
    with rc.open("a") as f:
        f.write(hook)
    return str(rc)


def is_installed() -> bool:
    shell = os.environ.get("SHELL", "/bin/bash")
    rc = Path.home() / (".zshrc" if "zsh" in shell else ".bashrc")
    return rc.exists() and MARKER in rc.read_text()
