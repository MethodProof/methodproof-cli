"""Tests for CLI session commands — start, stop, status, log."""

import os
import signal
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from methodproof import cli, config, store


# ── _is_daemon_alive ──


def test_daemon_alive_no_pidfile(monkeypatch):
    monkeypatch.setattr(cli, "PIDFILE", config.DIR / "methodproof.pid")
    assert cli._is_daemon_alive() is False


def test_daemon_alive_valid_pid(monkeypatch, tmp_path):
    pidfile = config.DIR / "methodproof.pid"
    pidfile.write_text(str(os.getpid()))
    monkeypatch.setattr(cli, "PIDFILE", pidfile)
    with patch("subprocess.check_output", return_value="python methodproof daemon"):
        assert cli._is_daemon_alive() is True


def test_daemon_alive_wrong_process(monkeypatch):
    pidfile = config.DIR / "methodproof.pid"
    pidfile.write_text(str(os.getpid()))
    monkeypatch.setattr(cli, "PIDFILE", pidfile)
    with patch("subprocess.check_output", return_value="nginx worker"):
        assert cli._is_daemon_alive() is False


def test_daemon_alive_dead_pid(monkeypatch):
    pidfile = config.DIR / "methodproof.pid"
    pidfile.write_text("999999999")
    monkeypatch.setattr(cli, "PIDFILE", pidfile)
    assert cli._is_daemon_alive() is False


# ── cmd_stop ──


def test_stop_no_active_session(cli_args):
    with pytest.raises(SystemExit):
        cli.cmd_stop(cli_args())


@patch("os.kill")
@patch("time.sleep")
def test_stop_sends_sigterm(mock_sleep, mock_kill, cli_args, make_session, monkeypatch):
    sid, _ = make_session()
    cfg = config.load()
    cfg["active_session"] = sid
    config.save(cfg)
    pidfile = config.DIR / "methodproof.pid"
    pidfile.write_text("12345")
    monkeypatch.setattr(cli, "PIDFILE", pidfile)

    cli.cmd_stop(cli_args())
    mock_kill.assert_called_once_with(12345, signal.SIGTERM)


@patch("methodproof.agents.base.init")
@patch("methodproof.agents.base.flush")
def test_stop_fallback_completes_directly(mock_flush, mock_init, cli_args, make_session, monkeypatch, capsys):
    sid, _ = make_session()
    # Undo completion so stop can complete it
    store._db().execute("UPDATE sessions SET completed_at = NULL WHERE id = ?", (sid,))
    store._db().commit()
    cfg = config.load()
    cfg["active_session"] = sid
    config.save(cfg)
    monkeypatch.setattr(cli, "PIDFILE", config.DIR / "methodproof.pid")

    cli.cmd_stop(cli_args())
    saved = config.load()
    assert saved["active_session"] is None


# ── cmd_status ──


def test_status_not_signed_in(cli_args, capsys):
    cli.cmd_status(cli_args())
    out = capsys.readouterr().out
    assert "not signed in" in out


def test_status_signed_in(logged_in_cfg, cli_args, capsys):
    logged_in_cfg(account_id="acct-1")
    cli.cmd_status(cli_args())
    out = capsys.readouterr().out
    assert "signed in" in out
    assert "acct-1" in out


def test_status_active_session(logged_in_cfg, make_session, cli_args, capsys):
    logged_in_cfg()
    sid, _ = make_session()
    cfg = config.load()
    cfg["active_session"] = sid
    config.save(cfg)
    cli.cmd_status(cli_args())
    out = capsys.readouterr().out
    assert "RECORDING" in out


def test_status_idle(logged_in_cfg, cli_args, capsys):
    logged_in_cfg()
    cli.cmd_status(cli_args())
    out = capsys.readouterr().out
    assert "idle" in out


def test_status_shows_profiles_hint(logged_in_cfg, fake_jwt, cli_args, capsys):
    cfg = logged_in_cfg(account_id="acct-a")
    config.save_active_profile(cfg)
    cfg["account_id"] = "acct-b"
    cfg["token"] = fake_jwt(user_id="acct-b")
    config.save_active_profile(cfg)
    config.save(cfg)
    cli.cmd_status(cli_args())
    out = capsys.readouterr().out
    assert "mp switch" in out


# ── cmd_log ──


def test_log_no_sessions(cli_args, capsys):
    cli.cmd_log(cli_args())
    assert "No sessions yet" in capsys.readouterr().out


def test_log_lists_sessions(make_session, cli_args, capsys):
    make_session()
    make_session()
    cli.cmd_log(cli_args())
    out = capsys.readouterr().out
    assert "events" in out
    assert out.count("events") >= 2  # each session line contains "events"


def test_log_shows_unsynced_count(make_session, cli_args, capsys):
    make_session()
    cli.cmd_log(cli_args())
    out = capsys.readouterr().out
    assert "behind sync" in out
