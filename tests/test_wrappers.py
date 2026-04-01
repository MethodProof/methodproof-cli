"""Tests for AI CLI wrappers."""

from pathlib import Path

import pytest

from methodproof.hooks import wrappers


@pytest.fixture(autouse=True)
def clean_rc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    rc = tmp_path / ".zshrc"
    rc.write_text("# existing config\n")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return rc


def test_install_with_codex(clean_rc: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda x: f"/usr/local/bin/{x}" if x == "codex" else None)
    wrapped = wrappers.install()
    assert "codex" in wrapped
    content = clean_rc.read_text()
    assert "_mp_codex" in content
    assert "/usr/local/bin/codex" in content
    assert "alias codex=" in content


def test_install_multiple_tools(clean_rc: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    found = {"codex": "/usr/local/bin/codex", "aider": "/usr/local/bin/aider"}
    monkeypatch.setattr("shutil.which", lambda x: found.get(x))
    wrapped = wrappers.install()
    assert "codex" in wrapped
    assert "aider" in wrapped


def test_install_no_tools(clean_rc: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda x: None)
    wrapped = wrappers.install()
    assert wrapped == []
    assert wrappers.MARKER not in clean_rc.read_text()


def test_install_idempotent(clean_rc: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/codex" if x == "codex" else None)
    wrappers.install()
    wrappers.install()  # second call
    content = clean_rc.read_text()
    assert content.count(wrappers.MARKER) == 2  # start + end markers, not duplicated


def test_is_installed(clean_rc: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/codex" if x == "codex" else None)
    assert not wrappers.is_installed()
    wrappers.install()
    assert wrappers.is_installed()


def test_wrapper_calls_real_binary(clean_rc: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrapper references the resolved binary path, not the alias."""
    monkeypatch.setattr("shutil.which", lambda x: "/opt/homebrew/bin/codex" if x == "codex" else None)
    wrappers.install()
    content = clean_rc.read_text()
    assert "/opt/homebrew/bin/codex" in content  # real path, not "codex"


def test_wrapper_posts_to_bridge(clean_rc: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrapper contains curl POST to localhost:9877."""
    monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/codex" if x == "codex" else None)
    wrappers.install()
    content = clean_rc.read_text()
    assert "localhost:9877/events" in content
    assert "ai_cli_start" in content
    assert "ai_cli_end" in content
