"""MethodProof CLI. See how you code.

Usage:
    methodproof init              Install hooks, configure capture
    methodproof start [--dir .]   Start recording a session
    methodproof stop              Stop recording, build process graph
    methodproof view [id]         View session graph in browser
    methodproof log               List local sessions
    methodproof review [id]       Review session data before pushing
    methodproof login             Connect to platform (opens browser)
    methodproof push [id]         Upload privately to your account
    methodproof publish [id]      Make session public (applies redaction defaults)
    methodproof consent           Review or change capture, research, and redaction settings
    methodproof extension pair    Pair browser extension to active session
    methodproof extension status  Check extension connection
    methodproof extension install Open Chrome Web Store listing
"""

import argparse
import json
import os
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, UTC

from pathlib import Path

from methodproof import config, store, graph, hook, repos

PIDFILE = config.DIR / "methodproof.pid"

_RAINBOW = [
    "\033[91m",       # red
    "\033[38;5;208m", # orange
    "\033[93m",       # yellow
    "\033[92m",       # green
    "\033[96m",       # cyan
    "\033[94m",       # blue
    "\033[95m",       # magenta
]
_RESET = "\033[0m"


def _rainbow(text: str) -> str:
    if not sys.stdout.isatty():
        return text
    chars = []
    ci = 0
    for ch in text:
        if ch == " ":
            chars.append(ch)
        else:
            chars.append(f"{_RAINBOW[ci % len(_RAINBOW)]}{ch}")
            ci += 1
    return "".join(chars) + _RESET


def _banner() -> str:
    return f"MethodProof — {_rainbow('Full Spectrum')}"


def _app_url(api_url: str) -> str:
    """Derive dashboard URL from API URL."""
    if "localhost" in api_url or "127.0.0.1" in api_url:
        return "http://localhost:5173"
    return api_url.replace("api.", "app.", 1)


def _print_intro() -> None:
    """Show the 3-layer architecture intro with rainbow borders."""
    if not sys.stdout.isatty():
        _print_intro_plain()
        return

    W = "\033[1;97m"
    G = "\033[92m"
    C = "\033[96m"
    Y = "\033[93m"
    D = "\033[90m"
    R = _RESET

    bar = _rainbow("━" * 51)

    print(f"\n  {bar}\n")
    print(f"       {W}M E T H O D P R O O F{R}")
    print(f"    {D}See how you code. Prove how you build.{R}")
    print(f"\n  {bar}\n")
    print(f"   ┌────────────────────────────────────────────────┐")
    print(f"   │  {Y}SHARE{R}     push · publish · anonymous · live   │")
    print(f"   ├────────────────────────────────────────────────┤")
    print(f"   │  {C}GRAPH{R}     knowledge graph · moments · edges   │")
    print(f"   ├────────────────────────────────────────────────┤")
    print(f"   │  {G}CAPTURE{R}   hooks · proxy · plugin              │")
    print(f"   └────────────────────────────────────────────────┘")
    print()
    print(f"   {D}1.{R} {G}mp start{R}       begin recording")
    print(f"   {D}2.{R} code normally  {D}MethodProof watches silently{R}")
    print(f"   {D}3.{R} {G}mp stop{R}        build your process graph")
    print(f"   {D}4.{R} {G}mp push{R}        upload to your profile")
    print()
    print(f"   {D}Your process is worth studying.{R}")
    print(f"   {D}All data stays local until you push.{R}\n")


def _print_intro_plain() -> None:
    print("\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    print("       M E T H O D P R O O F")
    print("    See how you code. Prove how you build.")
    print("\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    print("   ┌────────────────────────────────────────────────┐")
    print("   │  SHARE     push · publish · anonymous · live   │")
    print("   ├────────────────────────────────────────────────┤")
    print("   │  GRAPH     knowledge graph · moments · edges   │")
    print("   ├────────────────────────────────────────────────┤")
    print("   │  CAPTURE   hooks · proxy · plugin              │")
    print("   └────────────────────────────────────────────────┘")
    print()
    print("   1. mp start       begin recording")
    print("   2. code normally  MethodProof watches silently")
    print("   3. mp stop        build your process graph")
    print("   4. mp push        upload to your profile")
    print()
    print("   Your process is worth studying.")
    print("   All data stays local until you push.\n")


_ALIAS_MARKER = "# methodproof-alias"


def _install_alias() -> None:
    """Add `alias mp=methodproof` to the user's shell rc file."""
    rc, _ = hook.get_shell_rc()
    if rc.exists() and _ALIAS_MARKER in rc.read_text():
        return
    rc.parent.mkdir(parents=True, exist_ok=True)
    alias = '\n# methodproof-alias\nSet-Alias mp methodproof\n' if sys.platform == "win32" \
        else '\n# methodproof-alias\nalias mp="methodproof"\n'
    with rc.open("a") as f:
        f.write(alias)


def _print_journal_intro(credits: int) -> None:
    """Show journal mode introduction with remaining credits."""
    print("  ┌─────────────────────────────────────────────────────┐")
    print("  │  Journal Mode — full content capture                │")
    print("  └─────────────────────────────────────────────────────┘")
    print(f"  You have {credits} free journal credit{'s' if credits != 1 else ''} "
          f"(sessions up to {config.FREE_JOURNAL_MAX_HOURS}h each).")
    print()
    print("  By default, MethodProof captures structural metadata only —")
    print("  file paths, line counts, timing, tool names. Journal mode")
    print("  preserves the full picture: prompts, AI responses, diffs,")
    print("  and terminal output. All encrypted (AES-256-GCM).")
    print()
    print("  Try it:  mp start --journal")
    print("  Toggle:  mp journal on / off / status")
    print()


def _run_consent(cfg: dict) -> dict:
    """Simplified consent flow: accept defaults or customize."""
    print(f"\n{_banner()}\n")
    print("  Welcome, fellow researcher.\n")
    print("  All data stays local in ~/.methodproof/. Nothing leaves your")
    print("  machine unless you explicitly run `mp push` or `mp publish`.\n")
    print("  MethodProof records structural metadata about your workflow:")
    print("  commands, file changes, git commits, AI interactions, and more.")
    print("  No code content is stored by default.\n")

    choice = input("  Enable recommended capture? [Y/n/c to customize]: ").strip().lower()

    if choice in ("c", "customize"):
        return _run_consent_detailed(cfg)

    if choice in ("n", "no"):
        # Minimal: only file changes + git commits
        capture = {k: False for k in config.STANDARD_CATEGORIES}
        capture["file_changes"] = True
        capture["git_commits"] = True
        capture["code_capture"] = False
        cfg["capture"] = capture
        cfg["research_consent"] = False
        cfg["publish_redact"] = dict(config._DEFAULTS["publish_redact"])
        cfg["consent_acknowledged"] = True
        credits = cfg.get("journal_credits", config._DEFAULTS["journal_credits"])
        print("\n  Minimal capture enabled (file changes + git commits).\n")
        _print_journal_intro(credits)
        print("  Customize anytime: `methodproof consent`\n")
        return cfg

    # Default: all 10 standard on, code_capture off
    cfg["capture"] = dict(config._DEFAULTS["capture"])
    cfg["research_consent"] = False
    cfg["publish_redact"] = dict(config._DEFAULTS["publish_redact"])
    cfg["consent_acknowledged"] = True
    credits = cfg.get("journal_credits", config._DEFAULTS["journal_credits"])
    print(f"\n  {_rainbow('Full Spectrum')} enabled — free live streaming unlocked.\n")
    _print_journal_intro(credits)
    print("  Customize anytime: `methodproof consent`\n")
    return cfg


def _run_consent_detailed(cfg: dict) -> dict:
    """Full interactive consent flow with three sections: capture, research, redaction."""
    capture = cfg.get("capture", dict(config._DEFAULTS["capture"]))
    publish_redact = cfg.get("publish_redact", dict(config._DEFAULTS["publish_redact"]))
    std = config.STANDARD_CATEGORIES

    # --- Section 1: Capture ---
    print()
    print("=" * 60)
    print("  What gets recorded locally")
    print("=" * 60)
    print()
    print("  These 10 categories are structural metadata only.")
    print("  Enable all 10 to unlock free live streaming.\n")

    while True:
        for i, key in enumerate(std, 1):
            mark = "x" if capture.get(key, True) else " "
            desc = config.CAPTURE_DESCRIPTIONS[key]
            print(f"  [{mark}] {i}. {key:<20s} {desc}")

        std_enabled = sum(1 for k in std if capture.get(k, True))
        is_full = std_enabled == len(std)
        label = _rainbow("Full Spectrum") if is_full else f"{std_enabled}/{len(std)} categories"
        print(f"\n  {label} enabled", end="")
        if is_full:
            print("  |  Free live streaming unlocked")
        else:
            print(f"  |  Enable all 10 for free live streaming")

        # Code capture (separate, premium)
        cc_mark = "x" if capture.get("code_capture", False) else " "
        print(f"\n  [{cc_mark}] 0. {'code_capture':<20s} {config.CAPTURE_DESCRIPTIONS['code_capture']}")

        print("\n  Toggle: enter number (0 for code capture) | a = all 10 on | n = all off | done = confirm\n")

        choice = input("  > ").strip().lower()
        if choice in ("done", "d", ""):
            if std_enabled == 0:
                print("  At least one category must be enabled.\n")
                continue
            break
        elif choice == "a":
            for k in std:
                capture[k] = True
        elif choice == "n":
            for k in std:
                capture[k] = False
        elif choice == "0":
            capture["code_capture"] = not capture.get("code_capture", False)
        elif choice.isdigit() and 1 <= int(choice) <= len(std):
            k = std[int(choice) - 1]
            capture[k] = not capture.get(k, True)
        else:
            print(f"  Unknown input: {choice}\n")
        print()

    cfg["capture"] = capture

    if is_full:
        print(f"\n  {_rainbow('Full Spectrum')} unlocked.\n")

    # --- Section 2: Research Data ---
    print("=" * 60)
    print("  Contribute to AI research (optional)")
    print("=" * 60)
    print()

    if not is_full:
        print("  Research contribution requires all 10 standard categories enabled.")
        print("  You can enable this later via `methodproof consent`.\n")
        cfg["research_consent"] = False
    else:
        print("  Opt in to contribute anonymized, aggregated process patterns")
        print("  to improve AI developer tools and engineering research.")
        print()
        print("  What gets shared: action types, durations, tool selections,")
        print("  behavioral patterns, and scores.")
        print("  What never leaves: your code, prompts, company IP.")
        print()
        print("  This consent is separate from capture. You can withdraw anytime.")
        print("  Your data is stripped of all identifying information before export.\n")

        choice = input("  Contribute to research? [y/N]: ").strip().lower()
        cfg["research_consent"] = choice in ("y", "yes")
        if cfg["research_consent"]:
            print("  Research contribution enabled. Thank you.\n")
        else:
            print("  No problem. You can opt in anytime via `methodproof consent`.\n")

    # --- Section 3: Publish Redaction ---
    print("=" * 60)
    print("  Default redactions for public sessions")
    print("=" * 60)
    print()
    print("  `mp push` uploads privately to your account (nothing public).")
    print("  `mp publish` makes a session public. These defaults control")
    print("  what gets redacted from public views.\n")

    redactable = [
        ("command_output", "Terminal output (first 500 chars)"),
        ("ai_prompts", "AI prompt text"),
        ("ai_responses", "AI response text"),
        ("code_capture", "File diffs and git patches"),
    ]

    while True:
        for i, (key, desc) in enumerate(redactable, 1):
            mark = "x" if publish_redact.get(key, True) else " "
            print(f"  [{mark}] {i}. Redact: {desc}")

        print("\n  Checked = redacted from public view. Toggle: number | done = confirm\n")

        choice = input("  > ").strip().lower()
        if choice in ("done", "d", ""):
            break
        elif choice.isdigit() and 1 <= int(choice) <= len(redactable):
            k = redactable[int(choice) - 1][0]
            publish_redact[k] = not publish_redact.get(k, True)
        else:
            print(f"  Unknown input: {choice}\n")
        print()

    cfg["publish_redact"] = publish_redact
    cfg["consent_acknowledged"] = True
    return cfg


def cmd_init(args: argparse.Namespace) -> None:
    config.ensure_dirs()
    cfg = config.load()
    if getattr(args, "force", False):
        for key in ("consent_acknowledged", "auto_update_offered", "alias_offered", "local_ai_ports_offered", "ui_mode_offered"):
            cfg.pop(key, None)
        config.save(cfg)

    # TUI wizard — runs when nothing is set up yet, or on --force, or when ui_mode is on
    needs_setup = not cfg.get("consent_acknowledged")
    use_ui = needs_setup or _resolve_ui(args, cfg)
    if use_ui:
        try:
            _tui_guard()
            from methodproof.tui.init import run as tui_init
            tui_init(cfg)
            return
        except SystemExit:
            pass  # textual not installed — fall through to classic

    if not cfg.get("consent_acknowledged"):
        cfg = _run_consent(cfg)
        config.save(cfg)
        if cfg.get("token"):
            cfg["_pending_research_sync"] = True
            config.save(cfg)
            from methodproof.sync import sync_research_consent
            sync_research_consent(cfg["token"], cfg["api_url"])
        print()

    capture = cfg.get("capture", {})
    store.init_db()

    # Offer auto-update (recommended)
    if not cfg.get("auto_update_offered"):
        answer = input("Enable auto-update (recommended)? [Y/n]: ").strip().lower()
        cfg["auto_update_offered"] = True
        cfg["auto_update"] = answer != "n"
        print(f"Auto-update: {'ON — updates install before each session' if cfg['auto_update'] else 'OFF — toggle with: mp update --auto'}")
        config.save(cfg)

    # Offer mp alias
    if not cfg.get("alias_offered"):
        answer = input("Install `mp` as a shorthand alias? [Y/n]: ").strip().lower()
        cfg["alias_offered"] = True
        if answer != "n":
            _install_alias()
            cfg["alias_installed"] = True
            print("Alias: mp -> methodproof")
        else:
            print("Alias: skipped")
        config.save(cfg)

    # Offer classic CLI mode (TUI is default)
    if not cfg.get("ui_mode_offered"):
        cfg["ui_mode_offered"] = True
        answer = input("Prefer classic terminal output instead of the rich TUI? [y/N]: ").strip().lower()
        if answer == "y":
            cfg["ui_mode"] = False
            print("Output mode: classic  (toggle anytime with: mp ui on/off)")
        else:
            cfg["ui_mode"] = True
            print("Output mode: rich TUI  (toggle anytime with: mp ui off)")
        config.save(cfg)

    # Shell hook — needed for terminal commands
    if capture.get("terminal_commands", True):
        rc = hook.install()
        print(f"Shell hook: {rc}")
    else:
        print("Shell hook: skipped (terminal_commands disabled)")

    # AI hooks — only install if ai_prompts or ai_responses enabled
    ai_enabled = capture.get("ai_prompts", True) or capture.get("ai_responses", True)

    if ai_enabled:
        from methodproof.hooks.install import install as install_claude_hooks
        result = install_claude_hooks()
        if result is None:
            print("Claude Code: not found (hooks skipped)")
        else:
            print(f"Claude Code hooks: {result}")

        from methodproof.mcp import register_with_claude
        mcp_result = register_with_claude()
        if mcp_result is None:
            print("Claude Code: MCP server not registered (skipped)")
        elif mcp_result == "already registered":
            print("Claude Code MCP: already registered")
        else:
            print(f"Claude Code MCP: registered in {mcp_result}")

        from methodproof.hooks.wrappers import install as install_wrappers
        wrapped = install_wrappers()
        if wrapped:
            print(f"AI CLI wrappers: {', '.join(wrapped)}")
        else:
            print("AI CLI wrappers: no tools found (codex, gemini, aider)")

        from methodproof.hooks.openclaw_install import install as install_openclaw_hooks, install_skill
        oc_result = install_openclaw_hooks()
        if oc_result is None:
            print("AI Agent Graph: OpenClaw not found (hooks + skill skipped)")
        else:
            print(f"AI Agent Graph hooks: {oc_result}")
            skill_result = install_skill()
            if skill_result:
                print(f"AI Agent Graph skill: {skill_result}")
    else:
        print("AI hooks: skipped (ai_prompts and ai_responses disabled)")

    # Local AI ports — capture traffic from local LLM servers
    if ai_enabled and not cfg.get("local_ai_ports_offered"):
        answer = input("Run any local AI models (Ollama, LM Studio, vLLM, etc.)? [y/N]: ").strip().lower()
        cfg["local_ai_ports_offered"] = True
        if answer == "y":
            raw = input("Enter ports (comma-separated, e.g. 8080,5000,7860): ").strip()
            ports = [int(p.strip()) for p in raw.split(",") if p.strip().isdigit()]
            cfg["local_ai_ports"] = ports
            if ports:
                print(f"Local AI ports: {', '.join(str(p) for p in ports)} (proxy will decode these)")
            else:
                print("Local AI ports: none added")
        else:
            cfg["local_ai_ports"] = []
            print("Local AI ports: skipped (built-in: Ollama 11434, Jan 1234)")
        config.save(cfg)

    # Signing keypair for attestation
    from methodproof.integrity import has_keypair
    if not has_keypair():
        try:
            from methodproof.integrity import generate_keypair
            pub = generate_keypair()
            print(f"Signing key: generated ({len(pub)} bytes)")
        except ImportError:
            print("Signing key: skipped (install methodproof[signing])")
    else:
        print("Signing key: exists")

    _print_intro()
    print("  Restart your shell or run this to activate now:\n")
    print("    eval \"$(methodproof shell-hook)\"\n")


def cmd_shell_hook(_args: argparse.Namespace) -> None:
    """Print the shell hook text for the current shell (for eval)."""
    _, hook_text = hook.get_shell_rc()
    print(hook_text.strip())


# ── TUI mode helpers ──────────────────────────────────────────────────────────

def _add_ui_flags(parser: argparse.ArgumentParser) -> None:
    """Add --ui / --no-ui flags to a subparser."""
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--ui", dest="ui", action="store_true", default=None, help="Force TUI output")
    g.add_argument("--no-ui", dest="ui", action="store_false", help="Force classic output")


def _tui_guard() -> None:
    """Raise SystemExit with install hint if textual is not installed."""
    import importlib.util
    if importlib.util.find_spec("textual") is None:
        raise SystemExit(
            "TUI mode requires the ui extras.\n"
            "Install with:  pip install methodproof[ui]\n"
            "Or switch back: mp ui off"
        )


def _resolve_ui(args: argparse.Namespace, cfg: dict) -> bool:
    """Return True if TUI mode should be used for this invocation."""
    flag = getattr(args, "ui", None)  # True / False / None (not specified)
    if flag is True:
        return True
    if flag is False:
        return False
    return cfg.get("ui_mode", True)


def cmd_ui(args: argparse.Namespace) -> None:
    """Toggle or report TUI mode."""
    import importlib.util
    cfg = config.load()
    sub = getattr(args, "ui_cmd", None)
    if sub == "on":
        cfg["ui_mode"] = True
        config.save(cfg)
        print("TUI mode: on  (mp consent, mp log, mp start, mp status, mp review)")
        if importlib.util.find_spec("textual") is None:
            print("Install libraries:  pip install methodproof[ui]")
    elif sub == "off":
        cfg["ui_mode"] = False
        config.save(cfg)
        print("TUI mode: off  (classic terminal output)")
    else:
        mode = cfg.get("ui_mode", True)
        installed = importlib.util.find_spec("textual") is not None
        print(f"TUI mode:  {'on' if mode else 'off'}")
        print(f"Libraries: {'installed ✓' if installed else 'not installed  (pip install methodproof[ui])'}")


def _print_commands() -> None:
    """Print color coded command reference."""
    if not sys.stdout.isatty():
        _print_commands_plain()
        return

    _W = "\033[97m"   # white/bold
    _G = "\033[92m"   # green
    _C = "\033[96m"   # cyan
    _Y = "\033[93m"   # yellow
    _M = "\033[95m"   # magenta
    _D = "\033[90m"   # dim
    R = _RESET

    print(f"  {_W}RECORD{R}")
    print(f"    {_G}mp start{R}              Start recording a session")
    print(f"    {_G}mp stop{R}               Stop recording, build process graph")
    print(f"    {_G}mp start --live{R}        Stream your graph privately (only you can view)")
    print(f"    {_G}mp start --live-public{R} Stream your graph publicly (shareable link)")
    print(f"    {_G}mp start --journal{R}    Full content capture (2 free credits, then Pro)")
    print(f"    {_G}mp start --e2e{R}         Encrypt session with your personal key {_D}(Pro){R}")
    print(f"    {_G}mp journal on{R}         Enable persistent journal mode")
    print(f"    {_G}mp journal status{R}     Check journal mode and remaining credits")
    print()
    print(f"  {_W}REVIEW{R}")
    print(f"    {_C}mp view{R}  {_D}[id]{R}          View session graph in browser")
    print(f"    {_C}mp review{R} {_D}[id]{R}         Inspect session data before pushing")
    print(f"    {_C}mp log{R}                List all local sessions")
    print()
    print(f"  {_W}SHARE{R}")
    print(f"    {_Y}mp push{R}  {_D}[id]{R}          Upload privately to your account")
    print(f"    {_Y}mp push --local{R}        Push to local dev API {_D}(localhost:8000){R}")
    print(f"    {_Y}mp publish{R} {_D}[id]{R}        Make session public (redaction applied)")
    print(f"    {_Y}mp publish --anonymous{R}  Public but identity hidden {_D}(Pro){R}")
    print(f"    {_Y}mp tag{R} {_D}<id> <tags>{R}     Tag a session")
    print()
    print(f"  {_W}ENCRYPTION{R}")
    print(f"    {_C}mp e2e on{R}              Enable E2E encryption (generates key on first use)")
    print(f"    {_C}mp e2e off{R}             Disable E2E mode (key stays in keychain)")
    print(f"    {_C}mp e2e status{R}          Show E2E mode and key status")
    print(f"    {_C}mp e2e recover{R}         Recover key from recovery passphrase")
    print(f"    {_C}mp e2e release{R} {_D}<id>{R}   Release a session from E2E encryption")
    print()
    print(f"  {_W}EXTENSION{R}")
    print(f"    {_C}mp extension pair{R}      Pair browser extension to active session")
    print(f"    {_C}mp extension status{R}    Check extension connection")
    print(f"    {_C}mp extension install{R}   Open Chrome Web Store")
    print()
    print(f"  {_W}PROXY{R}")
    print(f"    {_C}mp proxy start{R}         Start local AI API proxy {_D}(deep capture){R}")
    print(f"    {_C}mp proxy stop{R}          Stop proxy")
    print(f"    {_C}mp proxy status{R}        Show proxy status")
    print(f"    {_C}mp proxy cert{R}          CA certificate install instructions")
    print()
    print(f"  {_W}ACCOUNT{R}")
    print(f"    {_M}mp login{R}              Connect to platform (opens browser)")
    print(f"    {_M}mp accounts{R}           List all accounts on this device")
    print(f"    {_M}mp switch{R} {_D}[query]{R}     Quick-swap to another account")
    print(f"    {_M}mp consent{R}            Change capture, research, and redaction settings")
    print(f"    {_M}mp lock{R}                Destroy local encryption key {_D}(reversible){R}")
    print(f"    {_M}mp lock --purge{R}        Delete all local data {_D}(irreversible){R}")
    print(f"    {_M}mp reset{R}               Clear login and consent (keeps sessions)")
    print(f"    {_M}mp delete{R} {_D}<id>{R}        Delete a session and all its data")
    print(f"    {_M}mp update{R}              Update to the latest version")
    print(f"    {_M}mp update --auto{R}      Toggle auto-update on  {_D}(recommended){R}")
    print(f"    {_M}mp update --no-auto{R}   Toggle auto-update off")
    print(f"    {_M}mp uninstall{R}           Remove all hooks, data, and config")
    print()
    print(f"  {_W}ENVIRONMENT{R}")
    print(f"    {_D}METHODPROOF_API_URL{R}    Override API endpoint {_D}(e.g. http://localhost:8000){R}")
    print()
    print(f"  {_D}To view this at any time run: mp help{R}\n")


def _print_commands_plain() -> None:
    print("  RECORD")
    print("    mp start              Start recording a session")
    print("    mp stop               Stop recording, build process graph")
    print("    mp start --live       Stream your graph privately")
    print("    mp start --live-public  Stream your graph publicly (shareable link)")
    print("    mp start --journal    Full content capture (2 free credits, then Pro)")
    print("    mp start --e2e        Encrypt session with your personal key (Pro)")
    print("    mp journal on         Enable persistent journal mode")
    print("    mp journal status     Check journal mode and remaining credits")
    print()
    print("  REVIEW")
    print("    mp view  [id]         View session graph in browser")
    print("    mp review [id]        Inspect session data before pushing")
    print("    mp log                List all local sessions")
    print()
    print("  SHARE")
    print("    mp push  [id]         Upload privately to your account")
    print("    mp push --local       Push to local dev API (localhost:8000)")
    print("    mp publish [id]       Make session public (redaction applied)")
    print("    mp publish --anonymous  Public but identity hidden (Pro)")
    print("    mp tag <id> <tags>    Tag a session")
    print()
    print("  ENCRYPTION")
    print("    mp e2e on             Enable E2E encryption (generates key on first use)")
    print("    mp e2e off            Disable E2E mode (key stays in keychain)")
    print("    mp e2e status         Show E2E mode and key status")
    print("    mp e2e recover        Recover key from recovery passphrase")
    print("    mp e2e release <id>   Release a session from E2E encryption")
    print()
    print("  EXTENSION")
    print("    mp extension pair     Pair browser extension to active session")
    print("    mp extension status   Check extension connection")
    print("    mp extension install  Open Chrome Web Store")
    print()
    print("  PROXY")
    print("    mp proxy start        Start local AI API proxy (deep capture)")
    print("    mp proxy stop         Stop proxy")
    print("    mp proxy status       Show proxy status")
    print("    mp proxy cert         CA certificate install instructions")
    print()
    print("  ACCOUNT")
    print("    mp login              Connect to platform (opens browser)")
    print("    mp accounts           List all accounts on this device")
    print("    mp switch [query]     Quick-swap to another account")
    print("    mp consent            Change capture, research, and redaction settings")
    print("    mp lock               Destroy local encryption key (reversible)")
    print("    mp lock --purge       Delete all local data (irreversible)")
    print("    mp reset              Clear login and consent (keeps sessions)")
    print("    mp delete <id>        Delete a session and all its data")
    print("    mp update             Update to the latest version")
    print("    mp update --auto      Toggle auto-update on (recommended)")
    print("    mp update --no-auto   Toggle auto-update off")
    print("    mp uninstall          Remove all hooks, data, and config")
    print()
    print("  ENVIRONMENT")
    print("    METHODPROOF_API_URL   Override API endpoint (e.g. http://localhost:8000)")
    print()
    print("  To view this at any time run: mp help\n")


def cmd_uninstall(args: argparse.Namespace) -> None:
    """Remove all MethodProof hooks, data, and config."""
    import shutil

    keep_sessions = getattr(args, "keep_sessions", False)

    if not args.force:
        sessions = store.list_sessions()
        unsynced = [s for s in sessions if not s["synced"]]
        if sessions:
            print(f"  {len(sessions)} session(s) on disk ({len(unsynced)} not pushed).")
        answer = input("\n  Remove all MethodProof hooks and config? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("  Cancelled.")
            return
        if sessions and not keep_sessions:
            keep = input("  Keep session data? [Y/n]: ").strip().lower()
            keep_sessions = keep != "n"

    removed = []

    # Shell hook
    rc, _ = hook.get_shell_rc()
    if rc.exists():
        text = rc.read_text()
        if hook.MARKER in text:
            lines = text.split("\n")
            clean = []
            skip = False
            for line in lines:
                if hook.MARKER in line:
                    skip = True
                    continue
                if skip and line.strip() == "":
                    skip = False
                    continue
                if skip:
                    continue
                clean.append(line)
            rc.write_text("\n".join(clean))
            removed.append(f"Shell hook from {rc}")

        # mp alias
        if _ALIAS_MARKER in rc.read_text():
            text = rc.read_text()
            lines = text.split("\n")
            clean = [l for l in lines if _ALIAS_MARKER not in l and "alias mp=" not in l and "Set-Alias mp" not in l]
            rc.write_text("\n".join(clean))
            removed.append(f"mp alias from {rc}")

    # Claude Code hooks
    claude_dir = Path.home() / ".claude"
    for p in [
        claude_dir / "hooks" / "methodproof",
        claude_dir / "skills" / "methodproof",
    ]:
        if p.exists():
            shutil.rmtree(p)
            removed.append(str(p))

    # OpenClaw hooks
    openclaw_dir = Path.home() / ".openclaw"
    for p in [
        openclaw_dir / "hooks" / "methodproof",
        openclaw_dir / "skills" / "methodproof",
    ]:
        if p.exists():
            shutil.rmtree(p)
            removed.append(str(p))

    # Data directory
    if config.DIR.exists():
        if keep_sessions and config.DB_PATH.exists():
            # Remove everything except the session database
            for item in config.DIR.iterdir():
                if item == config.DB_PATH:
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                removed.append(str(item))
            removed.append(f"Kept: {config.DB_PATH}")
        else:
            shutil.rmtree(config.DIR)
            removed.append(str(config.DIR))

    if removed:
        print("\n  Removed:")
        for r in removed:
            print(f"    {r}")
    print("\n  To remove the CLI itself: pip uninstall methodproof")
    if keep_sessions:
        print(f"  Session data preserved at: {config.DB_PATH}")
        print("  Re-install and run `mp init` to resume.")
    print("  Restart your shell to clear hooks.\n")


def cmd_lock(args: argparse.Namespace) -> None:
    """Destroy local key access. --purge deletes DB entirely."""
    cfg = config.load()
    account_id = cfg.get("account_id", "")
    if not account_id:
        print("No account linked. Nothing to lock.")
        return
    purge = getattr(args, "purge", False)
    if not args.force:
        action = "DELETE all local data" if purge else "lock encrypted fields"
        answer = input(f"  {action}? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("  Cancelled.")
            return
    from methodproof.lock import lock
    lock(account_id, purge=purge)
    print("  Done.\n")


def cmd_reset(args: argparse.Namespace) -> None:
    """Wipe login credentials and consent config. Sessions and hooks kept."""
    cfg = config.load()
    if not args.force:
        answer = input("  Clear login and consent settings? Sessions and hooks are kept. [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("  Cancelled.")
            return
    for key in ("token", "refresh_token", "email", "e2e_key",
                "account_id", "last_auth_at", "master_key_fingerprint"):
        cfg[key] = config._DEFAULTS[key]
    for key in ("capture", "research_consent", "publish_redact", "consent_acknowledged",
                "journal_mode", "journal_credits", "auto_update", "auto_update_offered"):
        cfg[key] = config._DEFAULTS.get(key)
    config.save(cfg)
    cleared = ["login token", "refresh token", "email", "e2e key",
               "account id", "master key fingerprint",
               "capture consent", "research consent", "redaction defaults",
               "journal mode", "auto-update"]
    print("  Cleared:")
    for c in cleared:
        print(f"    {c}")
    print("\n  Run `mp init` to reconfigure, or `mp login` to reconnect.\n")


def cmd_consent(args: argparse.Namespace) -> None:
    """Review or change capture, research, and redaction settings."""
    cfg = config.load()
    if _resolve_ui(args, cfg):
        _tui_guard()
        from methodproof.tui.consent import run as tui_consent
        cfg = tui_consent(cfg)
        config.save(cfg)
        if cfg.get("token"):
            cfg["_pending_research_sync"] = True
            config.save(cfg)
            from methodproof.sync import sync_research_consent
            sync_research_consent(cfg["token"], cfg["api_url"])
        return
    # Classic flow
    print(f"\n{_banner()}\n")
    cfg = _run_consent_detailed(cfg)
    config.save(cfg)
    if cfg.get("token"):
        cfg["_pending_research_sync"] = True
        config.save(cfg)
        from methodproof.sync import sync_research_consent
        sync_research_consent(cfg["token"], cfg["api_url"])
    print(f"\n{_banner()} settings saved.\n")
    _print_commands()


def cmd_journal(args: argparse.Namespace) -> None:
    """Journal mode — full content capture."""
    subcmd = getattr(args, "journal_cmd", None)
    cfg = config.load()
    credits = cfg.get("journal_credits", 0)

    if subcmd == "on":
        print("Journal Mode — Full Content Capture\n")
        print("When enabled, MethodProof persists full content alongside structural data:")
        print("  • Full prompt text (not just length)")
        print("  • Full AI completion text (not just length)")
        print("  • Full file diffs and git patches")
        print("  • Terminal output (not just commands)")
        print("  • Tool call parameters and results\n")
        print("All content is encrypted (AES-256-GCM) and subject to your consent settings.\n")
        if credits > 0:
            print(f"You have {credits} free journal credit{'s' if credits != 1 else ''} "
                  f"(sessions up to {config.FREE_JOURNAL_MAX_HOURS}h each).")
            print("After credits are used, journal mode requires a Pro plan.\n")
        else:
            print("Journal mode requires a Pro plan (or free credits if available).\n")
        answer = input("Enable journal mode? [y/N] ").strip().lower()
        if answer != "y":
            print("Journal mode not enabled.")
            return
        cfg["journal_mode"] = True
        config.save(cfg)
        print("\nJournal mode ON. Full content will be captured in your next session.")
        print("Run `methodproof start` to begin recording.\n")

    elif subcmd == "off":
        cfg["journal_mode"] = False
        config.save(cfg)
        print("Journal mode OFF. Only structural metadata will be captured.")

    elif subcmd == "status":
        enabled = cfg.get("journal_mode", False)
        if enabled:
            print("Journal mode: ON (full content capture)")
            print("  Prompts, completions, diffs, and output are persisted and encrypted.")
        else:
            print("Journal mode: OFF (structural only)")
            print("  Only metadata captured: lengths, types, timing, file paths.")
            print("  Enable with: methodproof journal on")
        if credits > 0:
            print(f"  Free journal credits: {credits} "
                  f"(up to {config.FREE_JOURNAL_MAX_HOURS}h per session)")

    else:
        print("Usage: methodproof journal [on|off|status]")


def _decode_jwt_claims(token: str) -> dict:
    """Extract claims from JWT payload without verification (auth already done server-side)."""
    import base64
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)  # pad base64
    return json.loads(base64.urlsafe_b64decode(payload))


def _require_auth(cfg: dict) -> str:
    """Ensure valid auth. Returns account_id. Exits on failure."""
    token = cfg.get("token", "")
    if not token:
        print("Login required. Run `mp login` first.")
        sys.exit(1)
    claims = _decode_jwt_claims(token)
    account_id = claims.get("user_id", "")
    if not account_id:
        print("Invalid token. Run `mp login` to re-authenticate.")
        sys.exit(1)
    # Check expiry — attempt refresh if expired
    exp = claims.get("exp", 0)
    if exp and time.time() > exp:
        from methodproof.sync import _refresh_token
        pair = _refresh_token(cfg["api_url"], cfg.get("refresh_token", ""))
        if pair:
            cfg["token"], cfg["refresh_token"] = pair
            cfg["last_auth_at"] = time.time()
            cfg["account_id"] = account_id
            config.save(cfg)
            return account_id
        # Offline grace — allow if last auth was within 24h
        if time.time() - cfg.get("last_auth_at", 0) < 86400:
            return account_id
        print("Session expired. Run `mp login` to re-authenticate.")
        sys.exit(1)
    cfg["last_auth_at"] = time.time()
    cfg["account_id"] = account_id
    config.save(cfg)
    return account_id


def _setup_master_key(cfg: dict) -> None:
    """Generate or recover master key on first login. Shows recovery phrase once."""
    account_id = cfg.get("account_id", "")
    if not account_id:
        return
    from methodproof.keychain import has_secret, store_secret, load_secret
    if has_secret(account_id):
        # Already set up — ensure fingerprint is in config
        if not cfg.get("master_key_fingerprint"):
            from methodproof.kdf import derive_master, derive_db_key
            from methodproof.crypto import fingerprint
            master = derive_master(load_secret(account_id))
            cfg["master_key_fingerprint"] = fingerprint(derive_db_key(master, account_id))
            config.save(cfg)
        return

    # Check if user has a recovery phrase (returning user, new device)
    if cfg.get("master_key_fingerprint"):
        _recover_master_key(cfg, account_id)
        return

    # First time — generate entropy, show recovery phrase
    entropy = os.urandom(16)
    from methodproof.bip39 import entropy_to_phrase
    phrase = entropy_to_phrase(entropy)
    store_secret(account_id, entropy)

    from methodproof.kdf import derive_master, derive_db_key
    from methodproof.crypto import fingerprint
    master = derive_master(entropy)
    cfg["master_key_fingerprint"] = fingerprint(derive_db_key(master, account_id))
    config.save(cfg)

    W = "\033[1;97m"
    Y = "\033[93m"
    D = "\033[90m"
    R = _RESET
    print(f"  ┌──────────────────────────────────────────────────┐")
    print(f"  │  {W}RECOVERY PHRASE — WRITE THIS DOWN{R}               │")
    print(f"  │                                                  │")
    print(f"  │  {Y}{phrase}{R}")
    print(f"  │                                                  │")
    print(f"  │  {D}This is the only way to recover your data{R}      │")
    print(f"  │  {D}on a new device. Store it somewhere safe.{R}      │")
    print(f"  └──────────────────────────────────────────────────┘\n")

    # Encrypt any existing plaintext events
    db_key = derive_db_key(master, account_id)
    from methodproof.migrate_db import migrate_encrypt
    count = migrate_encrypt(db_key)
    if count:
        print(f"  Encrypted {count} existing events.\n")


def _recover_master_key(cfg: dict, account_id: str) -> None:
    """Prompt for recovery phrase to restore master key on new device."""
    print("\n  Master key not found on this device.")
    print("  Enter your 12-word recovery phrase to restore access.\n")
    phrase = input("  Recovery phrase: ").strip()
    if not phrase:
        print("  Skipped. Encrypted session data will be inaccessible.")
        return
    from methodproof.bip39 import phrase_to_entropy
    try:
        entropy = phrase_to_entropy(phrase)
    except ValueError as e:
        print(f"  Invalid phrase: {e}")
        return
    from methodproof.keychain import store_secret
    store_secret(account_id, entropy)
    print("  Master key restored.\n")


def _is_daemon_alive() -> bool:
    """Check if the recording daemon is still running (not a reused PID)."""
    if not PIDFILE.exists():
        return False
    try:
        pid = int(PIDFILE.read_text().strip())
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError, OSError):
        return False
    # Verify the PID is actually a methodproof process (PIDs get reused after reboot)
    try:
        import subprocess
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "args="], text=True).strip()
        return "methodproof" in out
    except Exception:
        return False


def _log_step(msg: str, verbose: bool = False) -> None:
    """Print a step-by-step progress line. Always shown."""
    print(f"  → {msg}")


def _log_debug(msg: str, **kw: object) -> None:
    """Print structured debug line (--verbose only). Writes to stderr."""
    import json as _json
    entry = {"ts": time.time(), "level": "debug", "event": msg, **kw}
    sys.stderr.write(_json.dumps(entry, default=str) + "\n")


def cmd_start(args: argparse.Namespace) -> None:
    verbose = getattr(args, "verbose", False)
    streaming = getattr(args, "streaming", False)

    _log_step("Loading config")
    cfg = config.load()
    if verbose:
        _log_debug("config.loaded", api_url=cfg.get("api_url"), account_id=cfg.get("account_id", "")[:8],
                    active_session=cfg.get("active_session"), journal=cfg.get("journal_mode"))

    if cfg.get("auto_update"):
        _log_step("Checking for updates")
        _auto_update()

    if cfg.get("active_session"):
        if _is_daemon_alive():
            print(f"Session active: {cfg['active_session'][:8]}")
            print("Run `methodproof stop` first.")
            sys.exit(1)
        stale_sid = cfg["active_session"]
        _log_step(f"Cleaning stale session {stale_sid[:8]}")
        store.complete_session(stale_sid)
        graph.build(stale_sid)
        PIDFILE.unlink(missing_ok=True)
        cfg["active_session"] = None
        config.save(cfg)

    _log_step("Checking hooks")
    if not hook.is_installed():
        print("ERROR: Run `methodproof init` first.")
        sys.exit(1)

    _log_step("Authenticating")
    account_id = _require_auth(cfg)
    if verbose:
        _log_debug("auth.ok", account_id=account_id[:8] if account_id else "none")

    # Check for new consent categories before recording
    capture = cfg.get("capture", {})
    new_cats = (set(config.STANDARD_CATEGORIES) | {"code_capture"}) - set(capture.keys())
    if new_cats:
        print(f"\n  New capture categories available: {', '.join(sorted(new_cats))}")
        print("  Please review your consent settings before recording.\n")
        cfg = _run_consent(cfg)
        config.save(cfg)
        print()

    _log_step("Creating session")
    sid = uuid.uuid4().hex
    watch_dir = os.path.abspath(args.dir or ".")

    # Prevent concurrent sessions watching overlapping directories
    conflict = store.find_active_for_dir(watch_dir)
    if conflict:
        print(f"Active session {conflict['id'][:8]} already watches {conflict['watch_dir']}")
        print("Run `methodproof stop` first, or choose a different directory.")
        sys.exit(1)
    repo_url = args.repo or repos.detect_repo(watch_dir)
    tags = args.tags.split(",") if args.tags else []
    visibility = "public" if args.public else "private"
    from methodproof.binding import compute_binding, compute_device_id
    device_id = compute_device_id()
    binding = ""
    if cfg.get("master_key_fingerprint") and account_id:
        from methodproof.keychain import load_secret
        from methodproof.kdf import derive_master, derive_bind_key
        entropy = load_secret(account_id)
        if entropy:
            master = derive_master(entropy)
            bind_key = derive_bind_key(master, account_id)
            binding = compute_binding(bind_key, sid, account_id, device_id, time.time())
            if verbose:
                _log_debug("binding.computed", device_id=device_id[:8])
    store.create_session(sid, watch_dir, repo_url, json.dumps(tags), visibility,
                         account_id, binding, device_id)
    cfg["active_session"] = sid
    config.save(cfg)
    PIDFILE.write_text(str(os.getpid()))
    if verbose:
        _log_debug("session.created", sid=sid[:8], watch_dir=watch_dir, visibility=visibility,
                    device_id=device_id[:8], bound=bool(binding))

    # Temporal anchor
    if cfg.get("token"):
        _log_step("Requesting temporal anchor")
        try:
            from methodproof.sync import _request
            anchor = _request("POST", f"/sessions/{sid}/anchor", cfg["api_url"], cfg["token"])
            store.update_anchor(sid, anchor["anchor_ts"], anchor["signature"])
            if verbose:
                _log_debug("anchor.ok", anchor_ts=anchor["anchor_ts"])
        except Exception as exc:
            _log_step(f"Anchor: skipped ({exc})")

    from methodproof.agents import base
    capture = cfg.get("capture", {})

    # Live streaming
    live_url = ""
    want_live = args.live or getattr(args, "live_public", False)
    live_visibility = "public" if getattr(args, "live_public", False) else "private"
    if want_live:
        _log_step("Connecting live stream")
        if not cfg.get("token"):
            print("Live mode requires login. Run `methodproof login` first.")
            sys.exit(1)
        from methodproof.sync import _request
        session_body: dict = {}
        if cfg.get("e2e_fingerprint") and (getattr(args, "e2e", False) or cfg.get("e2e_mode")):
            session_body["e2e_key_fingerprint"] = cfg["e2e_fingerprint"]
        result = _request("POST", "/personal/sessions", cfg["api_url"], cfg["token"],
                          session_body or None)
        remote_id = result["session_id"]
        store.mark_synced(sid, remote_id)
        from methodproof import live as live_mod
        live_url = live_mod.start(cfg["api_url"], cfg["token"], remote_id, capture, live_visibility) or ""
        if not live_url:
            print("Live stream rejected — requires Pro plan or Full Spectrum.")
            sys.exit(1)
        if live_visibility == "private":
            print(f"Live (private): {live_url}")
            print("  Only you can view this stream while logged in.")
        else:
            print(f"Live (public): {live_url}")
            print("  Anyone with this link can watch your session build in real time.")

    # Journal mode
    if getattr(args, "journal", False):
        cfg["journal_mode"] = True
        credits = cfg.get("journal_credits", 0)
        if credits > 0:
            cfg["journal_credits"] = credits - 1
            print(f"Journal mode ON (free credit used — {credits - 1} remaining, {config.FREE_JOURNAL_MAX_HOURS}h cap).")
        else:
            print("Journal mode ON for this session (full content capture).")
        config.save(cfg)

    # E2E mode
    want_e2e = getattr(args, "e2e", False) or (cfg.get("e2e_mode") and not getattr(args, "no_e2e", False))
    if want_e2e:
        fp = cfg.get("e2e_fingerprint")
        if not fp:
            print("E2E requires key setup. Run `methodproof e2e on` first.")
            sys.exit(1)
        cfg["_session_e2e"] = True
        config.save(cfg)
        print("E2E mode ON for this session (content encrypted with your key).")
        print("  Narration unavailable. Release later with: mp e2e release <session-id>")

    # Save live_url for daemon subprocess to pick up
    if live_url:
        cfg["_live_url"] = live_url
        config.save(cfg)

    active = [k for k, v in capture.items() if v]
    print(f"\n{_banner()}")
    print(f"Recording: {sid[:8]}")
    print(f"Watching:  {watch_dir}")
    if repo_url:
        print(f"Repo:      {repo_url}")
    print(f"Capture:   {', '.join(active)}")
    if capture.get("browser", True):
        print(f"Bridge:    http://localhost:9877")
    if live_url:
        print(f"Live:      {live_url}")
    if verbose:
        print(f"Mode:      verbose (debug → daemon.log)")
    if streaming:
        print(f"Mode:      streaming (blocking, events → stdout)")

    # --streaming: blocking foreground mode with real-time event output
    if streaming:
        _run_foreground(sid, watch_dir, cfg, capture, live_url, verbose=True, streaming=True)
        return

    # Daemonize (macOS/Linux) — pass --verbose to daemon if set
    if sys.platform != "win32":
        import subprocess as _sp
        daemon_log = config.DIR / "daemon.log"
        log_fh = open(daemon_log, "a")
        cmd = [sys.executable, "-m", "methodproof._daemon", sid, watch_dir]
        if verbose:
            cmd.append("--verbose")
        _log_step(f"Spawning daemon (log: {daemon_log})")
        proc = _sp.Popen(cmd, start_new_session=True, stdout=log_fh, stderr=log_fh, stdin=_sp.DEVNULL)
        PIDFILE.write_text(str(proc.pid))
        if verbose:
            _log_debug("daemon.spawned", pid=proc.pid, cmd=cmd)
        time.sleep(1)
        if proc.poll() is not None:
            print(f"ERROR: Daemon exited immediately (code {proc.returncode}). Check {daemon_log}")
            PIDFILE.unlink(missing_ok=True)
            sys.exit(1)
        _log_step(f"Daemon alive (pid {proc.pid})")
        if capture.get("browser", True):
            import urllib.request as _ur
            time.sleep(7)
            try:
                with _ur.urlopen("http://127.0.0.1:9877/extension-status", timeout=2) as resp:
                    ext_data = json.loads(resp.read())
                if ext_data.get("paired"):
                    print("Extension: connected")
                else:
                    print("Extension: not detected — run `mp extension pair` or install from store")
            except Exception as exc:
                print(f"Extension: not detected ({exc})")
        if _resolve_ui(args, cfg):
            try:
                _tui_guard()
                session = store.get_session(sid)
                from methodproof.tui.start import run as tui_start
                tui_start(sid, session)
                return
            except SystemExit:
                pass  # textual not installed — fall through to plain message
        print("Run `mp stop` to finish.")
        return

    # Windows: foreground mode (no subprocess daemonization)
    _run_foreground(sid, watch_dir, cfg, capture, live_url, verbose=verbose, streaming=False)


def _run_foreground(sid: str, watch_dir: str, cfg: dict, capture: dict,
                    live_url: str, verbose: bool, streaming: bool) -> None:
    """Run capture agents in the foreground (blocking). Used by --streaming and Windows."""
    from methodproof.agents import base as _base
    _base.init(sid, live=bool(live_url), verbose=verbose, streaming=streaming)
    if capture.get("environment_analysis", True):
        _log_step("Scanning environment")
        try:
            from methodproof.analysis import scan_environment
            env_profile = scan_environment(watch_dir)
            _base.emit("environment_profile", env_profile)
        except Exception as exc:
            _base.log("warning", "environment_scan.failed", error=str(exc))
    stop_event = threading.Event()
    threads: list[threading.Thread] = []
    files_enabled = (
        capture.get("file_changes", True)
        or capture.get("git_diffs", True)
        or capture.get("git_commits", True)
    )
    if files_enabled:
        from methodproof.agents import watcher
        threads.append(threading.Thread(target=watcher.start, args=(watch_dir, stop_event), daemon=True))
        _log_step("Agent: watcher")
    if capture.get("terminal_commands", True) or capture.get("test_results", True):
        from methodproof.agents import terminal
        threads.append(threading.Thread(target=terminal.start, args=(stop_event,), daemon=True))
        _log_step("Agent: terminal")
    if capture.get("browser", True):
        from methodproof import bridge
        e2e_key_hex = ""
        if cfg.get("_session_e2e") and cfg.get("account_id"):
            from methodproof.keychain import load_secret
            _raw = load_secret(f"e2e:{cfg['account_id']}")
            if _raw:
                e2e_key_hex = _raw.hex()
        else:
            e2e_key_hex = cfg.get("e2e_key", "")
        threads.append(threading.Thread(target=bridge.start, args=(
            sid, stop_event, 9877,
            cfg.get("token", ""), cfg.get("api_url", ""), e2e_key_hex,
            cfg.get("journal_mode", False),
        ), daemon=True))
        _log_step("Agent: bridge")
    if capture.get("music", True):
        from methodproof.agents import music
        threads.append(threading.Thread(target=music.start, args=(stop_event,), daemon=True))
        _log_step("Agent: music")

    def _shutdown(sig: int, frame: object) -> None:
        stop_event.set()
        try:
            if live_url:
                from methodproof import live as live_mod
                live_mod.stop()
            _base.flush()
            store.complete_session(sid)
            graph.build(sid)
        except Exception as exc:
            _base.log("error", "shutdown.cleanup_failed", error=str(exc))
        try:
            cfg_now = config.load()
            cfg_now["active_session"] = None
            config.save(cfg_now)
        except Exception as exc:
            _base.log("error", "shutdown.config_cleanup_failed", error=str(exc))
        PIDFILE.unlink(missing_ok=True)
        sys.exit(0)

    _log_step(f"Starting {len(threads)} agent(s)")
    for t in threads:
        t.start()
    signal.signal(signal.SIGINT, _shutdown)
    if streaming:
        print("\n  Streaming events (Ctrl+C to stop):\n")
    else:
        print("Press Ctrl+C or run `mp stop` to finish.")
    stopfile = config.DIR / "methodproof.stop"
    while not stop_event.is_set():
        if stopfile.exists():
            stopfile.unlink(missing_ok=True)
            _shutdown(0, None)
        time.sleep(5)
        _base.flush()


def cmd_stop(args: argparse.Namespace) -> None:
    cfg = config.load()
    sid = cfg.get("active_session")
    if not sid:
        # Config lost track — check store for dangling sessions on this directory
        watch_dir = os.path.abspath(".")
        dangling = store.find_active_for_dir(watch_dir)
        if dangling:
            sid = dangling["id"]
            cfg["active_session"] = sid
            config.save(cfg)
        else:
            print("No active session.")
            sys.exit(1)

    # Signal the start process if it's running
    if PIDFILE.exists():
        try:
            pid = int(PIDFILE.read_text().strip())
            if sys.platform == "win32":
                # Windows: write stop sentinel — the start loop checks for it
                stopfile = config.DIR / "methodproof.stop"
                stopfile.write_text(str(pid))
                print(f"Stopping session {sid[:8]}...")
                for _ in range(10):
                    time.sleep(0.5)
                    if not PIDFILE.exists():
                        break
            else:
                os.kill(pid, signal.SIGTERM)
                print(f"Stopping session {sid[:8]}...")
                time.sleep(3)
            return
        except (ProcessLookupError, ValueError, OSError):
            PIDFILE.unlink(missing_ok=True)

    # Fallback: start process is gone, complete directly
    from methodproof.agents import base
    base.init(sid)
    base.flush()
    store.complete_session(sid)
    stats = graph.build(sid)
    session = store.get_session(sid)
    cfg["active_session"] = None
    config.save(cfg)
    _print_summary(session, stats)


def cmd_view(args: argparse.Namespace) -> None:
    session = _resolve_session(args.session_id)
    from methodproof.viewer import view
    view(session)


def cmd_log(args: argparse.Namespace) -> None:
    cfg = config.load()
    if _resolve_ui(args, cfg):
        _tui_guard()
        from methodproof.tui.log import run as tui_log
        result = tui_log()
        if result:
            action, sid = result
            import argparse as _ap
            fake = _ap.Namespace(session_id=sid, local=False)
            if action == "push":
                cmd_push(fake)
            elif action == "view":
                cmd_view(fake)
        return
    sessions = store.list_sessions()
    if not sessions:
        print("No sessions yet.")
        return
    unsynced = [s for s in sessions if not s["synced"] and s.get("completed_at") and s["total_events"] > 0]
    if unsynced:
        print(f"  [{len(unsynced)} session{'s' if len(unsynced) != 1 else ''} behind sync] — run `mp push` to upload\n")
    for s in sessions:
        sync_tag = "synced" if s["synced"] else "local"
        status = _session_status(s)
        dt = datetime.fromtimestamp(s["created_at"], tz=UTC).strftime("%Y-%m-%d %H:%M")
        dur = _duration(s)
        vis = s.get("visibility", "private")
        tags = json.loads(s.get("tags") or "[]")
        suffix = f"  [{sync_tag}]  {status}"
        if vis != "private":
            suffix += f"  {vis}"
        if tags:
            suffix += f"  #{','.join(tags)}"
        print(f"  {s['id'][:8]}  {dt}  {dur}  {s['total_events']} events{suffix}")


def cmd_status(args: argparse.Namespace) -> None:
    """Show auth, session, and config status at a glance."""
    cfg = config.load()
    if _resolve_ui(args, cfg):
        _tui_guard()
        from methodproof.tui.status import run as tui_status
        tui_status(cfg)
        return
    from methodproof import __version__
    token = cfg.get("token", "")
    claims = _decode_jwt_claims(token) if token else {}
    sessions = store.list_sessions()
    active = cfg.get("active_session")
    capture = cfg.get("capture", {})
    enabled = [k for k, v in capture.items() if v]

    print(f"\n  methodproof v{__version__}")
    print(f"  api: {cfg.get('api_url', '—')}\n")

    # Auth
    if not token:
        print("  auth: not signed in")
    else:
        account_id = claims.get("user_id", "—")
        role = claims.get("role", "—")
        acct_type = claims.get("account_type", "—")
        exp = claims.get("exp", 0)
        if exp and time.time() > exp:
            expiry = "expired"
        elif exp:
            remaining = int(exp - time.time())
            hours = remaining // 3600
            mins = (remaining % 3600) // 60
            expiry = f"{hours}h {mins}m remaining"
        else:
            expiry = "unknown"
        print(f"  auth: signed in")
        print(f"  account: {account_id[:8]}...{account_id[-4:]}")
        print(f"  role: {role}  |  type: {acct_type}  |  token: {expiry}")
        n_profiles = len(cfg.get("profiles", {}))
        if n_profiles > 1:
            print(f"  accounts: {n_profiles} on this device  (`mp switch` to swap)")
        if claims.get("is_superadmin"):
            print("  superadmin: yes")

    # Session
    print()
    if active:
        sess = store.get_session(active)
        if sess:
            dt = datetime.fromtimestamp(sess["created_at"], tz=UTC).strftime("%H:%M")
            print(f"  session: RECORDING  {active[:8]}  started {dt}  ({sess['total_events']} events)")
        else:
            print(f"  session: RECORDING  {active[:8]}")
    else:
        print("  session: idle")

    # Local sessions
    total = len(sessions)
    unsynced = len([s for s in sessions if not s["synced"] and s.get("completed_at") and s["total_events"] > 0])
    print(f"  local: {total} session{'s' if total != 1 else ''}", end="")
    if unsynced:
        print(f"  ({unsynced} unsynced)")
    else:
        print()

    # Capture config
    print(f"\n  consent: {len(enabled)}/11 categories")
    full_spectrum = len(enabled) >= 10
    if full_spectrum:
        print("  spectrum: FULL")

    # Modes
    modes = []
    if cfg.get("journal_mode"):
        credits = cfg.get("journal_credits", 0)
        modes.append(f"journal ({credits} credits)")
    if cfg.get("e2e_mode"):
        fp = cfg.get("e2e_fingerprint", "")
        modes.append(f"e2e ({fp[:8]})" if fp else "e2e")
    if modes:
        print(f"  modes: {' | '.join(modes)}")

    # Research
    if cfg.get("research_consent"):
        level = cfg.get("contribution_level", "structural")
        print(f"  research: opted in ({level})")

    print()


def cmd_logout(args: argparse.Namespace) -> None:
    """Clear login credentials only. Keeps consent, sessions, and hooks."""
    cfg = config.load()
    if not cfg.get("token"):
        print("Not logged in.")
        return
    old_email = cfg.get("email", "")
    old_account = cfg.get("account_id", "")[:8]
    for key in ("token", "refresh_token", "email", "account_id", "last_auth_at", "master_key_fingerprint"):
        cfg[key] = config._DEFAULTS.get(key, "")
    config.save(cfg)
    label = old_email or old_account or "account"
    print(f"Logged out ({label}). Run `mp login` to sign in again.")


def cmd_accounts(args: argparse.Namespace) -> None:
    """List all accounts stored on this device."""
    cfg = config.load()
    profiles = config.list_profiles(cfg)
    if not profiles:
        print("No accounts. Run `mp login` to sign in.")
        return
    print()
    for p in profiles:
        marker = "*" if p.get("active") else " "
        email = p.get("email", "")
        aid = p.get("account_id", "")[:8]
        label = email or aid or "unknown"
        # Token status
        token = p.get("token", "")
        if token:
            claims = _decode_jwt_claims(token)
            exp = claims.get("exp", 0)
            if exp and time.time() > exp:
                status = "expired"
            elif exp:
                remaining = int(exp - time.time())
                h, m = remaining // 3600, (remaining % 3600) // 60
                status = f"{h}h {m}m"
            else:
                status = "valid"
        else:
            status = "no token"
        print(f"  {marker} {label}  ({aid})  token: {status}")
    print(f"\n  Switch: `mp switch <email or id prefix>`\n")


def cmd_switch(args: argparse.Namespace) -> None:
    """Quick-swap to a stored account profile."""
    cfg = config.load()
    profiles = cfg.get("profiles", {})

    if not profiles:
        print("No stored accounts. Run `mp login` to add one.")
        return

    query = getattr(args, "account", None)

    if query:
        # Direct match
        target = config.find_profile(cfg, query)
        if not target:
            print(f"No account matching '{query}'. Run `mp accounts` to see stored accounts.")
            return
    else:
        # Interactive picker
        items = [(aid, p) for aid, p in profiles.items() if aid != cfg.get("account_id")]
        if not items:
            print("Only one account stored. Run `mp login` to add another.")
            return
        print()
        for i, (aid, p) in enumerate(items, 1):
            label = p.get("email") or aid[:8]
            print(f"  {i}. {label}  ({aid[:8]})")
        print()
        try:
            choice = input(f"  Switch to [1-{len(items)}]: ").strip()
            idx = int(choice) - 1
            if not 0 <= idx < len(items):
                print("Cancelled.")
                return
        except (ValueError, EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return
        target = items[idx][0]

    if target == cfg.get("account_id"):
        label = cfg.get("email") or target[:8]
        print(f"Already active: {label}")
        return

    if config.restore_profile(cfg, target):
        cfg = config.load()  # reload after swap
        label = cfg.get("email") or cfg.get("account_id", "")[:8]
        print(f"Switched to {label} ({cfg.get('account_id', '')[:8]}).")
        # Re-setup master key for this account
        _setup_master_key(cfg)
    else:
        print(f"Profile not found for {target[:8]}. Run `mp login`.")


def cmd_login(args: argparse.Namespace) -> None:
    import webbrowser
    from methodproof.sync import _request

    cfg = config.load()
    api = args.api_url or cfg["api_url"]

    if cfg.get("token") and not getattr(args, "force", False):
        current = cfg.get("email") or cfg.get("account_id", "")[:8] or "an account"
        print(f"Already logged in as {current}.")
        answer = input("  Switch accounts? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            return
        # Stash current profile before switching
        config.save_active_profile(cfg)

    # Start device auth flow
    result = _request("POST", "/auth/cli/start", api, "")
    code = result["code"]
    auth_url = result["auth_url"]
    user_code = result.get("user_code", "")
    verification_url = result.get("verification_url", "")

    print(f"\nOpening browser to sign in...\n")
    print(f"  {auth_url}\n")
    if user_code and verification_url:
        print(f"Can't open a browser? Visit {verification_url} and enter:\n")
        print(f"  {user_code}\n")
    else:
        print("If the browser doesn't open, copy the URL above.\n")
    webbrowser.open(auth_url)

    # Poll until approved or expired
    print("Waiting for authorization...", end="", flush=True)
    for _ in range(60):
        time.sleep(2)
        try:
            poll = _request("GET", f"/auth/cli/poll?code={code}", api, "")
            if poll.get("status") == "complete":
                cfg["token"] = poll["token"]
                cfg["refresh_token"] = poll.get("refresh_token", "")
                cfg["api_url"] = api
                # Extract account_id and persist auth timestamp
                claims = _decode_jwt_claims(poll["token"])
                cfg["account_id"] = claims.get("user_id", "")
                cfg["last_auth_at"] = time.time()
                cfg["master_key_fingerprint"] = ""  # clear stale fingerprint from previous account
                config.save(cfg)
                config.save_active_profile(cfg)
                print(" done.\n")
                if not getattr(args, "no_key", False):
                    _setup_master_key(cfg)
                from methodproof.sync import sync_research_consent
                sync_research_consent(cfg["token"], cfg["api_url"])
                label = cfg.get("email") or cfg.get("account_id", "")[:8]
                profiles = cfg.get("profiles", {})
                n = len(profiles)
                print(f"Logged in as {label}. {n} account{'s' if n != 1 else ''} on this device.")
                print("  Quick-swap: `mp switch`")
                return
        except Exception:
            pass
        print(".", end="", flush=True)

    print("\n\nAuthorization timed out. Run `methodproof login` to try again.")


def cmd_push(args: argparse.Namespace) -> None:
    local = getattr(args, "local", False)
    cfg = config.load(local=local)
    if not cfg.get("token"):
        target = "local API" if local else "platform"
        print(f"Run `methodproof login{' --api-url http://localhost:8000' if local else ''}` first.")
        sys.exit(1)
    from methodproof.sync import sync_research_consent
    sync_research_consent(cfg["token"], cfg["api_url"])
    cfg = config.load(local=local)
    sid = args.session_id or _latest()
    if not sid:
        print("No sessions to push.")
        sys.exit(1)
    from methodproof.sync import push
    remote_id = push(sid, cfg["token"], cfg["api_url"])
    app = _app_url(cfg["api_url"])
    print(f"Pushed {sid[:8]} → {cfg['api_url']} (private).")
    print(f"  View: {app}/personal/sessions/{remote_id}")
    print(f"  Publish: mp publish {sid[:8]}")


def cmd_tag(args: argparse.Namespace) -> None:
    session = _resolve_session(args.session_id)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    existing = json.loads(session.get("tags") or "[]")
    merged = list(dict.fromkeys(existing + tags))
    store.update_tags(session["id"], merged)
    print(f"Tagged {session['id'][:8]}: {merged}")


def cmd_publish(args: argparse.Namespace) -> None:
    cfg = config.load()
    if not cfg.get("token"):
        print("Run `methodproof login` first.")
        sys.exit(1)
    session = _resolve_session(args.session_id)

    # Show what will be redacted
    redact = cfg.get("publish_redact", config._DEFAULTS["publish_redact"])
    redacted = [k for k, v in redact.items() if v]
    if redacted:
        print(f"  Redacting from public view: {', '.join(redacted)}")
        print(f"  Change defaults with `methodproof consent`\n")

    store.update_visibility(session["id"], "public")
    session["visibility"] = "public"
    if not session["synced"]:
        from methodproof.sync import push
        remote_id = push(session["id"], cfg["token"], cfg["api_url"])
    else:
        from methodproof.sync import sync_metadata
        sync_metadata(session, cfg["token"], cfg["api_url"])
        remote_id = session.get("remote_id", "")
    app = _app_url(cfg["api_url"])
    print(f"Published {session['id'][:8]} (public).")
    if remote_id:
        print(f"  View: {app}/sessions/{remote_id}/cover")


def _resolve_session(session_id: str) -> dict:
    sid = session_id or _latest()
    if not sid:
        print("No sessions found.")
        sys.exit(1)
    session = store.get_session(sid)
    if not session:
        # Try prefix match
        sessions = store.list_sessions()
        matches = [s for s in sessions if s["id"].startswith(sid)]
        if len(matches) == 1:
            return matches[0]
        print(f"Session not found: {sid}")
        sys.exit(1)
    return session


def cmd_delete(args: argparse.Namespace) -> None:
    session = _resolve_session(args.session_id)
    sid = session["id"]
    if not args.force:
        answer = input(f"Delete session {sid[:8]} and all its data? [y/N]: ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return
    if store.delete_session(sid):
        print(f"Deleted: {sid[:8]}")
    else:
        print(f"Session not found: {sid[:8]}")


def cmd_review(args: argparse.Namespace) -> None:
    """Show exactly what a session contains before pushing."""
    cfg = config.load()
    session = _resolve_session(args.session_id)
    if _resolve_ui(args, cfg):
        _tui_guard()
        from methodproof.tui.review import run as tui_review
        tui_review(session)
        return
    events = store.get_events(session["id"])
    if not events:
        print("No events in this session.")
        return

    print(f"\n{_banner()} — review before push\n")
    print(f"Session:  {session['id'][:8]}")
    print(f"Duration: {_duration(session)}")
    synced = "yes" if session["synced"] else "no"
    print(f"Synced:   {synced}")
    print(f"Events:   {len(events)}\n")

    # Group by type
    by_type: dict[str, list[dict]] = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)

    for etype, items in sorted(by_type.items(), key=lambda x: -len(x[1])):
        print(f"  {etype:<30s} {len(items):>4} events")
        # Show sample metadata fields from first event
        meta = json.loads(items[0]["metadata"])
        fields = ", ".join(meta.keys())
        if fields:
            print(f"    fields: {fields}")

    print(f"\nTotal: {len(events)} events across {len(by_type)} types.")
    print("No source code or diff content is captured.")
    print("Run `methodproof push` to upload, or `methodproof delete` to remove.\n")


def cmd_update(args: argparse.Namespace) -> None:
    # Handle --auto / --no-auto toggle
    if getattr(args, "auto", None) is not None:
        cfg = config.load()
        cfg["auto_update"] = args.auto
        config.save(cfg)
        state = "ON" if args.auto else "OFF"
        print(f"Auto-update: {state}")
        if args.auto:
            print("  Updates will install automatically before each `mp start`.")
        return

    latest = _check_pypi_version()
    current = _get_current_version()
    if not latest:
        print("Could not reach PyPI. Try: pip install --upgrade methodproof")
        return
    if latest == current:
        print(f"Already up to date (v{current}).")
        _check_consent_drift()
        return
    print(f"Updating v{current} -> v{latest}...")
    import subprocess as sp
    result = sp.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "methodproof"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"Updated to v{latest}.")
        _check_consent_drift()
    else:
        print(f"Update failed. Try manually: pip install --upgrade methodproof")


def _check_consent_drift() -> None:
    """If new capture categories exist since last consent, re-run the consent flow."""
    cfg = config.load()
    capture = cfg.get("capture", {})
    known = set(capture.keys())
    current = set(config.STANDARD_CATEGORIES) | {"code_capture"}
    new_categories = current - known

    if not new_categories:
        return

    print(f"\n  New capture categories available: {', '.join(sorted(new_categories))}")
    print("  Your consent preferences need updating.\n")
    cfg = _run_consent(cfg)
    config.save(cfg)
    print(f"\n{_banner()} settings saved.\n")


def _get_current_version() -> str:
    try:
        from importlib.metadata import version
        return version("methodproof")
    except Exception:
        return "0.0.0"


def _check_pypi_version() -> str | None:
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://pypi.org/pypi/methodproof/json",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            return data["info"]["version"]
    except Exception:
        return None


def _update_check() -> None:
    """Background version check. Runs once per day, prints notice if outdated."""
    check_file = config.DIR / ".last_update_check"
    now = time.time()

    try:
        if check_file.exists():
            last = float(check_file.read_text().strip())
            if now - last < 86400:
                return
    except Exception:
        pass

    def _check():
        latest = _check_pypi_version()
        current = _get_current_version()
        try:
            config.ensure_dirs()
            check_file.write_text(str(now))
        except Exception:
            pass
        if latest and latest != current:
            sys.stderr.write(
                f"\033[90m  Update available: v{current} -> v{latest}."
                f" Run: mp update\033[0m\n"
            )

    t = threading.Thread(target=_check, daemon=True)
    t.start()


def _auto_update() -> None:
    """Check PyPI and install update before starting a session."""
    latest = _check_pypi_version()
    current = _get_current_version()
    if not latest or latest == current:
        return
    print(f"  Updating v{current} -> v{latest}...", end=" ", flush=True)
    import subprocess as sp
    result = sp.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "methodproof"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("done.")
        _check_consent_drift()
    else:
        print("failed (run `mp update` manually).")


def cmd_mcp_serve(args: argparse.Namespace) -> None:
    from methodproof.mcp import serve
    serve()


def _latest() -> str | None:
    sessions = store.list_sessions()
    return sessions[0]["id"] if sessions else None


def _session_status(s: dict) -> str:
    active = config.load().get("active_session")
    if s["id"] == active:
        return "recording"
    if not s.get("completed_at"):
        return "abandoned"
    if s["total_events"] == 0:
        return "empty"
    if s["synced"]:
        return "pushed"
    return "stopped"


def _duration(s: dict) -> str:
    if not s.get("completed_at") or not s.get("created_at"):
        return "--:--"
    secs = int(s["completed_at"] - s["created_at"])
    return f"{secs // 60}:{secs % 60:02d}"


def _print_summary(session: dict | None, stats: dict) -> None:
    if not session:
        return
    print(f"\n{_banner()}")
    print(f"Session:  {session['id'][:8]}")
    print(f"  Events:   {session['total_events']}")
    print(f"  Duration: {_duration(session)}")
    print(f"  Graph:    {stats['next']} links, {stats['causal']} causal")
    print(f"\nRun `methodproof view` to inspect captured data.")


CHROME_STORE_URL = "https://chromewebstore.google.com/detail/methodproof/TODO_EXTENSION_ID"


def cmd_extension(args: argparse.Namespace) -> None:
    import json as _json
    import urllib.request
    import webbrowser

    ext_cmd = getattr(args, "ext_cmd", None)

    if ext_cmd == "install":
        print(f"Opening Chrome Web Store...\n  {CHROME_STORE_URL}")
        webbrowser.open(CHROME_STORE_URL)
        return

    if ext_cmd == "status":
        try:
            with urllib.request.urlopen("http://127.0.0.1:9877/extension-status", timeout=2) as resp:
                data = _json.loads(resp.read())
            print("Extension: paired" if data.get("paired") else "Extension: not paired")
        except Exception:
            print("Bridge not running. Start a session first (`mp start`).")
        return

    if ext_cmd == "pair":
        cfg = config.load()
        sid = cfg.get("active_session")
        if not sid:
            print("No active session. Run `mp start` first.")
            sys.exit(1)

        # Check bridge is running
        try:
            with urllib.request.urlopen("http://127.0.0.1:9877/session", timeout=2) as resp:
                bridge_data = _json.loads(resp.read())
            if not bridge_data.get("active"):
                print("Bridge not active. Is browser capture enabled?")
                sys.exit(1)
        except Exception:
            print("Bridge not running. Ensure browser capture is enabled in consent settings.")
            sys.exit(1)

        # Get API credentials for the extension
        api_token = cfg.get("token", "")
        api_base = cfg.get("api_url", "https://api.methodproof.com")
        e2e_key = cfg.get("e2e_key", "")

        # For live sessions, use the remote session ID
        session = store.get_session(sid)
        pair_session_id = session["remote_id"] if session and session.get("remote_id") else sid

        # Register pairing token with the running bridge via HTTP
        import secrets as _secrets
        token = _secrets.token_urlsafe(16)
        reg_body = _json.dumps({
            "token": token, "session_id": pair_session_id,
            "api_token": api_token, "api_base": api_base, "e2e_key": e2e_key,
        }).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:9877/pair/register", data=reg_body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            print("Failed to register pairing token with bridge.")
            sys.exit(1)
        url = f"http://localhost:9877/pair?token={token}"

        print(f"\n{_banner()}")
        print(f"Pairing extension to session {pair_session_id[:8]}...")
        print(f"\nOpening browser...\n  {url}\n")
        webbrowser.open(url)

        # Wait for pairing confirmation (up to 60s)
        print("Waiting for extension...", end="", flush=True)
        for _ in range(30):
            time.sleep(2)
            try:
                with urllib.request.urlopen("http://127.0.0.1:9877/extension-status", timeout=2) as resp:
                    data = _json.loads(resp.read())
                if data.get("paired"):
                    print(" paired!\n")
                    print("Browser telemetry is now captured for this session.")
                    print("The extension popup shows session status.")
                    return
            except Exception:
                pass
            print(".", end="", flush=True)

        print("\n\nPairing timed out. Make sure the MethodProof extension is installed.")
        print(f"Install it: mp extension install")
        return

    # No subcommand — show help
    print("Usage: methodproof extension <pair|status|install>")
    print("  pair     Pair browser extension to active session")
    print("  status   Check extension connection")
    print("  install  Open Chrome Web Store listing")


def main() -> None:
    from methodproof import __version__
    p = argparse.ArgumentParser(prog="methodproof", description=_banner())
    p.add_argument("--version", action="version", version=f"methodproof {__version__}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("init", help="Install shell hook")
    s.add_argument("--force", action="store_true", help="Re-run all setup prompts from scratch")
    _add_ui_flags(s)
    sub.add_parser("shell-hook", help="Print shell hook for eval (activates without restart)")
    s = sub.add_parser("start", help="Start recording")
    s.add_argument("--dir", help="Directory to watch")
    s.add_argument("--repo", help="Git remote URL (overrides auto-detect)")
    s.add_argument("--public", action="store_true", help="Set visibility to public")
    s.add_argument("--tags", help="Comma-separated tags")
    s.add_argument("--live", action="store_true", help="Stream graph live to your private profile")
    s.add_argument("--live-public", action="store_true", help="Stream graph live — visible to anyone with the link")
    s.add_argument("--journal", action="store_true", help="Journal mode — full content capture (2 free credits, then Pro)")
    s.add_argument("--e2e", action="store_true", help="E2E encryption — content encrypted with your personal key")
    s.add_argument("--no-e2e", action="store_true", help="Disable E2E for this session (overrides config)")
    s.add_argument("--verbose", "-v", action="store_true", help="Debug logging at each step (still daemonizes)")
    s.add_argument("--streaming", action="store_true", help="Blocking foreground — stream every captured event to stdout")
    _add_ui_flags(s)
    sub.add_parser("stop", help="Stop recording")
    v = sub.add_parser("view", help="Inspect captured session data")
    v.add_argument("session_id", nargs="?")
    l_log = sub.add_parser("log", help="List sessions")
    _add_ui_flags(l_log)
    s_status = sub.add_parser("status", help="Auth, session, and config status")
    _add_ui_flags(s_status)
    l = sub.add_parser("login", help="Connect to platform")
    l.add_argument("--api-url")
    l.add_argument("--force", "-f", action="store_true", help="Skip switch-account prompt")
    l.add_argument("--no-key", action="store_true", help="Skip master key generation (test accounts)")
    sub.add_parser("logout", help="Clear login credentials (keeps consent and sessions)")
    sub.add_parser("accounts", help="List all accounts on this device")
    sw = sub.add_parser("switch", help="Quick-swap to another account")
    sw.add_argument("account", nargs="?", help="Email or account ID prefix")
    pu = sub.add_parser("push", help="Upload privately to your account")
    pu.add_argument("session_id", nargs="?")
    pu.add_argument("--local", action="store_true", help="Push to local dev API (localhost:8000)")
    tg = sub.add_parser("tag", help="Tag a session")
    tg.add_argument("session_id", help="Session ID (prefix ok)")
    tg.add_argument("tags", help="Comma-separated tags")
    pb = sub.add_parser("publish", help="Make session public (applies redaction defaults)")
    pb.add_argument("session_id", nargs="?")
    dl = sub.add_parser("delete", help="Delete a session and all its data")
    dl.add_argument("session_id", help="Session ID (prefix ok)")
    dl.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    rv = sub.add_parser("review", help="Review session data before pushing")
    rv.add_argument("session_id", nargs="?")
    _add_ui_flags(rv)
    c_consent = sub.add_parser("consent", help="Change capture, research, and redaction settings")
    _add_ui_flags(c_consent)
    ui_p = sub.add_parser("ui", help="Toggle TUI mode on/off")
    ui_sub = ui_p.add_subparsers(dest="ui_cmd")
    ui_sub.add_parser("on", help="Enable TUI mode")
    ui_sub.add_parser("off", help="Disable TUI mode (classic output)")
    ui_sub.add_parser("status", help="Show TUI mode and library status")
    up = sub.add_parser("update", help="Update to the latest version from PyPI")
    up_auto = up.add_mutually_exclusive_group()
    up_auto.add_argument("--auto", dest="auto", action="store_true", default=None,
                         help="Enable auto-update before each mp start (recommended)")
    up_auto.add_argument("--no-auto", dest="auto", action="store_false",
                         help="Disable auto-update")
    lk = sub.add_parser("lock", help="Destroy local encryption key (reversible with recovery phrase)")
    lk.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    lk.add_argument("--purge", action="store_true", help="Also delete the entire database (irreversible)")
    rs = sub.add_parser("reset", help="Clear login and consent settings (keeps sessions and hooks)")
    rs.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    un = sub.add_parser("uninstall", help="Remove all hooks, data, and config")
    un.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    un.add_argument("--keep-sessions", action="store_true", help="Preserve session database")
    ext = sub.add_parser("extension", help="Browser extension pairing and status")
    ext_sub = ext.add_subparsers(dest="ext_cmd")
    ext_sub.add_parser("pair", help="Pair extension to active session")
    ext_sub.add_parser("status", help="Check extension connection")
    ext_sub.add_parser("install", help="Open Chrome Web Store listing")
    jr = sub.add_parser("journal", help="Journal mode — full content capture (2 free credits, then Pro)")
    jr_sub = jr.add_subparsers(dest="journal_cmd")
    jr_sub.add_parser("on", help="Enable journal mode (persists full content)")
    jr_sub.add_parser("off", help="Disable journal mode (structural only)")
    jr_sub.add_parser("status", help="Show journal mode status")
    e2e_p = sub.add_parser("e2e", help="E2E encryption — personal key management")
    e2e_sub = e2e_p.add_subparsers(dest="e2e_cmd")
    e2e_sub.add_parser("on", help="Enable E2E mode (generates key on first use)")
    e2e_sub.add_parser("off", help="Disable E2E mode (key stays in keychain)")
    e2e_sub.add_parser("status", help="Show E2E mode status")
    e2e_sub.add_parser("recover", help="Recover key from passphrase")
    e2e_rel = e2e_sub.add_parser("release", help="Release a session from E2E encryption")
    e2e_rel.add_argument("session_id", help="Session ID to release")
    sub.add_parser("intro", help="Show the MethodProof intro")
    sub.add_parser("help", help="Show command reference")
    sub.add_parser("mcp-serve", help="Run MCP server (used by Claude Code)")
    px = sub.add_parser("proxy", help="Local AI API proxy (deep capture)")
    px_sub = px.add_subparsers(dest="proxy_cmd")
    px_sub.add_parser("start", help="Start proxy (requires consent)")
    px_sub.add_parser("stop", help="Stop proxy")
    px_sub.add_parser("status", help="Show proxy status")
    px_sub.add_parser("cert", help="CA certificate install instructions")

    args = p.parse_args()
    cmds = {
        "init": cmd_init, "start": cmd_start, "stop": cmd_stop,
        "view": cmd_view, "log": cmd_log, "status": cmd_status,
        "login": cmd_login, "logout": cmd_logout, "accounts": cmd_accounts, "switch": cmd_switch,
        "push": cmd_push, "tag": cmd_tag, "publish": cmd_publish,
        "delete": cmd_delete, "review": cmd_review, "consent": cmd_consent,
        "update": cmd_update, "lock": cmd_lock, "reset": cmd_reset, "uninstall": cmd_uninstall,
        "extension": cmd_extension,
        "journal": cmd_journal,
        "e2e": lambda a: __import__("methodproof.e2e", fromlist=["cmd_e2e"]).cmd_e2e(a),
        "intro": lambda _: _print_intro(),
        "help": lambda _: _print_commands(),
        "shell-hook": cmd_shell_hook,
        "ui": cmd_ui,
        "mcp-serve": cmd_mcp_serve,
        "proxy": lambda a: __import__("methodproof.proxy", fromlist=["cmd_proxy"]).cmd_proxy(a),
    }
    fn = cmds.get(args.cmd)
    if not fn:
        _print_intro()
        _print_commands()
        sys.exit(1)

    # Background update check (once per day, non blocking)
    if args.cmd not in ("help", "update", "uninstall", "mcp-serve"):
        _update_check()

    if args.cmd not in ("help", "update"):
        store.init_db()
    fn(args)
