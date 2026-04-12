"""Textual TUI for mp start — live session event feed."""
from __future__ import annotations

import json
import time
from datetime import datetime, UTC

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, RichLog, Static
from methodproof import config, store
from methodproof.tui.theme import BASE_CSS, BORDER, DIM, GOLD, GREEN, PURPLE, RED, TEXT

_CSS = BASE_CSS + f"""
#session-bar {{
    background: #1c1a18;
    height: 1;
    padding: 0 2;
    color: {DIM};
}}
#feed {{
    width: 3fr;
    border-right: solid {BORDER};
    padding: 0 1;
}}
#sidebar {{
    width: 22;
    padding: 1 2;
    background: #0a0908;
}}
.sidebar-title {{
    color: {GOLD};
    text-style: bold;
    margin: 0 0 1 0;
}}
.stat-row {{
    color: {DIM};
    height: 1;
}}
#moment-alert {{
    background: #1a1408;
    border: solid #3a2e10;
    margin: 1 1;
    padding: 0 1;
    height: 3;
    display: none;
}}
#moment-alert.visible {{
    display: block;
}}
"""

_EVENT_COLORS = {
    "file_edit": GREEN, "file_create": GREEN, "file_delete": RED,
    "terminal_cmd": TEXT, "test_run": GOLD, "git_commit": GOLD,
    "llm_prompt": PURPLE, "llm_completion": PURPLE,
    "agent_prompt": PURPLE, "agent_completion": PURPLE,
    "browser_visit": DIM, "browser_search": DIM,
    "music_playing": DIM,
}

_POLL_INTERVAL = 0.5  # seconds between store polls


class StartApp(App[None]):
    """Live session view — tails the active session's events."""

    TITLE = "methodproof — mp start"
    CSS = _CSS
    BINDINGS = [
        Binding("q", "stop_session", "stop"),
        Binding("p", "pause", "pause"),
        Binding("l", "toggle_live", "toggle live"),
        Binding("escape", "quit", "quit"),
    ]

    _elapsed: reactive[int] = reactive(0)
    _paused: reactive[bool] = reactive(False)
    _event_count: int = 0
    _last_seen_id: str = ""

    def __init__(self, session_id: str, session: dict) -> None:
        super().__init__()
        self._session_id = session_id
        self._session = session
        self._stats: dict[str, int] = {}
        self._start_time = session.get("created_at", time.time())

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        watch_dir = self._session.get("watch_dir", "?")
        sid = self._session_id[:8]
        yield Static(
            f"  session: [{GOLD}]{sid}[/{GOLD}]  ·  {watch_dir}  ·  [{GREEN}]●[/{GREEN}]  00:00:00",
            id="session-bar",
            markup=True,
        )
        with Horizontal():
            with Vertical(id="feed-col"):
                yield RichLog(id="feed", highlight=True, markup=True, wrap=False)
                yield Static("", id="moment-alert", markup=True)
            with Vertical(id="sidebar"):
                yield Static("Stats", classes="sidebar-title")
                yield Static("", id="stats-content", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        import base64
        cfg = config.load()
        token = cfg.get("token", "")
        try:
            payload = token.split(".")[1] + "=="
            claims = json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            claims = {}
        self._account_type = (claims.get("account_type") or "free").capitalize()
        self.set_interval(_POLL_INTERVAL, self._poll_events)
        self.set_interval(1.0, self._tick_timer)

    def _tick_timer(self) -> None:
        if self._paused:
            return
        elapsed = int(time.time() - self._start_time)
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        sid = self._session_id[:8]
        watch_dir = self._session.get("watch_dir", "?")
        self.query_one("#session-bar", Static).update(
            f"  session: [{GOLD}]{sid}[/{GOLD}]  ·  {watch_dir}  ·  [{GREEN}]●[/{GREEN}]"
            f"  {h:02d}:{m:02d}:{s:02d}  ·  [{PURPLE}]{self._account_type}[/{PURPLE}]"
        )

    def _poll_events(self) -> None:
        if self._paused:
            return
        try:
            events = store.get_session_events(self._session_id, after_id=self._last_seen_id)
        except Exception as exc:
            self.log.warning(f"poll_events failed: {exc}")
            return

        feed = self.query_one(RichLog)
        for ev in events:
            self._last_seen_id = ev.get("id", self._last_seen_id)
            etype = ev.get("type", "event")
            color = _EVENT_COLORS.get(etype, DIM)
            ts = datetime.fromtimestamp(ev.get("ts", time.time()), tz=UTC).strftime("%H:%M:%S")
            meta = _fmt_meta(ev)
            feed.write(
                f"[{DIM}]{ts}[/{DIM}]  [{color}]{etype:<18}[/{color}] [{DIM}]{meta}[/{DIM}]"
            )
            self._stats[etype] = self._stats.get(etype, 0) + 1
            self._event_count += 1

        if events:
            self._refresh_stats()

    def _refresh_stats(self) -> None:
        lines = []
        for etype, count in sorted(self._stats.items(), key=lambda x: -x[1])[:10]:
            color = _EVENT_COLORS.get(etype, DIM)
            lines.append(f"[{DIM}]{etype:<14}[/{DIM}] [{color}]{count}[/{color}]")
        self.query_one("#stats-content", Static).update("\n".join(lines))

    def _show_moment(self, mtype: str, detail: str) -> None:
        alert = self.query_one("#moment-alert", Static)
        alert.update(f"  [{GOLD}]⚡ {mtype}[/{GOLD}]  [{DIM}]{detail}[/{DIM}]")
        alert.add_class("visible")
        self.set_timer(4.0, lambda: alert.remove_class("visible"))

    def action_stop_session(self) -> None:
        self.exit(None)

    def action_pause(self) -> None:
        self._paused = not self._paused

    def action_toggle_live(self) -> None:
        pass  # handled by caller in cli.py


def _fmt_meta(ev: dict) -> str:
    etype = ev.get("type", "")
    meta = ev.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    if etype in ("file_edit", "file_create", "file_delete"):
        path = meta.get("path") or meta.get("file_path", "")
        delta = meta.get("line_delta") or meta.get("lines_added", "")
        return f"{path}  {f'+{delta}' if delta else ''}".strip()
    if etype == "terminal_cmd":
        cmd = (meta.get("command") or "")[:40]
        ec = meta.get("exit_code", 0)
        return f"{cmd}  {'✓' if ec == 0 else f'✗{ec}'}"
    if etype == "git_commit":
        return (meta.get("message") or "")[:40]
    if etype in ("llm_prompt", "agent_prompt"):
        tokens = meta.get("prompt_tokens") or meta.get("input_length", "")
        return f"{tokens} tokens" if tokens else ""
    if etype in ("llm_completion", "agent_completion"):
        tokens = meta.get("completion_tokens") or meta.get("output_length", "")
        dur = ev.get("duration_ms", "")
        return f"{tokens} tokens  {dur}ms" if tokens else ""
    if etype == "test_run":
        p, f = meta.get("passed", 0), meta.get("failed", 0)
        return f"{p} passed  {f} failed" if f else f"{p} passed"
    return ""


def run(session_id: str, session: dict) -> None:
    """Launch the live session view for the given session."""
    StartApp(session_id, session).run()
