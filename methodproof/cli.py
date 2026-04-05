"""MethodProof CLI. See how you code.

Usage:
    methodproof init              Install hooks, configure capture + research + redaction
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


def _run_consent(cfg: dict) -> dict:
    """Interactive consent flow with three sections: capture, research, redaction."""
    capture = cfg.get("capture", dict(config._DEFAULTS["capture"]))
    publish_redact = cfg.get("publish_redact", dict(config._DEFAULTS["publish_redact"]))
    std = config.STANDARD_CATEGORIES

    print(f"\n{_banner()}\n")
    print("Built by engineers, for engineers.\n")
    print("All data stays local in ~/.methodproof/. Nothing leaves your")
    print("machine unless you explicitly run `mp push` or `mp publish`.\n")

    # --- Section 1: Capture ---
    print("=" * 60)
    print("  SECTION 1: What gets recorded locally")
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
    print("  SECTION 2: Contribute to AI research (optional)")
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
    print("  SECTION 3: Default redactions for public sessions")
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
    if not cfg.get("consent_acknowledged"):
        cfg = _run_consent(cfg)
        config.save(cfg)
        print()

    capture = cfg.get("capture", {})
    store.init_db()

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
            print("AI Agent Graph: Claude Code not found (hooks + skill skipped)")
        else:
            print(f"AI Agent Graph hooks: {oc_result}")
            skill_result = install_skill()
            if skill_result:
                print(f"AI Agent Graph skill: {skill_result}")
    else:
        print("AI hooks: skipped (ai_prompts and ai_responses disabled)")

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

    print(f"\n{_banner()}")
    print("Restart your shell, then run: methodproof start\n")
    _print_commands()


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
    print(f"    {_G}mp start --live{R}        Stream your graph in real time")
    print()
    print(f"  {_W}REVIEW{R}")
    print(f"    {_C}mp view{R}  {_D}[id]{R}          View session graph in browser")
    print(f"    {_C}mp review{R} {_D}[id]{R}         Inspect session data before pushing")
    print(f"    {_C}mp log{R}                List all local sessions")
    print()
    print(f"  {_W}SHARE{R}")
    print(f"    {_Y}mp push{R}  {_D}[id]{R}          Upload privately to your account")
    print(f"    {_Y}mp publish{R} {_D}[id]{R}        Make session public (redaction applied)")
    print(f"    {_Y}mp tag{R} {_D}<id> <tags>{R}     Tag a session")
    print()
    print(f"  {_W}EXTENSION{R}")
    print(f"    {_C}mp extension pair{R}      Pair browser extension to active session")
    print(f"    {_C}mp extension status{R}    Check extension connection")
    print(f"    {_C}mp extension install{R}   Open Chrome Web Store")
    print()
    print(f"  {_W}ACCOUNT{R}")
    print(f"    {_M}mp login{R}              Connect to platform (opens browser)")
    print(f"    {_M}mp consent{R}            Change capture, research, and redaction settings")
    print(f"    {_M}mp delete{R} {_D}<id>{R}        Delete a session and all its data")
    print(f"    {_M}mp update{R}              Update to the latest version")
    print(f"    {_M}mp uninstall{R}           Remove all hooks, data, and config")
    print()
    print(f"  {_D}To view this at any time run: mp help{R}\n")


def _print_commands_plain() -> None:
    print("  RECORD")
    print("    mp start              Start recording a session")
    print("    mp stop               Stop recording, build process graph")
    print("    mp start --live       Stream your graph in real time")
    print()
    print("  REVIEW")
    print("    mp view  [id]         View session graph in browser")
    print("    mp review [id]        Inspect session data before pushing")
    print("    mp log                List all local sessions")
    print()
    print("  SHARE")
    print("    mp push  [id]         Upload privately to your account")
    print("    mp publish [id]       Make session public (redaction applied)")
    print("    mp tag <id> <tags>    Tag a session")
    print()
    print("  EXTENSION")
    print("    mp extension pair     Pair browser extension to active session")
    print("    mp extension status   Check extension connection")
    print("    mp extension install  Open Chrome Web Store")
    print()
    print("  ACCOUNT")
    print("    mp login              Connect to platform (opens browser)")
    print("    mp consent            Change capture, research, and redaction settings")
    print("    mp delete <id>        Delete a session and all its data")
    print("    mp update             Update to the latest version")
    print("    mp uninstall          Remove all hooks, data, and config")
    print()
    print("  To view this at any time run: mp help\n")


def cmd_uninstall(args: argparse.Namespace) -> None:
    """Remove all MethodProof hooks, data, and config."""
    import shutil

    if not args.force:
        sessions = store.list_sessions()
        unsynced = [s for s in sessions if not s["synced"]]
        if unsynced:
            print(f"  Warning: {len(unsynced)} session(s) not pushed to platform.")
        answer = input("\n  Remove all MethodProof data and hooks? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("  Cancelled.")
            return

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
        shutil.rmtree(config.DIR)
        removed.append(str(config.DIR))

    if removed:
        print("\n  Removed:")
        for r in removed:
            print(f"    {r}")
    print("\n  To remove the CLI itself: pip uninstall methodproof")
    print("  Restart your shell to clear hooks.\n")


def cmd_consent(args: argparse.Namespace) -> None:
    """Review or change capture, research, and redaction settings."""
    cfg = config.load()
    cfg = _run_consent(cfg)
    config.save(cfg)
    print(f"\n{_banner()} settings saved.\n")
    _print_commands()


def _is_daemon_alive() -> bool:
    """Check if the recording daemon is still running."""
    if not PIDFILE.exists():
        return False
    try:
        pid = int(PIDFILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 = check existence without killing
        return True
    except (ProcessLookupError, ValueError, OSError):
        return False


def cmd_start(args: argparse.Namespace) -> None:
    cfg = config.load()
    if cfg.get("active_session"):
        if _is_daemon_alive():
            print(f"Session active: {cfg['active_session'][:8]}")
            print("Run `methodproof stop` first.")
            sys.exit(1)
        # Daemon is dead — clean up the stale session
        stale_sid = cfg["active_session"]
        store.complete_session(stale_sid)
        graph.build(stale_sid)
        PIDFILE.unlink(missing_ok=True)
        cfg["active_session"] = None
        config.save(cfg)
        print(f"Cleaned up stale session {stale_sid[:8]} (daemon was not running).")
    if not hook.is_installed():
        print("Run `methodproof init` first.")
        sys.exit(1)

    # Check for new consent categories before recording
    capture = cfg.get("capture", {})
    new_cats = (set(config.STANDARD_CATEGORIES) | {"code_capture"}) - set(capture.keys())
    if new_cats:
        print(f"\n  New capture categories available: {', '.join(sorted(new_cats))}")
        print("  Please review your consent settings before recording.\n")
        cfg = _run_consent(cfg)
        config.save(cfg)
        print()

    sid = uuid.uuid4().hex
    watch_dir = os.path.abspath(args.dir or ".")
    repo_url = args.repo or repos.detect_repo(watch_dir)
    tags = args.tags.split(",") if args.tags else []
    visibility = "public" if args.public else "private"
    store.create_session(sid, watch_dir, repo_url, json.dumps(tags), visibility)
    cfg["active_session"] = sid
    config.save(cfg)
    PIDFILE.write_text(str(os.getpid()))

    from methodproof.agents import base
    live_ok = False
    capture = cfg.get("capture", {})

    live_url = ""
    if args.live:
        if not cfg.get("token"):
            print("Live mode requires login. Run `methodproof login` first.")
            sys.exit(1)
        # Create remote session first
        from methodproof.sync import _request
        result = _request("POST", "/personal/sessions", cfg["api_url"], cfg["token"])
        remote_id = result["session_id"]
        store.mark_synced(sid, remote_id)
        # Connect live WebSocket
        from methodproof import live as live_mod
        live_url = live_mod.start(cfg["api_url"], cfg["token"], remote_id, capture) or ""
        if not live_url:
            print("Live stream rejected — requires Pro plan or full-spectrum consent.")
            sys.exit(1)

    base.init(sid, live=bool(live_url))

    if capture.get("environment_analysis", True):
        from methodproof.analysis import scan_environment
        try:
            env_profile = scan_environment(watch_dir)
            base.emit("environment_profile", env_profile)
        except Exception:
            base.log("warning", "environment_scan.failed")

    stop_event = threading.Event()

    threads: list[threading.Thread] = []

    # File watcher — if any file/git category is enabled
    files_enabled = (
        capture.get("file_changes", True)
        or capture.get("git_diffs", True)
        or capture.get("git_commits", True)
    )
    if files_enabled:
        from methodproof.agents import watcher
        threads.append(threading.Thread(target=watcher.start, args=(watch_dir, stop_event), daemon=True))

    # Terminal monitor — if terminal or test categories enabled
    if capture.get("terminal_commands", True) or capture.get("test_results", True):
        from methodproof.agents import terminal
        threads.append(threading.Thread(target=terminal.start, args=(stop_event,), daemon=True))

    # Bridge — if browser category enabled
    if capture.get("browser", True):
        from methodproof import bridge
        threads.append(threading.Thread(target=bridge.start, args=(
            sid, stop_event, 9877,
            cfg.get("token", ""), cfg.get("api_url", ""), cfg.get("e2e_key", ""),
        ), daemon=True))

    # Music — if music category enabled
    if capture.get("music", True):
        from methodproof.agents import music
        threads.append(threading.Thread(target=music.start, args=(stop_event,), daemon=True))

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

    def _shutdown(sig: int, frame: object) -> None:
        stop_event.set()
        try:
            if live_url:
                from methodproof import live as live_mod
                live_mod.stop()
            base.flush()
            store.complete_session(sid)
            graph.build(sid)
        except Exception:
            pass
        try:
            cfg_now = config.load()
            cfg_now["active_session"] = None
            config.save(cfg_now)
        except Exception:
            pass
        PIDFILE.unlink(missing_ok=True)
        sys.exit(0)

    # Daemonize: fork into background so the terminal is free
    if sys.platform != "win32":
        child = os.fork()
        if child > 0:
            # Parent: write child PID and exit
            PIDFILE.write_text(str(child))
            # Brief pause for extension auto-discovery (extension polls every ~6s in dev)
            if capture.get("browser", True):
                import urllib.request as _ur
                time.sleep(8)
                try:
                    with _ur.urlopen("http://127.0.0.1:9877/extension-status", timeout=2) as resp:
                        ext_data = json.loads(resp.read())
                    if ext_data.get("paired"):
                        print(f"Extension: connected")
                    else:
                        print(f"Extension: not detected — run `mp extension pair` or install from store")
                except Exception:
                    print(f"Extension: not detected")
            print("Run `mp stop` to finish.")
            return
        # Child: detach and run in background
        os.setsid()
        # Redirect stdio to /dev/null so writes don't fail after terminal closes
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)
        store.reset_connection()
        for t in threads:
            t.start()
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
        try:
            while not stop_event.is_set():
                time.sleep(5)
                base.flush()
        except Exception:
            _shutdown(0, None)
        return

    # Windows: foreground mode (no fork)
    for t in threads:
        t.start()
    signal.signal(signal.SIGINT, _shutdown)
    print("Press Ctrl+C or run `mp stop` to finish.")
    stopfile = config.DIR / "methodproof.stop"
    while not stop_event.is_set():
        if stopfile.exists():
            stopfile.unlink(missing_ok=True)
            _shutdown(0, None)
        time.sleep(5)
        base.flush()


def cmd_stop(args: argparse.Namespace) -> None:
    cfg = config.load()
    sid = cfg.get("active_session")
    if not sid:
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


def cmd_login(args: argparse.Namespace) -> None:
    import webbrowser
    from methodproof.sync import _request

    cfg = config.load()
    api = args.api_url or cfg["api_url"]

    # Start device auth flow
    result = _request("POST", "/auth/cli/start", api, "")
    code = result["code"]
    auth_url = result["auth_url"]

    print(f"\nOpening browser to sign in...\n")
    print(f"  {auth_url}\n")
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
                config.save(cfg)
                print(" done.\n")
                print("Logged in. Run `methodproof push` to upload sessions.")
                return
        except Exception:
            pass
        print(".", end="", flush=True)

    print("\n\nAuthorization timed out. Run `methodproof login` to try again.")


def cmd_push(args: argparse.Namespace) -> None:
    cfg = config.load()
    if not cfg.get("token"):
        print("Run `methodproof login` first.")
        sys.exit(1)
    sid = args.session_id or _latest()
    if not sid:
        print("No sessions to push.")
        sys.exit(1)
    from methodproof.sync import push
    push(sid, cfg["token"], cfg["api_url"])
    print(f"Pushed {sid[:8]} (private). Use `mp publish` to make public.")


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
        push(session["id"], cfg["token"], cfg["api_url"])
    else:
        from methodproof.sync import sync_metadata
        sync_metadata(session, cfg["token"], cfg["api_url"])
    print(f"Published {session['id'][:8]} (public).")


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
    session = _resolve_session(args.session_id)
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
    p = argparse.ArgumentParser(prog="methodproof", description=_banner())
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("init", help="Install shell hook")
    s = sub.add_parser("start", help="Start recording")
    s.add_argument("--dir", help="Directory to watch")
    s.add_argument("--repo", help="Git remote URL (overrides auto-detect)")
    s.add_argument("--public", action="store_true", help="Set visibility to public")
    s.add_argument("--tags", help="Comma-separated tags")
    s.add_argument("--live", action="store_true", help="Stream events live to platform")
    sub.add_parser("stop", help="Stop recording")
    v = sub.add_parser("view", help="Inspect captured session data")
    v.add_argument("session_id", nargs="?")
    sub.add_parser("log", help="List sessions")
    l = sub.add_parser("login", help="Connect to platform")
    l.add_argument("--api-url")
    pu = sub.add_parser("push", help="Upload privately to your account")
    pu.add_argument("session_id", nargs="?")
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
    sub.add_parser("consent", help="Change capture, research, and redaction settings")
    sub.add_parser("update", help="Update to the latest version from PyPI")
    un = sub.add_parser("uninstall", help="Remove all hooks, data, and config")
    un.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    ext = sub.add_parser("extension", help="Browser extension pairing and status")
    ext_sub = ext.add_subparsers(dest="ext_cmd")
    ext_sub.add_parser("pair", help="Pair extension to active session")
    ext_sub.add_parser("status", help="Check extension connection")
    ext_sub.add_parser("install", help="Open Chrome Web Store listing")
    sub.add_parser("help", help="Show command reference")
    sub.add_parser("mcp-serve", help="Run MCP server (used by Claude Code)")

    args = p.parse_args()
    cmds = {
        "init": cmd_init, "start": cmd_start, "stop": cmd_stop,
        "view": cmd_view, "log": cmd_log, "login": cmd_login,
        "push": cmd_push, "tag": cmd_tag, "publish": cmd_publish,
        "delete": cmd_delete, "review": cmd_review, "consent": cmd_consent,
        "update": cmd_update, "uninstall": cmd_uninstall,
        "extension": cmd_extension,
        "help": lambda _: _print_commands(),
        "mcp-serve": cmd_mcp_serve,
    }
    fn = cmds.get(args.cmd)
    if not fn:
        _print_commands()
        sys.exit(1)

    # Background update check (once per day, non blocking)
    if args.cmd not in ("help", "update", "uninstall", "mcp-serve"):
        _update_check()

    if args.cmd not in ("help", "update"):
        store.init_db()
    fn(args)
