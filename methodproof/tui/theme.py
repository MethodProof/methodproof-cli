"""Theme palette for the MethodProof TUI.

Two themes: **SHOMEN** (light) and **KINMYAKU** (dark). One is selected at
process startup via the ``MP_THEME`` environment variable (``shomen`` or
``kinmyaku``); default is ``kinmyaku`` because most dev terminals run dark.

Call sites should import ``ACTIVE`` and read attributes on it
(``ACTIVE.accent``, ``ACTIVE.ai_input``) — intent, not hex. The uppercase
re-exports (``GOLD``, ``DIM``, …) are kept for legacy Rich markup and
resolve to the selected theme at import time.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    # Surfaces
    bg: str
    surface: str
    sidebar_bg: str
    panel_bg: str
    border: str
    # Text
    text: str
    dim: str
    # Brand node colors (what) — five-color palette from brand/
    gold: str
    gold_aged: str
    gold_deep: str
    gold_ember: str
    red: str
    green: str
    purple: str
    purple_muted: str
    # Semantic roles (why) — every call site that means something should
    # use one of these, not the raw brand names above
    accent: str        # primary interactive accent (gold dark / vermillion light)
    ai_input: str      # prompts, agent dispatch, tool calls
    ai_output: str     # completions, agent replies, tool results
    human: str         # file edits, terminal, git — structural engineer work
    verify: str        # tests, browser research, web lookups
    moment: str        # flagged moments, pivots, breakthroughs
    # Cursor / selection highlight (list rows, focused controls)
    cursor_bg: str
    cursor_fg: str


# ── KINMYAKU — 金脈, "gold vein" (dark) ─────────────────────────────────
KINMYAKU = Theme(
    name="kinmyaku",
    bg="#12110f", surface="#1c1a18", sidebar_bg="#0a0908",
    panel_bg="#0f0d0b", border="#2e2c29",
    text="#e8e4de", dim="#8b8171",
    gold="#c9a84c", gold_aged="#9a7b3a",
    gold_deep="#6b5528", gold_ember="#3d3118",
    red="#e85445",
    green="#40d98c",
    purple="#9b59b6", purple_muted="#6b2f7d",
    accent="#c9a84c",
    ai_input="#9b59b6", ai_output="#c9a84c", human="#e8e4de",
    verify="#40d98c", moment="#e85445",
    cursor_bg="#c9a84c", cursor_fg="#12110f",
)

# ── SHOMEN — 正面, "the front" (light) ──────────────────────────────────
# Gold is darkened for contrast on white. Vermillion is the primary accent
# per METHODPROOF.md: "In light mode, vermillion and the brand node colors
# are the only saturated colors."
SHOMEN = Theme(
    name="shomen",
    bg="#ffffff", surface="#fafaf7", sidebar_bg="#f5f4ef",
    panel_bg="#f5f4ef", border="#d0ccc2",
    text="#0a0a0a", dim="#6b6862",
    gold="#8a6f2a", gold_aged="#6b5528",
    gold_deep="#3d3118", gold_ember="#e8dfc5",
    red="#d93326",
    green="#2d7a42",
    purple="#803794", purple_muted="#b89ac2",
    accent="#d93326",
    ai_input="#803794", ai_output="#8a6f2a", human="#0a0a0a",
    verify="#2d7a42", moment="#d93326",
    cursor_bg="#d93326", cursor_fg="#ffffff",
)


_THEMES = {"shomen": SHOMEN, "kinmyaku": KINMYAKU}
ACTIVE: Theme = _THEMES.get(os.environ.get("MP_THEME", "kinmyaku").strip().lower(), KINMYAKU)


# Legacy uppercase re-exports — bound to the selected theme. Kept so Rich
# markup in existing files (`[{GOLD}]…[/{GOLD}]`) keeps rendering. New code
# should use `ACTIVE.accent` / `ACTIVE.ai_output` instead of these.
GOLD = ACTIVE.gold
GREEN = ACTIVE.green
RED = ACTIVE.red
PURPLE = ACTIVE.purple
BG = ACTIVE.bg
BORDER = ACTIVE.border
TEXT = ACTIVE.text
DIM = ACTIVE.dim


BASE_CSS = f"""
Screen {{
    background: {ACTIVE.bg};
    color: {ACTIVE.text};
}}
Header {{
    background: {ACTIVE.surface};
    color: {ACTIVE.accent};
    text-style: bold;
}}
Footer {{
    background: {ACTIVE.surface};
    color: {ACTIVE.dim};
}}
.panel {{
    border: solid {ACTIVE.border};
    background: {ACTIVE.panel_bg};
    margin: 0 0 1 0;
    padding: 1 2;
}}
.section-title {{
    color: {ACTIVE.accent};
    text-style: bold;
    margin: 0 0 1 0;
}}
.row-label {{
    width: 24;
    color: {ACTIVE.text};
}}
.row-desc {{
    color: {ACTIVE.dim};
}}
Rule {{
    color: {ACTIVE.border};
    margin: 1 0;
}}
DataTable > .datatable--cursor {{
    background: {ACTIVE.cursor_bg};
    color: {ACTIVE.cursor_fg};
    text-style: bold;
}}
DataTable:focus > .datatable--cursor {{
    background: {ACTIVE.cursor_bg};
    color: {ACTIVE.cursor_fg};
    text-style: bold;
}}
DataTable > .datatable--hover {{
    background: {ACTIVE.surface};
}}
"""
