"""Textual TUI for mp start — live session event feed.

Four display layers:
  B — Rich structural formatting for all 42 event types
  E — Causal chain tree indentation (prompt→tool→result)
  A — Journal mode content enrichment (second dim line)
  D — Enriched session bar (badges, event count)
"""
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
from methodproof.agents.base import log
from methodproof.tui.theme import ACTIVE, BASE_CSS

# ── CSS ──────────────────────────────────────────────────────────────
_CSS = BASE_CSS + f"""
#session-bar {{
    background: {ACTIVE.surface};
    height: 1;
    padding: 0 2;
    color: {ACTIVE.dim};
}}
#feed {{
    width: 3fr;
    border-right: solid {ACTIVE.border};
    padding: 0 1;
}}
#sidebar {{
    width: 22;
    padding: 1 2;
    background: {ACTIVE.sidebar_bg};
}}
.sidebar-title {{
    color: {ACTIVE.gold};
    text-style: bold;
    margin: 0 0 1 0;
}}
.stat-row {{
    color: {ACTIVE.dim};
    height: 1;
}}
#moment-alert {{
    background: {ACTIVE.gold_ember};
    border: solid {ACTIVE.gold_deep};
    margin: 1 1;
    padding: 0 1;
    height: 3;
    display: none;
}}
#moment-alert.visible {{
    display: block;
}}
"""

_POLL_INTERVAL = 0.5

# ── Layer B: Semantic color roles ──────��─────────────────────────────
_EVENT_ROLE: dict[str, str] = {
    # AI input (purple)
    "llm_prompt": "ai_input", "agent_prompt": "ai_input",
    "user_prompt": "ai_input", "tool_call": "ai_input",
    "agent_launch": "ai_input", "task_start": "ai_input",
    "permission_request": "ai_input",
    "agent_tool_dispatch": "ai_input", "agent_skill_invoke": "ai_input",
    "claude_session_start": "ai_input", "codex_session_start": "ai_input",
    "gemini_session_start": "ai_input", "kiro_session_start": "ai_input",
    # AI output (gold)
    "llm_completion": "ai_output", "agent_completion": "ai_output",
    "tool_result": "ai_output", "tool_failure": "ai_output",
    "agent_complete": "ai_output", "task_end": "ai_output",
    "agent_tool_result": "ai_output",
    "agent_turn_end": "ai_output", "agent_turn_error": "ai_output",
    "claude_session_end": "ai_output", "codex_session_end": "ai_output",
    "gemini_session_end": "ai_output", "kiro_session_end": "ai_output",
    # Human structural (cream/ink)
    "file_edit": "human", "file_create": "human", "file_delete": "human",
    "terminal_cmd": "human", "git_commit": "human",
    "cwd_changed": "human",
    "worktree_create": "human", "worktree_remove": "human",
    # Verification (green)
    "test_run": "verify",
    "browser_visit": "verify", "browser_search": "verify",
    "web_search": "verify", "web_visit": "verify",
}
# Everything else falls to "dim"

_MOMENT_TYPES = {
    "rapid_iteration", "test_driven", "git_discipline",
    "focused_session", "breakthrough", "approach_pivot",
}


def _event_color(etype: str) -> str:
    role = _EVENT_ROLE.get(etype, "dim")
    return getattr(ACTIVE, role, ACTIVE.dim)


# ── Layer E: Causal chain tree tracker ───��───────────────────────────
class _TreeTracker:
    """Track prompt→tool_call→tool_result causal chains."""

    _OPENERS = {
        "user_prompt", "agent_launch", "task_start",
        "claude_session_start", "codex_session_start",
        "gemini_session_start", "kiro_session_start",
    }
    _INNERS = {
        "tool_call", "tool_result", "tool_failure",
        "permission_request", "permission_denied",
        "agent_tool_dispatch", "agent_tool_result", "agent_skill_invoke",
        "context_compact_start", "context_compact_end",
        "cwd_changed", "mcp_elicitation", "mcp_elicitation_result",
        "worktree_create", "worktree_remove",
    }
    _CLOSERS = {
        "agent_turn_end", "agent_turn_error", "agent_complete", "task_end",
        "claude_session_end", "codex_session_end",
        "gemini_session_end", "kiro_session_end",
    }

    def __init__(self) -> None:
        self._in_chain = False

    def feed(self, etype: str) -> str:
        if etype in self._OPENERS:
            self._in_chain = True
            return "  "
        if self._in_chain:
            if etype in self._CLOSERS:
                self._in_chain = False
                return "└ "
            if etype in self._INNERS:
                return "├ "
            # Non-chain event while in chain — implicit close
            self._in_chain = False
            return "  "
        return "  "


# ── Layer B: Structural metadata formatters ──────────────────────────
def _fmt_meta(ev: dict) -> str:
    etype = ev.get("type", "")
    meta = ev.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}

    # File events
    if etype in ("file_edit", "file_create", "file_delete"):
        path = meta.get("path") or meta.get("file_path", "")
        added = meta.get("lines_added") or meta.get("line_delta", "")
        removed = meta.get("lines_removed", "")
        delta = f"+{added}" if added else ""
        if removed:
            delta += f" -{removed}"
        return f"{path}  {delta}".strip()

    # Terminal
    if etype == "terminal_cmd":
        cmd = (meta.get("command") or "")[:50]
        ec = meta.get("exit_code", 0)
        return f"{cmd}  {'✓' if ec == 0 else f'✗ exit {ec}'}"

    # Git
    if etype == "git_commit":
        h = (meta.get("hash") or "")[:7]
        msg = (meta.get("message") or "")[:40]
        return f"{h}  {msg}".strip()

    # Tests
    if etype == "test_run":
        fw = meta.get("framework", "")
        p, f = meta.get("passed", 0), meta.get("failed", 0)
        result = f"{p}✓ {f}✗" if f else f"{p}✓"
        return f"{fw}  {result}".strip()

    # LLM / agent prompts
    if etype in ("llm_prompt", "agent_prompt"):
        tokens = meta.get("prompt_tokens") or meta.get("input_length", "")
        return f"{tokens} tokens" if tokens else ""
    if etype in ("llm_completion", "agent_completion"):
        tokens = meta.get("completion_tokens") or meta.get("output_length", "")
        dur = ev.get("duration_ms", "")
        return f"{tokens} tokens  {dur}ms" if tokens else ""

    # Hook lifecycle — user prompt
    if etype == "user_prompt":
        length = meta.get("prompt_length", "")
        return f"{length} chars" if length else ""

    # Hook lifecycle — tool call / result
    if etype == "tool_call":
        name = meta.get("tool_name", "")
        preview = (meta.get("tool_input_preview") or "")[:60]
        return f"{name}  {preview}".strip()
    if etype == "tool_result":
        name = meta.get("tool_name", "")
        ok = "✓" if meta.get("success", True) else "✗"
        return f"{name}  {ok}"
    if etype == "tool_failure":
        name = meta.get("tool_name", "")
        err = (meta.get("error") or "")[:40]
        return f"{name}  ✗  {err}".strip()

    # Hook lifecycle — agents
    if etype == "agent_launch":
        return f"{meta.get('agent_type', '')}  spawned"
    if etype == "agent_complete":
        return f"{meta.get('agent_type', '')}  done"

    # Hook lifecycle — tasks
    if etype == "task_start":
        return f"task {(meta.get('task_id') or '')[:8]}"
    if etype == "task_end":
        return f"task {(meta.get('task_id') or '')[:8]}  done"

    # Hook lifecycle — permissions
    if etype == "permission_request":
        return f"{meta.get('tool_name', '')}  awaiting"
    if etype == "permission_denied":
        return f"{meta.get('tool_name', '')}  denied"

    # Session lifecycle
    if etype.endswith("_session_start"):
        return "session opened"
    if etype.endswith("_session_end"):
        return "session ended"

    # Context / system
    if etype == "context_compact_start":
        return "compacting..."
    if etype == "context_compact_end":
        return "compacted"
    if etype in ("agent_turn_end", "agent_turn_error"):
        err = (meta.get("error") or "")[:40]
        return err if err else ""
    if etype in ("cwd_changed",):
        return meta.get("cwd", "")
    if etype in ("worktree_create", "worktree_remove"):
        return meta.get("worktree_path", "")

    # Music
    if etype == "music_playing":
        artist = meta.get("artist", "")
        track = meta.get("track", "")
        return f"{artist} — {track}" if artist else track

    # Browser
    if etype.startswith("browser_") or etype.startswith("web_"):
        return (meta.get("url") or meta.get("query") or "")[:50]

    # Environment
    if etype == "environment_profile":
        return f"{meta.get('tool_count', '?')} tools"

    # Fallback: first 3 metadata keys
    keys = list(meta.keys())[:3]
    return ", ".join(f"{k}={meta[k]}" for k in keys) if keys else ""


# ── Layer A: Journal content enrichment ──���───────────────────────────
def _journal_line(ev: dict, journal_mode: bool) -> str | None:
    """Return truncated content preview when journal mode is ON."""
    if not journal_mode:
        return None
    meta = ev.get("metadata") or {}
    if not isinstance(meta, dict):
        return None
    etype = ev.get("type", "")
    for jetype, field in config.JOURNAL_CONTENT_FIELDS:
        if jetype == etype and field in meta:
            content = str(meta[field]).replace("\n", " ")[:120]
            return content if content else None
    return None


# ── App ──────────────────────────────────��───────────────────────────
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
        self._tree = _TreeTracker()
        self._journal_mode = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="session-bar", markup=True)
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
        self._journal_mode = cfg.get("journal_mode", False)
        token = cfg.get("token", "")
        try:
            payload = token.split(".")[1] + "=="
            claims = json.loads(base64.urlsafe_b64decode(payload))
        except Exception as exc:
            log("warning", "tui.jwt_decode.failed", error=str(exc))
            claims = {}
        self._account_type = (claims.get("account_type") or "free").capitalize()
        self._tick_timer()
        self.set_interval(_POLL_INTERVAL, self._poll_events)
        self.set_interval(1.0, self._tick_timer)

    # ── Layer D: Session bar ─────────────────────────────────────
    def _tick_timer(self) -> None:
        if self._paused:
            return
        P = ACTIVE
        elapsed = int(time.time() - self._start_time)
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        sid = self._session_id[:8]
        watch_dir = self._session.get("watch_dir", "?")
        journal = f"  [{P.gold}]J[/{P.gold}]" if self._journal_mode else ""
        ev = f"  {self._event_count} ev" if self._event_count else ""
        self.query_one("#session-bar", Static).update(
            f"  session: [{P.gold}]{sid}[/{P.gold}]  ·  {watch_dir}"
            f"  ·  [{P.green}]●[/{P.green}]  {h:02d}:{m:02d}:{s:02d}"
            f"{ev}{journal}  ·  [{P.purple}]{self._account_type}[/{P.purple}]"
        )

    # ── Event poll: Layers B + E + A ��────────────────────────────
    def _poll_events(self) -> None:
        if self._paused:
            return
        try:
            events = store.get_session_events(
                self._session_id, after_id=self._last_seen_id,
            )
        except Exception as exc:
            log("warning", "tui.poll_events.failed", error=str(exc))
            return

        P = ACTIVE
        feed = self.query_one(RichLog)
        for ev in events:
            self._last_seen_id = ev.get("id", self._last_seen_id)
            etype = ev.get("type", "event")
            color = _event_color(etype)
            ts = datetime.fromtimestamp(
                ev.get("ts", time.time()), tz=UTC,
            ).strftime("%H:%M:%S")
            prefix = self._tree.feed(etype)
            meta = _fmt_meta(ev)

            # Layer B + E: structural line with tree prefix
            feed.write(
                f"[{P.dim}]{ts}[/{P.dim}] "
                f"[{P.gold_ember}]{prefix}[/{P.gold_ember}]"
                f"[{color}]{etype:<18}[/{color}] "
                f"[{P.dim}]{meta}[/{P.dim}]"
            )
            # Layer A: journal content enrichment
            jline = _journal_line(ev, self._journal_mode)
            if jline:
                feed.write(
                    f"           [{P.gold_ember}]│[/{P.gold_ember}] "
                    f"[{P.dim}]\"{jline}\"[/{P.dim}]"
                )

            self._stats[etype] = self._stats.get(etype, 0) + 1
            self._event_count += 1

            # Moment detection
            if etype in _MOMENT_TYPES:
                m = ev.get("metadata") or {}
                detail = m.get("detail", m.get("description", etype))
                self._show_moment(etype, str(detail)[:60])

        if events:
            self._refresh_stats()

    def _refresh_stats(self) -> None:
        lines = []
        for etype, count in sorted(self._stats.items(), key=lambda x: -x[1])[:10]:
            color = _event_color(etype)
            lines.append(
                f"[{ACTIVE.dim}]{etype:<14}[/{ACTIVE.dim}] [{color}]{count}[/{color}]"
            )
        self.query_one("#stats-content", Static).update("\n".join(lines))

    def _show_moment(self, mtype: str, detail: str) -> None:
        P = ACTIVE
        alert = self.query_one("#moment-alert", Static)
        alert.update(f"  [{P.moment}]⚡ {mtype}[/{P.moment}]  [{P.dim}]{detail}[/{P.dim}]")
        alert.add_class("visible")
        self.set_timer(4.0, lambda: alert.remove_class("visible"))

    def action_stop_session(self) -> None:
        self.exit(None)

    def action_pause(self) -> None:
        self._paused = not self._paused

    def action_toggle_live(self) -> None:
        pass  # handled by caller in cli.py


def run(session_id: str, session: dict) -> None:
    """Launch the live session view for the given session."""
    StartApp(session_id, session).run()
