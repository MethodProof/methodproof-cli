"""Rich display for mp status."""
from __future__ import annotations

import time
from datetime import datetime, UTC

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from methodproof import config as cfg_mod, store
from methodproof.tui.theme import BORDER, DIM, GOLD, GREEN, PURPLE, RED, TEXT

_CONSOLE = Console()


def _tier_color(tier: str) -> str:
    return {"free": DIM, "basic": TEXT, "pro": GOLD, "team": PURPLE}.get(tier.lower(), TEXT)


def _token_expiry(cfg: dict) -> str:
    last_auth = cfg.get("last_auth_at", 0)
    if not last_auth:
        return "unknown"
    age_h = (time.time() - last_auth) / 3600
    remaining_h = max(0, 24 - age_h)
    if remaining_h < 1:
        return f"[{RED}]expires soon[/{RED}]"
    return f"[{DIM}]expires in {int(remaining_h)}h[/{DIM}]"


def run(cfg: dict) -> None:
    console = _CONSOLE

    # ── Account ──────────────────────────────────────────────
    email = cfg.get("email") or "not logged in"
    tier = "unknown"
    if cfg.get("token"):
        try:
            import base64, json as _json
            payload = cfg["token"].split(".")[1]
            payload += "=" * (-len(payload) % 4)
            data = _json.loads(base64.b64decode(payload))
            tier = data.get("tier", "unknown")
        except Exception:
            pass

    acct_lines = Text()
    acct_lines.append("✓  ", style=f"bold {GREEN}")
    acct_lines.append(email, style=f"bold {TEXT}")
    acct_lines.append("  ·  ", style=DIM)
    acct_lines.append(tier, style=_tier_color(tier))
    acct_lines.append("\n")
    acct_lines.append(_token_expiry(cfg), style=DIM)

    console.print(Panel(
        acct_lines,
        title=f"[{GOLD}]  Account  [/{GOLD}]",
        border_style=BORDER,
        padding=(0, 1),
    ))

    # ── Session ───────────────────────────────────────────────
    active = cfg.get("active_session")
    if active:
        try:
            sess = store.get_session(active)
            created = datetime.fromtimestamp(sess["created_at"], tz=UTC).strftime("%H:%M")
            elapsed = int(time.time() - sess["created_at"])
            h, m = elapsed // 3600, (elapsed % 3600) // 60
            dur = f"{h}h {m:02d}m" if h else f"{m}m"
            ev = sess.get("total_events", 0)
            sess_text = Text()
            sess_text.append("● ", style=f"bold {GREEN}")
            sess_text.append(f"recording since {created}  ·  {dur}  ·  {ev} events", style=TEXT)
            sess_text.append(f"\n  {active[:8]}", style=DIM)
            sess_text.append(f"  ·  watching: {sess.get('watch_dir', '?')}", style=DIM)
        except Exception:
            sess_text = Text(f"● active: {active[:8]}", style=GREEN)
    else:
        sess_text = Text()
        sess_text.append("○  no active session   ", style=DIM)
        sess_text.append("mp start", style=f"bold {GOLD}")
        sess_text.append("  to begin", style=DIM)
        try:
            sessions = store.list_sessions()
            if sessions:
                last = sessions[0]
                dt = datetime.fromtimestamp(last["created_at"], tz=UTC).strftime("%b %d %H:%M")
                ev = last.get("total_events", 0)
                sess_text.append(f"\nlast: {dt}  ·  {ev} events", style=DIM)
        except Exception:
            pass

    console.print(Panel(
        sess_text,
        title=f"[{GOLD}]  Session  [/{GOLD}]",
        border_style=BORDER,
        padding=(0, 1),
    ))

    # ── Config ────────────────────────────────────────────────
    capture = cfg.get("capture", {})
    redact = cfg.get("publish_redact", {})
    n_cap = sum(1 for k in cfg_mod.STANDARD_CATEGORIES if capture.get(k, True))
    is_full = n_cap == len(cfg_mod.STANDARD_CATEGORIES)

    cfg_text = Text()
    cfg_text.append("capture:     ", style=DIM)
    if is_full:
        cfg_text.append("Full Spectrum  ", style=GOLD)
        cfg_text.append("(10/11 enabled)", style=DIM)
    else:
        cfg_text.append(f"{n_cap}/11 categories enabled", style=TEXT)
    cfg_text.append("\n")

    cfg_text.append("journal:     ", style=DIM)
    jm = cfg.get("journal_mode", False)
    cfg_text.append("on" if jm else "off", style=GOLD if jm else DIM)
    cfg_text.append("    e2e:  ", style=DIM)
    e2e = cfg.get("e2e_mode", False)
    cfg_text.append("on" if e2e else "off", style=GOLD if e2e else DIM)
    cfg_text.append("\n")

    cfg_text.append("auto-update: ", style=DIM)
    au = cfg.get("auto_update", False)
    cfg_text.append("on" if au else "off", style=GREEN if au else DIM)
    cfg_text.append("    live: ", style=DIM)
    cfg_text.append("private", style=TEXT)
    cfg_text.append("\n")

    try:
        sessions = store.list_sessions()
        n_total = len(sessions)
        n_unsynced = sum(1 for s in sessions if not s.get("synced") and s.get("completed_at"))
        cfg_text.append("sessions:    ", style=DIM)
        cfg_text.append(f"{n_total} local", style=TEXT)
        if n_unsynced:
            cfg_text.append(f"   {n_unsynced} unsynced", style=GOLD)
    except Exception:
        pass

    console.print(Panel(
        cfg_text,
        title=f"[{GOLD}]  Config  [/{GOLD}]",
        border_style=BORDER,
        padding=(0, 1),
    ))

    console.print(
        f"  [{DIM}]q quit   l login   c consent   u update[/{DIM}]",
        highlight=False,
    )
