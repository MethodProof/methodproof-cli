"""MethodProof CLI — see how you code.

Usage:
    methodproof init              Install shell hook, create data directory
    methodproof start [--dir .] [--repo URL] [--tags t1,t2] [--public]
    methodproof stop              Stop recording, build process graph
    methodproof view [id]         View session graph in browser
    methodproof log               List local sessions
    methodproof tag <id> <tags>   Tag a session (comma-separated)
    methodproof publish [id]      Set public visibility and push
    methodproof login             Connect to MethodProof platform
    methodproof push [id]         Upload session to platform
"""

import argparse
import getpass
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
_ALIAS_LINE = '\n# methodproof-alias\nalias mp="methodproof"\n'


def _install_alias() -> None:
    """Add `alias mp=methodproof` to the user's shell rc file."""
    shell = os.environ.get("SHELL", "/bin/bash")
    from pathlib import Path
    rc = Path.home() / (".zshrc" if "zsh" in shell else ".bashrc")
    if rc.exists() and _ALIAS_MARKER in rc.read_text():
        return
    with rc.open("a") as f:
        f.write(_ALIAS_LINE)


def _run_consent(cfg: dict) -> dict:
    """Interactive capture category selection. Returns updated config."""
    capture = cfg.get("capture", dict(config._DEFAULTS["capture"]))
    keys = list(config.CAPTURE_DESCRIPTIONS.keys())

    print(f"\n{_banner()}\n")
    print("Built by engineers, for engineers.")
    print()
    print("We don't just write code — we each have a flow, a rhythm, a craft.")
    print("MethodProof exists to make that visible. Every debug session, every")
    print("refactor, every late-night breakthrough is part of your story.")
    print()
    print("Help us build the greatest tool for understanding how engineers")
    print("actually work — not how we're told to work, but how we really do.")
    print()
    print("The more you share, the better the picture. Full Spectrum opt-in")
    print("unlocks live streaming on the free tier so others can watch your")
    print("process graph form in real-time. Your call, your data, your flow.")
    print()
    print("All data stays local in ~/.methodproof/. Nothing leaves your")
    print("machine unless you explicitly run `methodproof push`.\n")

    while True:
        for i, key in enumerate(keys, 1):
            mark = "x" if capture.get(key, True) else " "
            desc = config.CAPTURE_DESCRIPTIONS[key]
            print(f"  [{mark}] {i}. {key:<20s} {desc}")

        enabled = sum(1 for k in keys if capture.get(k, True))
        full = enabled == len(keys)
        label = _rainbow("Full Spectrum") if full else f"{enabled}/{len(keys)} categories"
        print(f"\n  {label} enabled")
        print("  Toggle: enter number | a = all on | n = all off | done = confirm\n")

        choice = input("  > ").strip().lower()
        if choice in ("done", "d", ""):
            if enabled == 0:
                print("  At least one category must be enabled.\n")
                continue
            break
        elif choice == "a":
            for k in keys:
                capture[k] = True
        elif choice == "n":
            for k in keys:
                capture[k] = False
        elif choice.isdigit() and 1 <= int(choice) <= len(keys):
            k = keys[int(choice) - 1]
            capture[k] = not capture.get(k, True)
        else:
            print(f"  Unknown input: {choice}\n")
        print()

    cfg["capture"] = capture
    cfg["consent_acknowledged"] = True

    is_full = all(capture.get(k, True) for k in keys)
    if is_full:
        print(f"\n  {_rainbow('Full Spectrum')} — live streaming unlocked on free tier.")
    else:
        print(f"\n  {enabled}/{len(keys)} categories. Enable all for free live streaming.")

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
            print("OpenClaw: not found (hooks + skill skipped)")
        else:
            print(f"OpenClaw hooks: {oc_result}")
            skill_result = install_skill()
            if skill_result:
                print(f"OpenClaw skill: {skill_result}")
    else:
        print("AI hooks: skipped (ai_prompts and ai_responses disabled)")

    print(f"\n{_banner()}")
    print("Restart your shell, then run: methodproof start")


def cmd_consent(args: argparse.Namespace) -> None:
    """Review or change capture categories."""
    cfg = config.load()
    cfg = _run_consent(cfg)
    config.save(cfg)
    print(f"\n{_banner()} — capture settings saved.")


def cmd_start(args: argparse.Namespace) -> None:
    cfg = config.load()
    if cfg.get("active_session"):
        print(f"Session active: {cfg['active_session'][:8]}")
        print("Run `methodproof stop` first.")
        sys.exit(1)
    if not hook.is_installed():
        print("Run `methodproof init` first.")
        sys.exit(1)

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
        live_ok = live_mod.start(cfg["api_url"], cfg["token"], remote_id, capture)
        if not live_ok:
            print("Live stream rejected — requires Pro plan or full-spectrum consent.")
            sys.exit(1)

    base.init(sid, live=live_ok)
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
        threads.append(threading.Thread(target=bridge.start, args=(sid, stop_event, 9877), daemon=True))

    # Music — if music category enabled
    if capture.get("music", True):
        from methodproof.agents import music
        threads.append(threading.Thread(target=music.start, args=(stop_event,), daemon=True))

    for t in threads:
        t.start()

    active = [k for k, v in capture.items() if v]
    print(f"\n{_banner()}")
    print(f"Recording: {sid[:8]}")
    print(f"Watching:  {watch_dir}")
    if repo_url:
        print(f"Repo:      {repo_url}")
    print(f"Capture:   {', '.join(active)}")
    if capture.get("browser", True):
        print(f"Bridge:    http://localhost:9877")
    if live_ok:
        print(f"Live:      streaming to {cfg['api_url']}")
    print("Press Ctrl+C or run `methodproof stop` to finish.")

    def _shutdown(sig: int, frame: object) -> None:
        stop_event.set()
        if live_ok:
            from methodproof import live as live_mod
            live_mod.stop()
        base.flush()
        store.complete_session(sid)
        stats = graph.build(sid)
        session = store.get_session(sid)
        cfg = config.load()
        cfg["active_session"] = None
        config.save(cfg)
        PIDFILE.unlink(missing_ok=True)
        _print_summary(session, stats)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while not stop_event.is_set():
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
            os.kill(pid, signal.SIGTERM)
            print(f"Stopping session {sid[:8]}...")
            time.sleep(3)
            return
        except (ProcessLookupError, ValueError):
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
    sid = args.session_id or _latest()
    if not sid:
        print("No sessions. Run `methodproof start` first.")
        sys.exit(1)
    from methodproof.viewer import serve
    serve(sid, port=int(args.port or 9876))


def cmd_log(args: argparse.Namespace) -> None:
    sessions = store.list_sessions()
    if not sessions:
        print("No sessions yet.")
        return
    for s in sessions:
        sync_tag = "synced" if s["synced"] else "local"
        dt = datetime.fromtimestamp(s["created_at"], tz=UTC).strftime("%Y-%m-%d %H:%M")
        dur = _duration(s)
        vis = s.get("visibility", "private")
        tags = json.loads(s.get("tags") or "[]")
        suffix = f"  [{sync_tag}]"
        if vis != "private":
            suffix += f"  {vis}"
        if tags:
            suffix += f"  #{','.join(tags)}"
        print(f"  {s['id'][:8]}  {dt}  {dur}  {s['total_events']} events{suffix}")


def cmd_login(args: argparse.Namespace) -> None:
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    action = input("Login or Register? [l/r]: ").strip().lower()

    from methodproof.sync import _request
    cfg = config.load()
    api = args.api_url or cfg["api_url"]

    if action.startswith("r"):
        result = _request("POST", "/personal/register", api, "",
                          {"email": email, "password": password})
        print("Registered.")
    else:
        result = _request("POST", "/auth/login", api, "",
                          {"email": email, "password": password})
        print("Logged in.")

    cfg["token"] = result["token"]
    cfg["email"] = email
    cfg["api_url"] = api
    config.save(cfg)


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
    store.update_visibility(session["id"], "public")
    session["visibility"] = "public"
    if not session["synced"]:
        from methodproof.sync import push
        push(session["id"], cfg["token"], cfg["api_url"])
    else:
        from methodproof.sync import sync_metadata
        sync_metadata(session, cfg["token"], cfg["api_url"])
    print(f"Published: {session['id'][:8]}")


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


def cmd_mcp_serve(args: argparse.Namespace) -> None:
    from methodproof.mcp import serve
    serve()


def _latest() -> str | None:
    sessions = store.list_sessions()
    return sessions[0]["id"] if sessions else None


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
    print(f"\nRun `methodproof view` to explore.")


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
    v = sub.add_parser("view", help="View session graph")
    v.add_argument("session_id", nargs="?")
    v.add_argument("--port", default="9876")
    sub.add_parser("log", help="List sessions")
    l = sub.add_parser("login", help="Connect to platform")
    l.add_argument("--api-url")
    pu = sub.add_parser("push", help="Upload to platform")
    pu.add_argument("session_id", nargs="?")
    tg = sub.add_parser("tag", help="Tag a session")
    tg.add_argument("session_id", help="Session ID (prefix ok)")
    tg.add_argument("tags", help="Comma-separated tags")
    pb = sub.add_parser("publish", help="Set public and push")
    pb.add_argument("session_id", nargs="?")
    dl = sub.add_parser("delete", help="Delete a session and all its data")
    dl.add_argument("session_id", help="Session ID (prefix ok)")
    dl.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    sub.add_parser("consent", help="Review or change capture categories")
    sub.add_parser("mcp-serve", help="Run MCP server (used by Claude Code)")

    args = p.parse_args()
    cmds = {
        "init": cmd_init, "start": cmd_start, "stop": cmd_stop,
        "view": cmd_view, "log": cmd_log, "login": cmd_login,
        "push": cmd_push, "tag": cmd_tag, "publish": cmd_publish,
        "delete": cmd_delete, "consent": cmd_consent,
        "mcp-serve": cmd_mcp_serve,
    }
    fn = cmds.get(args.cmd)
    if not fn:
        p.print_help()
        sys.exit(1)

    store.init_db()
    fn(args)
