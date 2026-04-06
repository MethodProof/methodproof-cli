"""Daemon process for methodproof capture — spawned by cmd_start via subprocess.

Uses subprocess.Popen (fork+exec) instead of os.fork() to avoid macOS
CoreFoundation segfaults when forking a multi-threaded Python 3.12+ process.
"""

import signal
import sys
import threading
import time

from methodproof import config, store, graph
from methodproof.agents import base

PIDFILE = config.DIR / "methodproof.pid"


def main() -> None:
    sid = sys.argv[1]
    watch_dir = sys.argv[2]

    cfg = config.load()
    capture = cfg.get("capture", {})
    live_url = cfg.get("_live_url", "")

    # Clean up transient key
    if "_live_url" in cfg:
        del cfg["_live_url"]
        config.save(cfg)

    base.init(sid, live=bool(live_url))

    # Environment profile (was done pre-fork in old code, now done in daemon)
    if capture.get("environment_analysis", True):
        try:
            from methodproof.analysis import scan_environment
            env_profile = scan_environment(watch_dir)
            base.emit("environment_profile", env_profile)
        except Exception as exc:
            base.log("warning", "environment_scan.failed", error=str(exc))

    stop_event = threading.Event()
    threads: list[threading.Thread] = []

    files_enabled = (
        capture.get("file_changes", True)
        or capture.get("git_diffs", True)
        or capture.get("git_commits", True)
    )
    if files_enabled:
        from methodproof.agents import watcher
        threads.append(threading.Thread(
            target=watcher.start, args=(watch_dir, stop_event), daemon=True,
        ))

    if capture.get("terminal_commands", True) or capture.get("test_results", True):
        from methodproof.agents import terminal
        threads.append(threading.Thread(
            target=terminal.start, args=(stop_event,), daemon=True,
        ))

    if capture.get("browser", True):
        from methodproof import bridge
        threads.append(threading.Thread(
            target=bridge.start,
            args=(sid, stop_event, 9877,
                  cfg.get("token", ""), cfg.get("api_url", ""), cfg.get("e2e_key", "")),
            daemon=True,
        ))

    if capture.get("music", True):
        from methodproof.agents import music
        threads.append(threading.Thread(
            target=music.start, args=(stop_event,), daemon=True,
        ))

    def _shutdown(sig_num: int, frame: object) -> None:
        stop_event.set()
        try:
            if live_url:
                from methodproof import live as live_mod
                live_mod.stop()
            base.flush()
            store.complete_session(sid)
            graph.build(sid)
        except Exception as exc:
            base.log("error", "daemon.shutdown_cleanup_failed", error=str(exc))
        try:
            cfg_now = config.load()
            cfg_now["active_session"] = None
            config.save(cfg_now)
        except Exception as exc:
            base.log("error", "daemon.config_cleanup_failed", error=str(exc))
        PIDFILE.unlink(missing_ok=True)
        sys.exit(0)

    for t in threads:
        t.start()
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    base.log("info", "daemon.started", session_id=sid, watch_dir=watch_dir, agents=len(threads))

    try:
        while not stop_event.is_set():
            time.sleep(5)
            base.flush()
    except Exception as exc:
        base.log("error", "daemon.loop_crashed", error=str(exc))
        _shutdown(0, None)


if __name__ == "__main__":
    main()
