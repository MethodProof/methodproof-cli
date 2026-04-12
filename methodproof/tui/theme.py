"""Theme palette for MethodProof TUI — KINMYAKU (dark) mode.

Colors derived from THEMES/METHODPROOF.md spec. Semantic roles encode
meaning (ai_input, ai_output, human, verify, moment) so TUI code reads
intent, not hex values.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    # Brand accents
    gold: str
    gold_aged: str
    gold_deep: str
    gold_ember: str
    green: str
    green_muted: str
    red: str
    purple: str
    purple_muted: str
    # Surfaces
    bg: str
    surface: str
    panel_bg: str
    border: str
    sidebar_bg: str
    deep_bg: str
    purple_bg: str
    # Text
    text: str
    dim: str
    # Semantic roles (aliases for intent-driven lookup)
    ai_input: str
    ai_output: str
    human: str
    verify: str
    moment: str


KINMYAKU = Palette(
    gold="#c9a84c", gold_aged="#9a7b3a", gold_deep="#6b5528", gold_ember="#3d3118",
    green="#40d98c", green_muted="#2a6b45",
    red="#e85445",
    purple="#9b59b6", purple_muted="#6b2f7d",
    bg="#12110f", surface="#1c1a18", panel_bg="#0f0d0b", border="#2e2c29",
    sidebar_bg="#0a0908", deep_bg="#050403", purple_bg="#200a26",
    text="#e8e4de", dim="#8b8171",
    ai_input="#9b59b6", ai_output="#c9a84c", human="#e8e4de",
    verify="#40d98c", moment="#e85445",
)

ACTIVE = KINMYAKU

# Backward-compatible re-exports — all existing imports keep working.
GOLD = ACTIVE.gold
GREEN = ACTIVE.green
RED = ACTIVE.red
PURPLE = ACTIVE.purple
NAVY = "#192a56"  # brand-only, not in palette
BG = ACTIVE.bg
BAR = ACTIVE.surface
PANEL_BG = ACTIVE.panel_bg
BORDER = ACTIVE.border
TEXT = ACTIVE.text
DIM = ACTIVE.dim
SIDEBAR_BG = ACTIVE.sidebar_bg
DEEP_BG = ACTIVE.deep_bg
PURPLE_BG = ACTIVE.purple_bg

BASE_CSS = f"""
Screen {{
    background: {ACTIVE.bg};
}}
Header {{
    background: {ACTIVE.surface};
    color: {ACTIVE.gold};
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
    color: {ACTIVE.gold};
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
"""
