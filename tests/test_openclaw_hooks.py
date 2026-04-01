"""Tests for OpenClaw hook and skill installer."""

import json
from pathlib import Path

import pytest

from methodproof.hooks import openclaw_install


@pytest.fixture(autouse=True)
def tmp_openclaw_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    monkeypatch.setattr(openclaw_install, "OPENCLAW_DIR", oc_dir)
    monkeypatch.setattr(openclaw_install, "HOOKS_DIR", oc_dir / "hooks" / "methodproof")
    monkeypatch.setattr(openclaw_install, "SKILLS_DIR", oc_dir / "skills" / "methodproof")
    monkeypatch.setattr(openclaw_install, "CONFIG_FILE", oc_dir / "config.json")
    return oc_dir


def test_install_copies_hook_dir(tmp_openclaw_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openclaw_install, "_has_openclaw", lambda: True)
    result = openclaw_install.install()
    assert result is not None
    hooks_dir = tmp_openclaw_dir / "hooks" / "methodproof"
    assert (hooks_dir / "HOOK.md").exists()
    assert (hooks_dir / "handler.ts").exists()


def test_install_enables_in_config(tmp_openclaw_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openclaw_install, "_has_openclaw", lambda: True)
    openclaw_install.install()
    cfg = json.loads((tmp_openclaw_dir / "config.json").read_text())
    assert cfg["hooks"]["internal"]["entries"]["methodproof"]["enabled"] is True


def test_install_idempotent(tmp_openclaw_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openclaw_install, "_has_openclaw", lambda: True)
    openclaw_install.install()
    result = openclaw_install.install()
    assert result == "already installed"


def test_install_skips_without_openclaw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openclaw_install, "_has_openclaw", lambda: False)
    assert openclaw_install.install() is None


def test_install_preserves_existing_config(tmp_openclaw_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openclaw_install, "_has_openclaw", lambda: True)
    existing = {"hooks": {"internal": {"enabled": True, "entries": {"other-hook": {"enabled": True}}}}, "other": 42}
    (tmp_openclaw_dir / "config.json").write_text(json.dumps(existing))

    openclaw_install.install()
    cfg = json.loads((tmp_openclaw_dir / "config.json").read_text())
    assert cfg["other"] == 42
    assert cfg["hooks"]["internal"]["entries"]["other-hook"]["enabled"] is True
    assert cfg["hooks"]["internal"]["entries"]["methodproof"]["enabled"] is True


def test_is_installed(tmp_openclaw_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openclaw_install, "_has_openclaw", lambda: True)
    assert not openclaw_install.is_installed()
    openclaw_install.install()
    assert openclaw_install.is_installed()


def test_install_skill(tmp_openclaw_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openclaw_install, "_has_openclaw", lambda: True)
    result = openclaw_install.install_skill()
    if result is not None:
        skills_dir = tmp_openclaw_dir / "skills" / "methodproof"
        assert (skills_dir / "SKILL.md").exists()


def test_install_skill_skips_without_openclaw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openclaw_install, "_has_openclaw", lambda: False)
    assert openclaw_install.install_skill() is None
