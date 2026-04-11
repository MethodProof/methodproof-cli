"""Rich display for mp review — pre-push session inspector."""
from __future__ import annotations

from datetime import datetime, UTC

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from methodproof.tui.theme import BORDER, DIM, GOLD, GREEN, PURPLE, RED, TEXT

_CONSOLE = Console()

# Edge type colors
_EDGE_COLOR = {
    "INFORMED": PURPLE,
    "RECEIVED": PURPLE,
    "LED_TO": DIM,
    "PASTED_FROM": DIM,
}

# Moment icons + colors
_MOMENT_STYLE = {
    "rapid_iteration": ("⚡", GOLD),
    "test_driven":     ("✓ ", GREEN),
    "git_discipline":  ("⎇ ", TEXT),
    "focused_session": ("⏸ ", PURPLE),
    "breakthrough":    ("★ ", GOLD),
    "approach_pivot":  ("↺ ", GOLD),
}


def run(session: dict) -> None:
    console = _CONSOLE

    # ── Session header ────────────────────────────────────────
    sid = session.get("id", "")[:8]
    created = session.get("created_at", 0)
    completed = session.get("completed_at", 0)
    dt_str = datetime.fromtimestamp(created, tz=UTC).strftime("%b %d %H:%M") if created else "?"
    dur_s = int((completed or 0) - created) if completed else 0
    dur_str = f"{dur_s // 3600}h {(dur_s % 3600) // 60:02d}m" if dur_s >= 3600 else f"{dur_s // 60}m"
    ev_count = session.get("total_events", 0)

    header = Text()
    header.append("session: ", style=DIM)
    header.append(sid, style=f"bold {GOLD}")
    header.append(f"  ·  {dt_str}  ·  {dur_str}  ·  ", style=DIM)
    header.append(f"{ev_count} events", style=f"bold {TEXT}")

    console.print()
    console.print(header)
    console.print()

    # ── Event breakdown ───────────────────────────────────────
    ev_counts: dict[str, int] = session.get("event_counts", {})
    total = sum(ev_counts.values()) or 1

    ev_table = Table(box=None, show_header=False, padding=(0, 1))
    ev_table.add_column("type", style=DIM, width=16)
    ev_table.add_column("count", style=f"bold {TEXT}", width=6)
    ev_table.add_column("bar", width=20)
    ev_table.add_column("pct", style=DIM, width=5)

    bar_colors = {
        "file_edit": GREEN, "terminal_cmd": TEXT, "browser_visit": DIM,
        "llm_prompt": PURPLE, "llm_completion": PURPLE,
        "test_run": GOLD, "git_commit": GOLD,
    }
    for etype, count in sorted(ev_counts.items(), key=lambda x: -x[1])[:8]:
        pct = count / total
        bar_len = max(1, int(pct * 18))
        color = bar_colors.get(etype, DIM)
        bar = Text("█" * bar_len + "░" * (18 - bar_len), style=color)
        ev_table.add_row(etype, str(count), bar, f"{int(pct * 100)}%")

    console.print(Panel(
        ev_table,
        title=f"[{GOLD}]  Events  [/{GOLD}]",
        border_style=BORDER,
        padding=(0, 1),
    ))

    # ── Causal edges + moments (side by side) ─────────────────
    edge_counts: dict[str, int] = session.get("edge_counts", {})
    edge_text = Text()
    for edge_type, count in sorted(edge_counts.items(), key=lambda x: -x[1]):
        color = _EDGE_COLOR.get(edge_type, DIM)
        edge_text.append(f"{edge_type:<12}", style=f"bold {color}")
        edge_text.append(f"  {count}\n", style=TEXT)
    if not edge_text._spans:
        edge_text.append("no edges recorded", style=DIM)

    moments: list[dict] = session.get("moments", [])
    mom_text = Text()
    for m in moments[:6]:
        mtype = m.get("type", "")
        icon, color = _MOMENT_STYLE.get(mtype, ("· ", DIM))
        when = datetime.fromtimestamp(m.get("ts", 0), tz=UTC).strftime("%H:%M") if m.get("ts") else ""
        mom_text.append(icon, style=color)
        mom_text.append(f"{mtype:<20}", style=color)
        mom_text.append(f"  {when}\n", style=DIM)
    if not mom_text._spans:
        mom_text.append("no moments detected", style=DIM)

    console.print(Columns([
        Panel(edge_text, title=f"[{GOLD}]  Causal Edges  [/{GOLD}]", border_style=BORDER, padding=(0, 1)),
        Panel(mom_text, title=f"[{GOLD}]  Moments  [/{GOLD}]", border_style=BORDER, padding=(0, 1)),
    ]))

    # ── Push summary ──────────────────────────────────────────
    redact = session.get("publish_redact", {})
    n_redacted = sum(1 for v in redact.values() if v)
    size_kb = ev_count * 0.05  # rough estimate
    e2e = session.get("e2e", False)
    integrity = session.get("integrity_score", None)

    summary = Text()
    summary.append("Push size: ", style=DIM)
    summary.append(f"~{size_kb:.0f} KB", style=TEXT)
    summary.append("  ·  redacted: ", style=DIM)
    summary.append(f"{n_redacted} fields", style=GREEN if n_redacted == 0 else GOLD)
    summary.append("  ·  E2E: ", style=DIM)
    summary.append("on" if e2e else "off", style=GOLD if e2e else DIM)
    if integrity is not None:
        summary.append("  ·  integrity: ", style=DIM)
        summary.append(f"{integrity}/100 ✓", style=GREEN)

    console.print(summary)
    console.print()
    console.print(
        f"  [{DIM}]p push   pub publish   e edit tags   v view graph   esc back[/{DIM}]",
        highlight=False,
    )
