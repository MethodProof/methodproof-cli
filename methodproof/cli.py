"""MethodProof CLI — see how you code.

Usage:
    methodproof init              Install shell hook, create data directory
    methodproof start [--dir .]   Start recording a session
    methodproof stop              Stop recording, build process graph
    methodproof view [id]         View session graph in browser
    methodproof log               List local sessions
    methodproof login             Connect to MethodProof platform
    methodproof push [id]         Upload session to platform
"""

import argparse
import getpass
import os
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, UTC

from methodproof import config, store, graph, hook


def cmd_init(args: argparse.Namespace) -> None:
    config.ensure_dirs()
    store.init_db()
    rc = hook.install()
    print(f"Hook installed: {rc}")
    print("Restart your shell, then run: methodproof start")


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
    store.create_session(sid, watch_dir)
    cfg["active_session"] = sid
    config.save(cfg)

    # Start agents as threads
    from methodproof.agents import base, watcher, terminal
    base.init(sid)
    stop_event = threading.Event()

    threads = [
        threading.Thread(target=watcher.start, args=(watch_dir, stop_event), daemon=True),
        threading.Thread(target=terminal.start, args=(stop_event,), daemon=True),
    ]
    for t in threads:
        t.start()

    print(f"Recording: {sid[:8]}")
    print(f"Watching:  {watch_dir}")
    print("Press Ctrl+C or run `methodproof stop` to finish.")

    def _shutdown(sig: int, frame: object) -> None:
        stop_event.set()
        base.flush()
        store.complete_session(sid)
        stats = graph.build(sid)
        session = store.get_session(sid)
        cfg["active_session"] = None
        config.save(cfg)
        _print_summary(session, stats)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Periodic flush
    while not stop_event.is_set():
        time.sleep(5)
        base.flush()


def cmd_stop(args: argparse.Namespace) -> None:
    cfg = config.load()
    sid = cfg.get("active_session")
    if not sid:
        print("No active session.")
        sys.exit(1)

    # The start process handles its own shutdown via signals.
    # If stop is called from another terminal, we complete the session directly.
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
        tag = "synced" if s["synced"] else "local"
        dt = datetime.fromtimestamp(s["created_at"], tz=UTC).strftime("%Y-%m-%d %H:%M")
        dur = _duration(s)
        print(f"  {s['id'][:8]}  {dt}  {dur}  {s['total_events']} events  [{tag}]")


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


# --- Helpers ---

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
    print(f"\nSession: {session['id'][:8]}")
    print(f"  Events:  {session['total_events']}")
    print(f"  Duration: {_duration(session)}")
    print(f"  Graph:   {stats['next']} links, {stats['causal']} causal")
    print(f"\nRun `methodproof view` to explore.")


# --- Entry point ---

def main() -> None:
    p = argparse.ArgumentParser(prog="methodproof", description="See how you code")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("init", help="Install shell hook")
    s = sub.add_parser("start", help="Start recording")
    s.add_argument("--dir", help="Directory to watch")
    sub.add_parser("stop", help="Stop recording")
    v = sub.add_parser("view", help="View session graph")
    v.add_argument("session_id", nargs="?")
    v.add_argument("--port", default="9876")
    sub.add_parser("log", help="List sessions")
    l = sub.add_parser("login", help="Connect to platform")
    l.add_argument("--api-url")
    pu = sub.add_parser("push", help="Upload to platform")
    pu.add_argument("session_id", nargs="?")

    args = p.parse_args()
    cmds = {
        "init": cmd_init, "start": cmd_start, "stop": cmd_stop,
        "view": cmd_view, "log": cmd_log, "login": cmd_login, "push": cmd_push,
    }
    fn = cmds.get(args.cmd)
    if not fn:
        p.print_help()
        sys.exit(1)

    store.init_db()
    fn(args)
