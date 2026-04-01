"""Tests for Claude Code hook installer."""

import json
from pathlib import Path

import pytest

from methodproof.hooks import install as hooks_install


@pytest.fixture(autouse=True)
def tmp_claude_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    monkeypatch.setattr(hooks_install, "CLAUDE_DIR", claude_dir)
    monkeypatch.setattr(hooks_install, "SETTINGS_FILE", claude_dir / "settings.json")
    return claude_dir


def test_install_creates_settings(tmp_claude_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude" if x == "claude" else None)
    result = hooks_install.install()
    assert result is not None
    settings = json.loads((tmp_claude_dir / "settings.json").read_text())
    assert "hooks" in settings
    assert "PreToolUse" in settings["hooks"]
    assert "UserPromptSubmit" in settings["hooks"]
    assert "SubagentStart" in settings["hooks"]


def test_install_idempotent(tmp_claude_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude" if x == "claude" else None)
    hooks_install.install()
    result = hooks_install.install()
    assert result == "already installed"


def test_install_skips_without_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda x: None)
    assert hooks_install.install() is None


def test_install_preserves_existing_hooks(tmp_claude_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude" if x == "claude" else None)
    existing = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "other.sh"}]}]}}
    (tmp_claude_dir / "settings.json").write_text(json.dumps(existing))

    hooks_install.install()
    settings = json.loads((tmp_claude_dir / "settings.json").read_text())
    # Should have both the existing hook AND the new one
    pre_tool = settings["hooks"]["PreToolUse"]
    commands = [h["command"] for g in pre_tool for h in g.get("hooks", [])]
    assert "other.sh" in commands
    assert str(hooks_install.HOOK_SCRIPT) in commands


def test_is_installed(tmp_claude_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude" if x == "claude" else None)
    assert not hooks_install.is_installed()
    hooks_install.install()
    assert hooks_install.is_installed()


def test_all_hook_events_registered(tmp_claude_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude" if x == "claude" else None)
    hooks_install.install()
    settings = json.loads((tmp_claude_dir / "settings.json").read_text())
    for event in hooks_install.HOOK_EVENTS:
        assert event in settings["hooks"], f"Missing hook: {event}"
