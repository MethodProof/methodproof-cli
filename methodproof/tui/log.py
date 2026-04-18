"""Textual TUI for mp log — session browser with inline detail screen."""
from __future__ import annotations

import json
from datetime import datetime, UTC

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from methodproof import store
from methodproof.tui.theme import ACTIVE, BASE_CSS, BORDER, DIM, GOLD, GREEN, PURPLE, RED, TEXT
from methodproof.viewer import SENSITIVE_FIELDS, _event_summary, _offset

_CSS = BASE_CSS + f"""
#sessions-table {{
    width: 3fr;
    border-right: solid {ACTIVE.border};
}}
#preview-pane {{
    width: 1fr;
    padding: 1 2;
    background: {ACTIVE.sidebar_bg};
}}
.preview-meta {{
    color: {TEXT};
    text-style: bold;
    margin: 0 0 1 0;
}}
.preview-dim {{
    color: {DIM};
}}
.preview-section {{
    color: {GOLD};
    text-style: bold;
    margin: 1 0 0 0;
}}
#detail-scroll {{
    padding: 1 3;
}}
#detail-content {{
    width: 100%;
}}
"""

_DT_FMT = "%b %d %H:%M"


def _fmt_dur(seconds: int) -> str:
    h, m = seconds // 3600, (seconds % 3600) // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _fmt_events(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


class DetailScreen(Screen):
    """Full-screen session detail view — esc returns to the list."""

    BINDINGS = [
        Binding("escape", "back", "back"),
        Binding("q", "back", "back"),
    ]

    def __init__(self, session: dict) -> None:
        super().__init__()
        self._session = session

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="detail-scroll"):
            yield Static(self._render(), id="detail-content")
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()

    def _render(self) -> str:
        sess = self._session
        sid = (sess.get("id") or "")[:8]
        created = sess.get("created_at", 0)
        completed = sess.get("completed_at")
        dt_str = datetime.fromtimestamp(created, tz=UTC).strftime(_DT_FMT) if created else "—"
        dur = _fmt_dur(int((completed or created) - created)) if completed else "in progress"
        vis = sess.get("visibility", "private")
        synced = "synced" if sess.get("synced") else "local"
        tags = json.loads(sess.get("tags") or "[]")
        repo = sess.get("repo_url") or "—"

        events = store.get_events(sess["id"], decrypt=True)

        lines = [
            f"[bold {GOLD}]session {sid}[/bold {GOLD}]",
            f"[{DIM}]{dt_str}  ·  {dur}  ·  {len(events)} events  ·  {vis}  ·  {synced}[/{DIM}]",
            f"[{DIM}]repo: {repo}[/{DIM}]",
        ]
        if tags:
            lines.append(f"[{DIM}]tags: {', '.join(tags)}[/{DIM}]")

        if not events:
            lines.append("")
            lines.append(f"[{DIM}]no events captured[/{DIM}]")
            return "\n".join(lines)

        by_type: dict[str, list[dict]] = {}
        for e in events:
            by_type.setdefault(e["type"], []).append(e)

        total = len(events)
        lines.append("")
        lines.append(f"[bold {GOLD}]Event mix[/bold {GOLD}]")
        for etype, items in sorted(by_type.items(), key=lambda x: -len(x[1])):
            pct = len(items) / total
            bar_len = max(1, int(pct * 18))
            bar = "█" * bar_len + "░" * (18 - bar_len)
            lines.append(
                f"[{DIM}]{etype:<20}[/{DIM}] "
                f"[{TEXT}]{len(items):>5}[/{TEXT}]  "
                f"[{GREEN}]{bar}[/{GREEN}] "
                f"[{DIM}]{int(pct * 100):>3}%[/{DIM}]"
            )

        start_ts = events[0]["timestamp"]
        lines.append("")
        lines.append(f"[bold {GOLD}]Timeline[/bold {GOLD}]")
        for etype, items in sorted(by_type.items(), key=lambda x: -len(x[1])):
            lines.append("")
            lines.append(f"[{PURPLE}]{etype}[/{PURPLE}] [{DIM}]({len(items)})[/{DIM}]")
            for e in items:
                ts = _offset(e["timestamp"], start_ts)
                meta = json.loads(e.get("metadata") or "{}")
                summary = _event_summary(etype, meta) or ""
                lines.append(f"  [{DIM}]{ts}[/{DIM}]  [{TEXT}]{summary}[/{TEXT}]")

        return "\n".join(lines)


class LogApp(App[None]):
    """Session browser — ↑↓ navigate, enter details, esc back/quit, p push."""

    TITLE = "methodproof — mp log"
    CSS = _CSS
    BINDINGS = [
        Binding("p", "push_session", "push"),
        Binding("enter", "view_session", "view"),
        Binding("escape", "quit", "quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._sessions: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            yield DataTable(id="sessions-table", cursor_type="row")
            with Vertical(id="preview-pane"):
                yield Static("", id="preview-content")
        yield Footer()

    def on_mount(self) -> None:
        self._sessions = store.list_sessions()
        table = self.query_one(DataTable)
        table.add_columns("Date", "Duration", "Events", "Tags", "Sync", "Visibility")

        n_unsynced = 0
        for sess in self._sessions:
            created = sess.get("created_at", 0)
            completed = sess.get("completed_at")
            dt_str = datetime.fromtimestamp(created, tz=UTC).strftime(_DT_FMT) if created else "—"
            dur = _fmt_dur(int((completed or created) - created)) if completed else "—"
            ev = _fmt_events(sess.get("total_events", 0))
            tags = sess.get("tags") or "—"
            synced = "●" if sess.get("synced") else "○"
            vis = sess.get("visibility", "private")
            if not sess.get("synced") and completed:
                n_unsynced += 1
            table.add_row(dt_str, dur, ev, tags, synced, vis)

        badge = f" — {n_unsynced} unsynced" if n_unsynced else ""
        self.title = f"methodproof — mp log  ({len(self._sessions)} sessions{badge})"

        if self._sessions:
            self._update_preview(0)
        table.focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_preview(event.cursor_row)

    def _update_preview(self, row: int) -> None:
        if row >= len(self._sessions):
            return
        sess = self._sessions[row]
        created = sess.get("created_at", 0)
        completed = sess.get("completed_at")
        dt_str = datetime.fromtimestamp(created, tz=UTC).strftime(_DT_FMT) if created else "—"
        dur = _fmt_dur(int((completed or created) - created)) if completed else "in progress"
        ev = sess.get("total_events", 0)
        tags = sess.get("tags") or "none"
        sid = (sess.get("id") or "")[:8]

        ev_counts: dict = sess.get("event_counts", {})
        moments: list = sess.get("moments", [])

        lines = [
            f"[bold {TEXT}]{dt_str}[/bold {TEXT}]",
            f"[{DIM}]{dur}  ·  {ev} events[/{DIM}]",
            f"[{DIM}]{sid}[/{DIM}]",
            "",
            f"[{DIM}]enter: details  ·  p: push  ·  esc: quit[/{DIM}]",
            "",
        ]

        if moments:
            lines.append(f"[bold {GOLD}]Moments[/bold {GOLD}]")
            for m in moments[:4]:
                mtype = m.get("type", "")
                lines.append(f"[{DIM}]· {mtype}[/{DIM}]")
            lines.append("")

        if ev_counts:
            lines.append(f"[bold {GOLD}]Event mix[/bold {GOLD}]")
            for etype, count in sorted(ev_counts.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"[{DIM}]{etype:<16}[/{DIM}][{TEXT}]{count}[/{TEXT}]")

        self.query_one("#preview-content", Static).update("\n".join(lines))

    def action_push_session(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        if row is None or row >= len(self._sessions):
            return
        sid = self._sessions[row].get("id", "")
        self.exit(("push", sid))

    def action_view_session(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        if row is None or row >= len(self._sessions):
            return
        self.push_screen(DetailScreen(self._sessions[row]))


def run() -> tuple[str, str] | None:
    """Launch the session browser. Returns (action, session_id) or None."""
    return LogApp().run()
