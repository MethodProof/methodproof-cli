"""Shared brand colors and base CSS for all MethodProof TUI screens."""

# Brand palette
GOLD   = "#c9a84c"
GREEN  = "#109446"
RED    = "#d93326"
PURPLE = "#803794"
NAVY   = "#192a56"

# Surface palette
BG        = "#12110f"
BAR       = "#1c1a18"
PANEL_BG  = "#0f0d0b"
BORDER    = "#2e2c29"
TEXT      = "#e8e4de"
DIM       = "#6b6560"

BASE_CSS = f"""
Screen {{
    background: {BG};
}}
Header {{
    background: {BAR};
    color: {GOLD};
    text-style: bold;
}}
Footer {{
    background: {BAR};
    color: {DIM};
}}
.panel {{
    border: solid {BORDER};
    background: {PANEL_BG};
    margin: 0 0 1 0;
    padding: 1 2;
}}
.section-title {{
    color: {GOLD};
    text-style: bold;
    margin: 0 0 1 0;
}}
.row-label {{
    width: 24;
    color: {TEXT};
}}
.row-desc {{
    color: {DIM};
}}
Rule {{
    color: {BORDER};
    margin: 1 0;
}}
"""
