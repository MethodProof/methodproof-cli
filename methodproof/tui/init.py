"""Textual TUI for mp init — two-screen setup wizard."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, RichLog, Rule, Static, Switch

from methodproof import config as cfg_mod
from methodproof.tui.theme import BASE_CSS, BORDER, DIM, GOLD, GREEN, PURPLE, RED, TEXT

_REDACTABLE = [
    ("command_output", "Terminal output"),
    ("ai_prompts",     "AI prompt text"),
    ("ai_responses",   "AI response text"),
    ("code_capture",   "File diffs"),
]

_CSS = BASE_CSS + f"""
PrefsScreen {{
    padding: 0;
}}
#prefs-scroll {{
    padding: 1 3;
}}
.section-heading {{
    color: {GOLD};
    text-style: bold;
    margin: 1 0 0 0;
}}
.section-sub {{
    color: {DIM};
    margin: 0 0 1 0;
}}
.toggle-row {{
    height: 2;
    align: left middle;
}}
.toggle-row Switch {{
    margin: 0 1 0 0;
    width: 4;
}}
.row-label {{
    color: {TEXT};
}}
.pro-row .row-label {{
    color: {PURPLE};
}}
.pro-badge {{
    background: #200a26;
    color: {PURPLE};
    padding: 0 1;
    margin: 0 0 0 1;
    width: 5;
}}
.opt-row {{
    height: 2;
    align: left middle;
}}
.opt-row Switch {{
    margin: 0 1 0 0;
    width: 4;
}}
#fs-status {{
    color: {DIM};
    height: 1;
    margin: 1 0 0 0;
}}
#fs-status.full {{
    color: {GOLD};
}}
#begin-btn {{
    margin: 2 0 1 0;
    background: {GOLD};
    color: #12110f;
    border: none;
    width: 20;
}}

ResultsScreen {{
    padding: 0;
}}
#results-log {{
    padding: 1 2;
    border: none;
}}
#eval-box {{
    background: #050403;
    border: solid {BORDER};
    margin: 1 2;
    padding: 1 2;
    height: 5;
}}
#eval-label {{
    color: {DIM};
    margin: 0 0 1 0;
}}
#eval-cmd {{
    color: {GOLD};
    text-style: bold;
}}
"""


class PrefsScreen(Screen[dict | None]):
    """Step 1: collect all preferences before any side effects run."""

    BINDINGS = [
        Binding("enter", "begin", "begin setup"),
        Binding("escape", "cancel", "cancel"),
    ]

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self._capture = dict(cfg.get("capture", {}))
        self._redact = dict(cfg.get("publish_redact", {}))
        self._auto_update = cfg.get("auto_update", True)
        self._alias = cfg.get("alias_installed", True)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with ScrollableContainer(id="prefs-scroll"):
            yield Static("Capture settings", classes="section-heading")
            yield Static("Choose what MethodProof records during your sessions.", classes="section-sub")

            for cat in cfg_mod.STANDARD_CATEGORIES:
                desc = cfg_mod.CAPTURE_DESCRIPTIONS.get(cat, cat)
                enabled = self._capture.get(cat, True)
                with Horizontal(classes="toggle-row", id=f"row-cap-{cat}"):
                    yield Switch(value=enabled, id=f"cap-{cat}", animate=False)
                    yield Label(desc, classes="row-label")

            with Horizontal(classes="toggle-row pro-row", id="row-cap-code_capture"):
                yield Switch(value=self._capture.get("code_capture", False),
                             id="cap-code_capture", animate=False)
                yield Label("Full code diffs and git patches", classes="row-label")
                yield Static("Pro", classes="pro-badge")

            yield Static("", id="fs-status")

            yield Rule()
            yield Static("Publish redaction", classes="section-heading")
            yield Static(
                "Fields stripped when you make a session public via mp publish.",
                classes="section-sub",
            )

            for key, desc in _REDACTABLE:
                redacted = self._redact.get(key, True)
                with Horizontal(classes="toggle-row", id=f"row-red-{key}"):
                    yield Switch(value=redacted, id=f"red-{key}", animate=False)
                    yield Label(f"Redact: {desc}", classes="row-label")

            yield Rule()
            yield Static("Options", classes="section-heading")

            with Horizontal(classes="opt-row"):
                yield Switch(value=self._auto_update, id="opt-auto-update", animate=False)
                yield Label("Auto-update before each session", classes="row-label")

            with Horizontal(classes="opt-row"):
                yield Switch(value=self._alias, id="opt-alias", animate=False)
                yield Label("Install `mp` shorthand alias", classes="row-label")

            yield Button("Begin Setup →", id="begin-btn", variant="primary")

        yield Footer()

    def on_mount(self) -> None:
        self._refresh_fs()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        sid = event.switch.id or ""
        if sid.startswith("cap-"):
            cat = sid[4:]
            self._capture[cat] = event.value
            self._refresh_fs()
        elif sid.startswith("red-"):
            self._redact[sid[4:]] = event.value
        elif sid == "opt-auto-update":
            self._auto_update = event.value
        elif sid == "opt-alias":
            self._alias = event.value

    def _refresh_fs(self) -> None:
        all_on = all(self._capture.get(c, True) for c in cfg_mod.STANDARD_CATEGORIES)
        widget = self.query_one("#fs-status", Static)
        if all_on:
            widget.update(f"[{GOLD}]★ Full Spectrum — live streaming unlocked[/{GOLD}]")
            widget.add_class("full")
        else:
            widget.update(f"[{DIM}]Enable all 10 standard categories for Full Spectrum[/{DIM}]")
            widget.remove_class("full")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "begin-btn":
            self.action_begin()

    def action_begin(self) -> None:
        self.dismiss({
            "capture": self._capture,
            "publish_redact": self._redact,
            "auto_update": self._auto_update,
            "install_alias": self._alias,
        })

    def action_cancel(self) -> None:
        self.dismiss(None)


class ResultsScreen(Screen[None]):
    """Step 2: run side effects and display progress."""

    BINDINGS = [Binding("escape", "done", "done")]

    def __init__(self, cfg: dict, prefs: dict) -> None:
        super().__init__()
        self._cfg = cfg
        self._prefs = prefs

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield RichLog(id="results-log", highlight=True, markup=True)
        with Vertical(id="eval-box"):
            yield Static("Activate now (or restart your shell):", id="eval-label")
            yield Static('eval "$(methodproof shell-hook)"', id="eval-cmd", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._run_setup, exclusive=True, thread=True)

    def _log(self, msg: str) -> None:
        self.query_one(RichLog).write(msg)

    def _run_setup(self) -> None:
        from methodproof import config, store
        from methodproof.hooks import hook

        cfg = self._cfg
        prefs = self._prefs

        # Apply preferences
        cfg["capture"] = prefs["capture"]
        cfg["publish_redact"] = prefs["publish_redact"]
        cfg["auto_update"] = prefs["auto_update"]
        cfg["auto_update_offered"] = True
        cfg["alias_offered"] = True
        cfg["ui_mode_offered"] = True
        cfg["ui_mode"] = True
        cfg["consent_acknowledged"] = True

        if prefs["install_alias"]:
            try:
                from methodproof.cli import _install_alias
                _install_alias()
                cfg["alias_installed"] = True
                self._log(f"[{GREEN}]✓[/{GREEN}] Alias: mp → methodproof")
            except Exception as exc:
                self._log(f"[{DIM}]  Alias: skipped ({exc})[/{DIM}]")
        else:
            self._log(f"[{DIM}]  Alias: skipped[/{DIM}]")

        config.save(cfg)
        store.init_db()

        # Shell hook
        capture = cfg["capture"]
        if capture.get("terminal_commands", True):
            try:
                rc = hook.install()
                self._log(f"[{GREEN}]✓[/{GREEN}] Shell hook: {rc}")
            except Exception as exc:
                self._log(f"[{RED}]✗[/{RED}] Shell hook: {exc}")
        else:
            self._log(f"[{DIM}]  Shell hook: skipped (terminal_commands off)[/{DIM}]")

        # AI hooks
        ai_enabled = capture.get("ai_prompts", True) or capture.get("ai_responses", True)
        if ai_enabled:
            try:
                from methodproof.hooks.install import install as install_claude_hooks
                result = install_claude_hooks()
                if result is None:
                    self._log(f"[{DIM}]  Claude Code: not found[/{DIM}]")
                else:
                    self._log(f"[{GREEN}]✓[/{GREEN}] Claude Code hooks: {result}")
            except Exception as exc:
                self._log(f"[{DIM}]  Claude Code: {exc}[/{DIM}]")

            try:
                from methodproof.mcp import register_with_claude
                mcp = register_with_claude()
                if mcp is None:
                    self._log(f"[{DIM}]  Claude Code MCP: skipped[/{DIM}]")
                elif mcp == "already registered":
                    self._log(f"[{GREEN}]✓[/{GREEN}] Claude Code MCP: already registered")
                else:
                    self._log(f"[{GREEN}]✓[/{GREEN}] Claude Code MCP: registered in {mcp}")
            except Exception as exc:
                self._log(f"[{DIM}]  MCP: {exc}[/{DIM}]")

            try:
                from methodproof.hooks.wrappers import install as install_wrappers
                wrapped = install_wrappers()
                if wrapped:
                    self._log(f"[{GREEN}]✓[/{GREEN}] AI CLI wrappers: {', '.join(wrapped)}")
                else:
                    self._log(f"[{DIM}]  AI CLI wrappers: no tools found[/{DIM}]")
            except Exception as exc:
                self._log(f"[{DIM}]  AI CLI wrappers: {exc}[/{DIM}]")

            try:
                from methodproof.hooks.openclaw_install import install as install_oc, install_skill
                oc = install_oc()
                if oc is None:
                    self._log(f"[{DIM}]  OpenClaw: not found[/{DIM}]")
                else:
                    self._log(f"[{GREEN}]✓[/{GREEN}] OpenClaw hooks: {oc}")
                    skill = install_skill()
                    if skill:
                        self._log(f"[{GREEN}]✓[/{GREEN}] OpenClaw skill: {skill}")
            except Exception as exc:
                self._log(f"[{DIM}]  OpenClaw: {exc}[/{DIM}]")
        else:
            self._log(f"[{DIM}]  AI hooks: skipped[/{DIM}]")

        # Local AI ports — skip interactive prompt, use defaults
        if ai_enabled and not cfg.get("local_ai_ports_offered"):
            cfg["local_ai_ports_offered"] = True
            cfg["local_ai_ports"] = []
            config.save(cfg)
            self._log(f"[{DIM}]  Local AI ports: using defaults (Ollama 11434, Jan 1234)[/{DIM}]")

        # Signing key
        try:
            from methodproof.integrity import has_keypair
            if not has_keypair():
                from methodproof.integrity import generate_keypair
                pub = generate_keypair()
                self._log(f"[{GREEN}]✓[/{GREEN}] Signing key: generated ({len(pub)} bytes)")
            else:
                self._log(f"[{GREEN}]✓[/{GREEN}] Signing key: exists")
        except ImportError:
            self._log(f"[{DIM}]  Signing key: skipped (pip install methodproof[signing])[/{DIM}]")

        # Research consent sync
        if cfg.get("token"):
            try:
                cfg["_pending_research_sync"] = True
                config.save(cfg)
                from methodproof.sync import sync_research_consent
                sync_research_consent(cfg["token"], cfg["api_url"])
                self._log(f"[{GREEN}]✓[/{GREEN}] Research consent synced")
            except Exception:
                pass

        self._log("")
        self._log(f"[{GOLD}]Setup complete.[/{GOLD}]  Press Esc to exit.")

    def action_done(self) -> None:
        self.dismiss(None)


class InitApp(App[None]):
    """mp init setup wizard — preferences then install."""

    TITLE = "methodproof — mp init"
    CSS = _CSS

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self._cfg = cfg

    def on_mount(self) -> None:
        self.push_screen(PrefsScreen(self._cfg), self._on_prefs_done)

    def _on_prefs_done(self, prefs: dict | None) -> None:
        if prefs is None:
            self.exit(None)
            return
        self.push_screen(ResultsScreen(self._cfg, prefs))


def run(cfg: dict) -> None:
    """Launch the init wizard."""
    InitApp(cfg).run()
