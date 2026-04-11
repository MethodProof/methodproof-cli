"""Textual TUI for mp consent — capture categories + publish redaction."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Footer, Header, Label, Rule, Static, Switch

from methodproof import config as cfg_mod
from methodproof.tui.theme import BASE_CSS, BORDER, DIM, GOLD, GREEN, PURPLE, RED, TEXT

# Redaction settings shown in Section B
_REDACTABLE = [
    ("command_output", "Terminal output (first 500 chars)"),
    ("ai_prompts",     "AI prompt text"),
    ("ai_responses",   "AI response text"),
    ("code_capture",   "File diffs and git patches"),
]

# Which sample field each publish_redact key covers (for live preview)
_REDACT_FIELD: dict[str, str] = {
    "command_output": "output_snippet",
    "ai_prompts":     "prompt_text",
    "ai_responses":   "response_text",
    "code_capture":   "diff",
}

_SAMPLE_EVENT = {
    "type":           "terminal_cmd",
    "command":        "pytest tests/ -v",
    "exit_code":      0,
    "duration_ms":    4201,
    "output_snippet": "12 passed in 4.2s",
}

_CSS = BASE_CSS + f"""
#main {{
    padding: 1 3;
}}
#heading {{
    color: {TEXT};
    text-style: bold;
    margin: 0 0 0 0;
}}
#subhead {{
    color: {DIM};
    margin: 0 0 1 0;
}}
.toggle-row {{
    height: 2;
    align: left middle;
    margin: 0;
}}
.toggle-row Switch {{
    margin: 0 1 0 0;
    width: 4;
}}
.pro-row .row-label {{
    color: {PURPLE};
}}
.pro-badge {{
    background: #200a26;
    color: {PURPLE};
    padding: 0 1;
    margin: 0 0 0 2;
    width: 5;
}}
#fs-status {{
    color: {DIM};
    margin: 1 0 0 0;
    height: 1;
}}
#fs-status.full {{
    color: {GOLD};
}}
#preview-box {{
    background: #050403;
    border: solid {BORDER};
    margin: 1 0 0 0;
    padding: 1 2;
    height: auto;
}}
.preview-header {{
    color: {DIM};
    margin: 0 0 1 0;
}}
"""


def _build_preview(redact: dict) -> str:
    """Rich markup string showing the sample event with redacted fields highlighted."""
    lines = [f"[{DIM}]{{[/{DIM}]"]
    sample = {**_SAMPLE_EVENT}

    # Mark fields that would be stripped on publish
    redacted_fields = {
        field for key, field in _REDACT_FIELD.items() if redact.get(key, True)
    }

    for k, v in sample.items():
        if k in redacted_fields:
            lines.append(f'  [{RED}]"{k}"[/{RED}]: [{RED} dim]\\[redacted][/{RED} dim],')
        elif isinstance(v, str):
            lines.append(f'  [{GOLD}]"{k}"[/{GOLD}]: [{GREEN}]"{v}"[/{GREEN}],')
        else:
            lines.append(f'  [{GOLD}]"{k}"[/{GOLD}]: [{TEXT}]{v}[/{TEXT}],')

    lines.append(f"[{DIM}]}}[/{DIM}]")
    return "\n".join(lines)


class ConsentApp(App[dict | None]):
    """Consent + Redaction TUI. Exits with updated cfg dict on save, None on cancel."""

    TITLE = "methodproof — mp consent"
    CSS = _CSS
    BINDINGS = [
        Binding("s", "save", "save"),
        Binding("escape", "cancel", "cancel"),
        Binding("r", "reset_defaults", "reset"),
    ]

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self._cfg = cfg
        self._capture = dict(cfg.get("capture", cfg_mod._DEFAULTS["capture"]))
        self._redact = dict(cfg.get("publish_redact", cfg_mod._DEFAULTS["publish_redact"]))

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with ScrollableContainer(id="main"):
            yield Static("Configure Data Capture", id="heading")
            yield Static(
                "Control exactly what leaves your machine.  Nothing uploads until  mp push.",
                id="subhead",
            )

            # ── Section A: Capture categories ────────────────────
            with Vertical(classes="panel", id="capture-panel"):
                yield Static("  Structural Capture  ", classes="section-title")

                for cat in cfg_mod.STANDARD_CATEGORIES:
                    label = cat.replace("_", " ")
                    desc = cfg_mod.CAPTURE_DESCRIPTIONS[cat]
                    with Horizontal(classes="toggle-row"):
                        yield Switch(
                            value=self._capture.get(cat, True),
                            id=f"cap-{cat}",
                            animate=False,
                        )
                        yield Label(label, classes="row-label")
                        yield Label(desc, classes="row-desc")

                yield Static("", id="fs-status")
                yield Rule()

                # Code capture — Pro, off by default
                with Horizontal(classes="toggle-row pro-row"):
                    yield Switch(
                        value=self._capture.get("code_capture", False),
                        id="cap-code_capture",
                        animate=False,
                    )
                    yield Label("code capture", classes="row-label")
                    yield Label(cfg_mod.CAPTURE_DESCRIPTIONS["code_capture"], classes="row-desc")
                    yield Static("Pro", classes="pro-badge")

            # ── Section B: Publish redaction ─────────────────────
            with Vertical(classes="panel", id="redact-panel"):
                yield Static("  Publish Redaction  ", classes="section-title")
                yield Static(
                    "Stripped when you publish a session publicly (mp publish).",
                    classes="row-desc",
                )
                yield Static("", classes="row-desc")  # spacer

                for key, desc in _REDACTABLE:
                    with Horizontal(classes="toggle-row"):
                        yield Switch(
                            value=self._redact.get(key, True),
                            id=f"red-{key}",
                            animate=False,
                        )
                        yield Label(desc, classes="row-label")

                # Live redaction preview
                with Vertical(id="preview-box"):
                    yield Static(
                        "What leaves your machine on  mp push  with current settings:",
                        classes="preview-header",
                    )
                    yield Static(
                        _build_preview(self._redact),
                        id="preview-content",
                        markup=True,
                    )

        yield Footer()

    def on_mount(self) -> None:
        self._refresh_fs_status()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        sw_id = event.switch.id or ""
        if sw_id.startswith("cap-"):
            self._capture[sw_id[4:]] = event.value
            self._refresh_fs_status()
        elif sw_id.startswith("red-"):
            self._redact[sw_id[4:]] = event.value
            self._refresh_preview()

    def _refresh_fs_status(self) -> None:
        enabled = sum(1 for k in cfg_mod.STANDARD_CATEGORIES if self._capture.get(k, True))
        is_full = enabled == len(cfg_mod.STANDARD_CATEGORIES)
        widget = self.query_one("#fs-status", Static)
        if is_full:
            widget.update("★  Full Spectrum — free live streaming unlocked")
            widget.remove_class("full")
            widget.add_class("full")
        else:
            widget.update(
                f"  {enabled} / {len(cfg_mod.STANDARD_CATEGORIES)} enabled"
                "  —  enable all 10 for free live streaming"
            )
            widget.remove_class("full")
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self.query_one("#preview-content", Static).update(
            _build_preview(self._redact)
        )

    def action_save(self) -> None:
        self._cfg["capture"] = self._capture
        self._cfg["publish_redact"] = self._redact
        self._cfg["consent_acknowledged"] = True
        self.exit(self._cfg)

    def action_cancel(self) -> None:
        self.exit(None)

    def action_reset_defaults(self) -> None:
        self._capture = dict(cfg_mod._DEFAULTS["capture"])
        self._redact = dict(cfg_mod._DEFAULTS["publish_redact"])
        for cat in cfg_mod.STANDARD_CATEGORIES:
            self.query_one(f"#cap-{cat}", Switch).value = self._capture[cat]
        self.query_one("#cap-code_capture", Switch).value = self._capture["code_capture"]
        for key, _ in _REDACTABLE:
            self.query_one(f"#red-{key}", Switch).value = self._redact[key]
        self._refresh_fs_status()


def run(cfg: dict) -> dict:
    """Launch the consent TUI. Returns updated cfg, or unchanged cfg if cancelled."""
    result = ConsentApp(cfg).run()
    return result if result is not None else cfg
