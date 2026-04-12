"""Textual TUI for mp start — live session event feed.

Four display layers:
  B — Rich structural formatting for all 42 event types
  E — Causal chain tree indentation (prompt→tool→result)
  A — Journal mode content enrichment (second dim line)
  D — Enriched session bar (badges, event count)

Ten controls:
  j — journal toggle       f — event filter cycle
  s — scroll lock           / — feed search
  tab — sidebar cycle       t — tree collapse
  d — timestamp format      c — copy last event
  enter — event detail      m — quiet mode
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, UTC

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, RichLog, Static
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
#search-bar {{
    display: none;
    height: 1;
    background: {ACTIVE.surface};
    padding: 0 1;
}}
#search-bar.visible {{
    display: block;
}}
#search-input {{
    width: 1fr;
}}
#detail-view {{
    width: 80%;
    height: 80%;
    background: {ACTIVE.panel_bg};
    border: solid {ACTIVE.gold_deep};
    padding: 1 2;
}}
"""

_POLL_INTERVAL = 0.5

# ── Layer B: Semantic color roles ────────────────────────────────────
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

_DIM_TYPES = {
    "music_playing", "environment_profile", "mcp_elicitation",
    "mcp_elicitation_result", "context_compact_start", "context_compact_end",
}

_FILTER_PRESETS = ["all", "ai_input", "ai_output", "human", "verify"]

_TS_MODES = ["clock", "relative", "elapsed"]

_SIDEBAR_VIEWS = ["stats", "files", "tools"]


def _event_color(etype: str) -> str:
    role = _EVENT_ROLE.get(etype, "dim")
    return getattr(ACTIVE, role, ACTIVE.dim)


# ── Layer E: Causal chain tree tracker ───────────────────────────────
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
        self._collapsed = False
        self._collapse_count = 0

    def set_collapsed(self, val: bool) -> None:
        self._collapsed = val
        self._collapse_count = 0

    def feed(self, etype: str) -> tuple[str, bool]:
        """Return (prefix, visible). When collapsed, inners are hidden."""
        if etype in self._OPENERS:
            self._in_chain = True
            self._collapse_count = 0
            return "  ", True
        if self._in_chain:
            if etype in self._CLOSERS:
                self._in_chain = False
                cnt = self._collapse_count
                self._collapse_count = 0
                if self._collapsed and cnt > 0:
                    return f"└ +{cnt} ", True
                return "└ ", True
            if etype in self._INNERS:
                if self._collapsed:
                    self._collapse_count += 1
                    return "├ ", False
                return "├ ", True
            self._in_chain = False
            return "  ", True
        # Not in chain — tool_call starts one implicitly (orphan after closer)
        if etype in self._INNERS:
            self._in_chain = True
            self._collapse_count = 0
            return "├ ", True
        return "  ", True


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

    # Hook lifecycle — user prompt (structural analysis summary)
    if etype == "user_prompt":
        summary = meta.get("prompt_summary", "")
        if summary:
            return summary[:80]
        length = meta.get("prompt_length", "")
        return f"{length} chars" if length else ""

    # Hook lifecycle — tool call / result
    if etype == "tool_call":
        name = meta.get("tool_name") or meta.get("tool", "")
        preview = (meta.get("tool_input_preview") or "")[:60]
        return f"{name}  {preview}".strip()
    if etype == "tool_result":
        name = meta.get("tool_name") or meta.get("tool", "")
        ok = "✓" if meta.get("success", True) else "✗"
        return f"{name}  {ok}"
    if etype == "tool_failure":
        name = meta.get("tool_name") or meta.get("tool", "")
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


# ── Layer A: Journal content enrichment ──────────────────────────────
_MULTILINE_TYPES = {"user_prompt": "prompt_text", "agent_complete": "last_message_preview"}


def _journal_lines(ev: dict, journal_mode: bool) -> list[str]:
    """Return content lines when journal mode is ON. Multi-line for prompts/completions."""
    if not journal_mode:
        return []
    meta = ev.get("metadata") or {}
    if not isinstance(meta, dict):
        return []
    etype = ev.get("type", "")

    # Multi-line: user_prompt (full), agent_complete (~paragraph)
    field = _MULTILINE_TYPES.get(etype)
    if field and field in meta:
        raw = str(meta[field]).strip()
        if not raw:
            return []
        if etype == "user_prompt":
            # Full prompt, wrap at ~100 chars per line
            return [raw[i:i + 100] for i in range(0, len(raw), 100)]
        # agent_complete: ~500 chars, preserve natural line breaks
        text = raw[:500]
        return [line for line in text.split("\n") if line.strip()][:8]

    # Single-line for everything else
    for jetype, jfield in config.JOURNAL_CONTENT_FIELDS:
        if jetype == etype and jfield in meta:
            content = str(meta[jfield]).replace("\n", " ")[:120]
            return [content] if content else []
    return []


# ── Detail modal ─────────────────────────────────────────────────────
class _DetailScreen(Screen[None]):
    """Full metadata view for a single event."""

    BINDINGS = [Binding("escape", "dismiss", "close")]

    def __init__(self, ev: dict) -> None:
        super().__init__()
        self._ev = ev

    def compose(self) -> ComposeResult:
        yield Static(
            f"[{ACTIVE.gold}]Event Detail[/{ACTIVE.gold}]  "
            f"[{ACTIVE.dim}]ESC to close[/{ACTIVE.dim}]",
        )
        yield RichLog(id="detail-view", highlight=True, markup=True, wrap=True)

    def on_mount(self) -> None:
        view = self.query_one("#detail-view", RichLog)
        P = ACTIVE
        ev = self._ev
        view.write(f"[{P.gold}]type:[/{P.gold}] {ev.get('type', '?')}")
        view.write(f"[{P.gold}]id:[/{P.gold}]   {ev.get('id', '?')}")
        view.write(f"[{P.gold}]ts:[/{P.gold}]   {ev.get('ts', '?')}")
        view.write("")
        meta = ev.get("metadata") or {}
        if isinstance(meta, dict):
            for k, v in meta.items():
                val = str(v)[:200]
                view.write(f"[{P.dim}]{k}:[/{P.dim}] {val}")

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class _ConfirmEndScreen(Screen[bool]):
    """Confirm session end."""

    BINDINGS = [
        Binding("y", "confirm", "yes"),
        Binding("n", "cancel", "no"),
        Binding("escape", "cancel", "cancel"),
    ]

    def compose(self) -> ComposeResult:
        P = ACTIVE
        yield Static(
            f"\n  [{P.red}]End this session?[/{P.red}]\n\n"
            f"  [{P.dim}]This will stop all capture agents and finalize the session.[/{P.dim}]\n\n"
            f"  [{P.gold}]y[/{P.gold}] [{P.dim}]confirm[/{P.dim}]    "
            f"[{P.gold}]n[/{P.gold}] [{P.dim}]cancel[/{P.dim}]",
        )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


# ── App ──────────────────────────────────────────────────────────────
class StartApp(App[str | None]):
    """Live session view — tails the active session's events."""

    TITLE = "methodproof — mp start"
    CSS = _CSS
    BINDINGS = [
        Binding("q", "exit_tui", "exit"),
        Binding("x", "end_session", "end session"),
        Binding("p", "pause", "pause"),
        Binding("j", "toggle_journal", "journal"),
        Binding("f", "cycle_filter", "filter"),
        Binding("s", "toggle_scroll", "scroll"),
        Binding("slash", "open_search", "search"),
        Binding("tab", "cycle_sidebar", "sidebar"),
        Binding("t", "toggle_tree", "tree"),
        Binding("d", "cycle_timestamp", "time"),
        Binding("c", "copy_last", "copy"),
        Binding("enter", "show_detail", "detail"),
        Binding("m", "toggle_quiet", "quiet"),
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
        # Controls state
        self._filter_idx = 0  # index into _FILTER_PRESETS
        self._scroll_locked = False
        self._search_query = ""
        self._sidebar_idx = 0  # index into _SIDEBAR_VIEWS
        self._ts_mode_idx = 0  # index into _TS_MODES
        self._quiet_mode = False
        self._last_event: dict | None = None
        self._last_event_ts: float = 0.0
        self._recent_files: list[str] = []
        self._recent_tools: list[str] = []
        # Source tracking: which AI tool session is active
        self._active_source: str = ""  # e.g. "claude", "codex", "gemini"
        self._source_session_id: str = ""  # short id of the AI session
        self._source_count: int = 0  # how many AI sessions so far

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="session-bar", markup=True)
        with Horizontal():
            with Vertical(id="feed-col"):
                yield RichLog(id="feed", highlight=True, markup=True, wrap=False)
                yield Static("", id="moment-alert", markup=True)
                yield Input(placeholder="search...", id="search-input")
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
        # Hide search input initially
        self.query_one("#search-input", Input).display = False
        self._tick_timer()
        self.set_interval(_POLL_INTERVAL, self._poll_events)
        self.set_interval(1.0, self._tick_timer)

    # ── Timestamp formatting ─────────────────────────────────────
    def _format_ts(self, ev_ts: float) -> str:
        mode = _TS_MODES[self._ts_mode_idx]
        if mode == "clock":
            return datetime.fromtimestamp(ev_ts, tz=UTC).strftime("%H:%M:%S")
        if mode == "relative":
            delta = ev_ts - self._last_event_ts if self._last_event_ts else 0
            return f"+{delta:.1f}s" if delta >= 0 else "+0.0s"
        # elapsed
        elapsed = ev_ts - self._start_time
        return f"{elapsed:.1f}s"

    # ── Filter check ─────────────────────────────────────────────
    def _passes_filter(self, etype: str) -> bool:
        preset = _FILTER_PRESETS[self._filter_idx]
        if preset == "all":
            return True
        role = _EVENT_ROLE.get(etype, "dim")
        return role == preset

    # ── Layer D: Session bar ─────────────────────────────────────
    def _tick_timer(self) -> None:
        if self._paused:
            return
        P = ACTIVE
        elapsed = int(time.time() - self._start_time)
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        sid = self._session_id[:8]
        watch_dir = self._session.get("watch_dir", "?")

        # Mode badges
        badges = []
        if self._journal_mode:
            badges.append(f"[{P.gold}]J[/{P.gold}]")
        if self._scroll_locked:
            badges.append(f"[{P.red}]⏸[/{P.red}]")
        if self._quiet_mode:
            badges.append(f"[{P.dim}]Q[/{P.dim}]")
        if self._tree._collapsed:
            badges.append(f"[{P.dim}]T[/{P.dim}]")
        filt = _FILTER_PRESETS[self._filter_idx]
        if filt != "all":
            badges.append(f"[{P.purple}]{filt}[/{P.purple}]")
        badge_str = "  ".join(badges)
        if badge_str:
            badge_str = f"  {badge_str}"

        ev = f"  {self._event_count} ev" if self._event_count else ""
        src = ""
        if self._active_source:
            src = f"  ·  [{P.purple_muted}]{self._active_source} #{self._source_count}[/{P.purple_muted}]"
        self.query_one("#session-bar", Static).update(
            f"  session: [{P.gold}]{sid}[/{P.gold}]  ·  {watch_dir}"
            f"  ·  [{P.green}]●[/{P.green}]  {h:02d}:{m:02d}:{s:02d}"
            f"{ev}{src}{badge_str}  ·  [{P.purple}]{self._account_type}[/{P.purple}]"
        )

    # ── Event poll: Layers B + E + A ─────────────────────────────
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
        feed = self.query_one("#feed", RichLog)
        for ev in events:
            self._last_seen_id = ev.get("id", self._last_seen_id)
            etype = ev.get("type", "event")
            self._last_event = ev
            ev_ts = ev.get("ts", time.time())

            # Source tracking: detect AI session boundaries
            if etype.endswith("_session_start"):
                self._active_source = etype.replace("_session_start", "")
                ev_meta_src = ev.get("metadata") or {}
                sid_field = ev_meta_src.get("session_id") or ev_meta_src.get("claude_session_id", "")
                self._source_session_id = str(sid_field)[:8]
                self._source_count += 1
            elif etype.endswith("_session_end"):
                self._active_source = ""
                self._source_session_id = ""

            # Quiet mode: skip dim events
            if self._quiet_mode and etype in _DIM_TYPES:
                self._stats[etype] = self._stats.get(etype, 0) + 1
                self._event_count += 1
                continue

            # Filter check
            if not self._passes_filter(etype):
                self._stats[etype] = self._stats.get(etype, 0) + 1
                self._event_count += 1
                self._last_event_ts = ev_ts
                continue

            color = _event_color(etype)
            ts = self._format_ts(ev_ts)
            self._last_event_ts = ev_ts
            prefix, visible = self._tree.feed(etype)
            meta = _fmt_meta(ev)

            # Track recent files and tools
            ev_meta = ev.get("metadata") or {}
            if isinstance(ev_meta, dict):
                path = ev_meta.get("path") or ev_meta.get("file_path")
                if path and etype in ("file_edit", "file_create", "file_delete"):
                    if path not in self._recent_files:
                        self._recent_files.append(path)
                    if len(self._recent_files) > 10:
                        self._recent_files.pop(0)
                tool = ev_meta.get("tool_name") or ev_meta.get("tool")
                if tool and etype in ("tool_call", "tool_result"):
                    if tool not in self._recent_tools:
                        self._recent_tools.append(tool)
                    if len(self._recent_tools) > 10:
                        self._recent_tools.pop(0)

            if not visible:
                # Collapsed inner — count but don't render
                self._stats[etype] = self._stats.get(etype, 0) + 1
                self._event_count += 1
                continue

            # Source tag
            src_tag = ""
            if self._active_source:
                src_tag = f"[{P.purple_muted}]{self._active_source}[/{P.purple_muted}] "

            # Search highlight
            line_plain = f"{etype} {meta}"
            if self._search_query and self._search_query.lower() not in line_plain.lower():
                feed.write(f"[{P.dim}]{ts}  {prefix}{etype:<18} {meta}[/{P.dim}]")
            else:
                feed.write(
                    f"[{P.dim}]{ts}[/{P.dim}] "
                    f"{src_tag}"
                    f"[{P.gold_aged}]{prefix}[/{P.gold_aged}]"
                    f"[{color}]{etype:<18}[/{color}] "
                    f"[{P.dim}]{meta}[/{P.dim}]"
                )

            # Layer A: journal content enrichment
            for jline in _journal_lines(ev, self._journal_mode):
                feed.write(
                    f"           [{P.gold_aged}]│[/{P.gold_aged}] "
                    f"[{P.dim}]{jline}[/{P.dim}]"
                )

            self._stats[etype] = self._stats.get(etype, 0) + 1
            self._event_count += 1

            # Moment detection
            if etype in _MOMENT_TYPES:
                m_meta = ev.get("metadata") or {}
                detail = m_meta.get("detail", m_meta.get("description", etype))
                self._show_moment(etype, str(detail)[:60])

        if events:
            self._refresh_sidebar()

    def _refresh_sidebar(self) -> None:
        view = _SIDEBAR_VIEWS[self._sidebar_idx]
        title = self.query_one(".sidebar-title", Static)
        content = self.query_one("#stats-content", Static)
        P = ACTIVE

        if view == "stats":
            title.update("Stats")
            lines = []
            for etype, count in sorted(self._stats.items(), key=lambda x: -x[1])[:10]:
                color = _event_color(etype)
                lines.append(f"[{P.dim}]{etype:<14}[/{P.dim}] [{color}]{count}[/{color}]")
            content.update("\n".join(lines))

        elif view == "files":
            title.update("Files")
            lines = []
            for path in reversed(self._recent_files[-10:]):
                short = path.rsplit("/", 1)[-1] if "/" in path else path
                lines.append(f"[{P.dim}]{short[:20]}[/{P.dim}]")
            content.update("\n".join(lines) if lines else f"[{P.dim}]no files yet[/{P.dim}]")

        elif view == "tools":
            title.update("Tools")
            lines = []
            for tool in reversed(self._recent_tools[-10:]):
                lines.append(f"[{P.dim}]{tool[:20]}[/{P.dim}]")
            content.update("\n".join(lines) if lines else f"[{P.dim}]no tools yet[/{P.dim}]")

    def _show_moment(self, mtype: str, detail: str) -> None:
        P = ACTIVE
        alert = self.query_one("#moment-alert", Static)
        alert.update(f"  [{P.moment}]⚡ {mtype}[/{P.moment}]  [{P.dim}]{detail}[/{P.dim}]")
        alert.add_class("visible")
        self.set_timer(4.0, lambda: alert.remove_class("visible"))

    # ── Actions ──────────────────────────────────────────────────
    def action_exit_tui(self) -> None:
        """Detach TUI — daemon keeps recording."""
        self.exit(None)

    def action_end_session(self) -> None:
        """End the session (with confirmation)."""
        self.push_screen(_ConfirmEndScreen(), self._on_confirm_end)

    def _on_confirm_end(self, confirmed: bool) -> None:
        if not confirmed:
            return
        self.exit("end_session")

    def action_pause(self) -> None:
        self._paused = not self._paused

    def action_toggle_journal(self) -> None:
        self._journal_mode = not self._journal_mode
        self._tick_timer()

    def action_cycle_filter(self) -> None:
        self._filter_idx = (self._filter_idx + 1) % len(_FILTER_PRESETS)
        P = ACTIVE
        filt = _FILTER_PRESETS[self._filter_idx]
        feed = self.query_one("#feed", RichLog)
        feed.write(f"[{P.dim}]── filter: {filt} ──[/{P.dim}]")
        self._tick_timer()

    def action_toggle_scroll(self) -> None:
        self._scroll_locked = not self._scroll_locked
        feed = self.query_one("#feed", RichLog)
        feed.auto_scroll = not self._scroll_locked
        self._tick_timer()

    def action_open_search(self) -> None:
        search = self.query_one("#search-input", Input)
        if search.display:
            search.display = False
            self._search_query = ""
            self.set_focus(self.query_one("#feed", RichLog))
        else:
            search.display = True
            search.value = self._search_query
            self.set_focus(search)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self._search_query = event.value.strip()
            event.input.display = False
            self.set_focus(self.query_one("#feed", RichLog))

    def action_cycle_sidebar(self) -> None:
        self._sidebar_idx = (self._sidebar_idx + 1) % len(_SIDEBAR_VIEWS)
        self._refresh_sidebar()

    def action_toggle_tree(self) -> None:
        self._tree.set_collapsed(not self._tree._collapsed)
        P = ACTIVE
        state = "collapsed" if self._tree._collapsed else "expanded"
        feed = self.query_one("#feed", RichLog)
        feed.write(f"[{P.dim}]── tree: {state} ──[/{P.dim}]")
        self._tick_timer()

    def action_cycle_timestamp(self) -> None:
        self._ts_mode_idx = (self._ts_mode_idx + 1) % len(_TS_MODES)
        P = ACTIVE
        mode = _TS_MODES[self._ts_mode_idx]
        feed = self.query_one("#feed", RichLog)
        feed.write(f"[{P.dim}]── time: {mode} ──[/{P.dim}]")

    def action_copy_last(self) -> None:
        if not self._last_event:
            return
        text = json.dumps(self._last_event, indent=2, default=str)
        try:
            if sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=text.encode(), check=True)
            else:
                subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return
        P = ACTIVE
        feed = self.query_one("#feed", RichLog)
        feed.write(f"[{P.dim}]── copied to clipboard ──[/{P.dim}]")

    def action_show_detail(self) -> None:
        if self._last_event:
            self.push_screen(_DetailScreen(self._last_event))

    def action_toggle_quiet(self) -> None:
        self._quiet_mode = not self._quiet_mode
        P = ACTIVE
        state = "on" if self._quiet_mode else "off"
        feed = self.query_one("#feed", RichLog)
        feed.write(f"[{P.dim}]── quiet: {state} ──[/{P.dim}]")
        self._tick_timer()


def run(session_id: str, session: dict) -> str | None:
    """Launch the live session view. Returns 'end_session' if user chose to end."""
    app = StartApp(session_id, session)
    return app.run()
