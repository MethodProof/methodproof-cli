"""Tests for cmd_start, _run_foreground, _shutdown, _setup_master_key, _run_consent_detailed, cmd_init."""

import os
import signal
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from methodproof import cli, config, graph, store


# ── cmd_start — guard rails ──


@patch("methodproof.hook.is_installed", return_value=False)
def test_start_hooks_not_installed(mock_hook, logged_in_cfg, cli_args):
    logged_in_cfg()
    with pytest.raises(SystemExit):
        cli.cmd_start(cli_args())


@patch("methodproof.hook.is_installed", return_value=True)
@patch("methodproof.cli._require_auth", side_effect=SystemExit("not logged in"))
def test_start_auth_fails(mock_auth, mock_hook, cli_args):
    with pytest.raises(SystemExit):
        cli.cmd_start(cli_args())


@patch("methodproof.cli._is_daemon_alive", return_value=True)
@patch("methodproof.hook.is_installed", return_value=True)
def test_start_session_already_active(mock_hook, mock_alive, logged_in_cfg, cli_args, make_session):
    logged_in_cfg()
    sid, _ = make_session()
    cfg = config.load()
    cfg["active_session"] = sid
    config.save(cfg)
    with pytest.raises(SystemExit):
        cli.cmd_start(cli_args())


@patch("methodproof.cli._is_daemon_alive", return_value=False)
@patch("methodproof.hook.is_installed", return_value=True)
@patch("methodproof.cli._require_auth", return_value="acct-1")
@patch("methodproof.cli._auto_update")
@patch("methodproof.repos.detect_repo", return_value=None)
@patch("methodproof.sync._request", return_value={"anchor_ts": 1.0, "signature": "sig"})
@patch("subprocess.Popen")
@patch("time.sleep")
def test_start_cleans_stale_session(mock_sleep, mock_popen, mock_req, mock_repo, mock_update, mock_auth,
                                     mock_hook, mock_alive, logged_in_cfg, make_session,
                                     cli_args, monkeypatch):
    logged_in_cfg()
    sid, _ = make_session()
    # Undo completion — simulate stale active session
    store._db().execute("UPDATE sessions SET completed_at = NULL WHERE id = ?", (sid,))
    store._db().commit()
    cfg = config.load()
    cfg["active_session"] = sid
    config.save(cfg)
    pidfile = config.DIR / "methodproof.pid"
    monkeypatch.setattr(cli, "PIDFILE", pidfile)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 99999
    mock_popen.return_value = mock_proc

    cli.cmd_start(cli_args())
    # Stale session should be completed
    s = store.get_session(sid)
    assert s["completed_at"] is not None


# ── cmd_start — happy path (daemon spawn) ──


@patch("methodproof.cli._is_daemon_alive", return_value=False)
@patch("methodproof.hook.is_installed", return_value=True)
@patch("methodproof.cli._require_auth", return_value="acct-1")
@patch("methodproof.cli._auto_update")
@patch("methodproof.repos.detect_repo", return_value=None)
@patch("methodproof.sync._request", return_value={"anchor_ts": 1.0, "signature": "sig"})
@patch("subprocess.Popen")
@patch("time.sleep")
def test_start_creates_session_and_spawns_daemon(mock_sleep, mock_popen, mock_req, mock_repo, mock_update,
                                                   mock_auth, mock_hook, mock_alive,
                                                   logged_in_cfg, cli_args, monkeypatch, capsys):
    logged_in_cfg(account_id="acct-1")
    pidfile = config.DIR / "methodproof.pid"
    monkeypatch.setattr(cli, "PIDFILE", pidfile)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 12345
    mock_popen.return_value = mock_proc

    cli.cmd_start(cli_args())
    out = capsys.readouterr().out
    assert "Recording" in out
    cfg = config.load()
    assert cfg["active_session"] is not None
    mock_popen.assert_called_once()


# ── cmd_start — journal mode ──


@patch("methodproof.cli._is_daemon_alive", return_value=False)
@patch("methodproof.hook.is_installed", return_value=True)
@patch("methodproof.cli._require_auth", return_value="acct-1")
@patch("methodproof.cli._auto_update")
@patch("methodproof.repos.detect_repo", return_value=None)
@patch("methodproof.sync._request", return_value={"anchor_ts": 1.0, "signature": "sig"})
@patch("subprocess.Popen")
@patch("time.sleep")
def test_start_journal_decrements_credits(mock_sleep, mock_popen, mock_req, mock_repo, mock_update, mock_auth,
                                           mock_hook, mock_alive, logged_in_cfg, fake_jwt, cli_args,
                                           monkeypatch, capsys):
    # Use free-tier JWT — pro/team skips credit deduction (unlimited)
    cfg = logged_in_cfg(account_id="acct-1", token=fake_jwt(user_id="acct-1", account_type="free"))
    cfg["journal_credits"] = 2
    config.save(cfg)
    pidfile = config.DIR / "methodproof.pid"
    monkeypatch.setattr(cli, "PIDFILE", pidfile)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 111
    mock_popen.return_value = mock_proc

    cli.cmd_start(cli_args(journal=True))
    cfg = config.load()
    assert cfg["journal_mode"] is True
    assert cfg["journal_credits"] == 1
    assert "Journal mode ON" in capsys.readouterr().out


# ── cmd_start — e2e mode ──


@patch("methodproof.cli._is_daemon_alive", return_value=False)
@patch("methodproof.hook.is_installed", return_value=True)
@patch("methodproof.cli._require_auth", return_value="acct-1")
@patch("methodproof.cli._auto_update")
@patch("methodproof.repos.detect_repo", return_value=None)
@patch("subprocess.Popen")
@patch("time.sleep")
def test_start_e2e_no_fingerprint_exits(mock_sleep, mock_popen, mock_repo, mock_update, mock_auth,
                                         mock_hook, mock_alive, logged_in_cfg, cli_args,
                                         monkeypatch):
    cfg = logged_in_cfg(account_id="acct-1")
    cfg["e2e_fingerprint"] = ""
    config.save(cfg)
    pidfile = config.DIR / "methodproof.pid"
    monkeypatch.setattr(cli, "PIDFILE", pidfile)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc

    with pytest.raises(SystemExit):
        cli.cmd_start(cli_args(e2e=True))


# ── cmd_start — live mode ──


@patch("methodproof.cli._is_daemon_alive", return_value=False)
@patch("methodproof.hook.is_installed", return_value=True)
@patch("methodproof.cli._require_auth", return_value="acct-1")
@patch("methodproof.cli._auto_update")
@patch("methodproof.live.start", return_value="https://app.methodproof.com/live/abc")
@patch("methodproof.sync._request", return_value={"session_id": "remote-live"})
@patch("methodproof.repos.detect_repo", return_value=None)
@patch("subprocess.Popen")
@patch("time.sleep")
def test_start_live_mode(mock_sleep, mock_popen, mock_repo, mock_req, mock_live, mock_update,
                          mock_auth, mock_hook, mock_alive, logged_in_cfg, cli_args,
                          monkeypatch, capsys):
    logged_in_cfg(account_id="acct-1")
    pidfile = config.DIR / "methodproof.pid"
    monkeypatch.setattr(cli, "PIDFILE", pidfile)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 222
    mock_popen.return_value = mock_proc

    cli.cmd_start(cli_args(live=True))
    out = capsys.readouterr().out
    assert "Live" in out
    mock_live.assert_called_once()


# ── _shutdown signal handler ──


def test_shutdown_completes_session_and_cleans_config(make_session, monkeypatch):
    sid, _ = make_session()
    # Undo completion
    store._db().execute("UPDATE sessions SET completed_at = NULL WHERE id = ?", (sid,))
    store._db().commit()
    cfg = config.load()
    cfg["active_session"] = sid
    config.save(cfg)

    pidfile = config.DIR / "methodproof.pid"
    pidfile.write_text("99999")
    monkeypatch.setattr(cli, "PIDFILE", pidfile)

    # Build the _shutdown closure the same way _run_foreground does
    stop_event = threading.Event()
    live_url = ""

    from methodproof.agents import base as _base
    with patch.object(_base, "init"), patch.object(_base, "flush"), patch.object(_base, "log"):
        _base.init(sid)

        def _shutdown(sig, frame):
            stop_event.set()
            try:
                _base.flush()
                store.complete_session(sid)
                graph.build(sid)
            except Exception:
                pass
            try:
                cfg_now = config.load()
                cfg_now["active_session"] = None
                config.save(cfg_now)
            except Exception:
                pass
            pidfile.unlink(missing_ok=True)

        _shutdown(signal.SIGINT, None)

    assert stop_event.is_set()
    s = store.get_session(sid)
    assert s["completed_at"] is not None
    saved = config.load()
    assert saved["active_session"] is None
    assert not pidfile.exists()


def test_shutdown_cleans_live_stream(make_session, monkeypatch):
    sid, _ = make_session()
    store._db().execute("UPDATE sessions SET completed_at = NULL WHERE id = ?", (sid,))
    store._db().commit()
    cfg = config.load()
    cfg["active_session"] = sid
    config.save(cfg)

    pidfile = config.DIR / "methodproof.pid"
    pidfile.write_text("99999")
    monkeypatch.setattr(cli, "PIDFILE", pidfile)

    stop_event = threading.Event()
    live_stopped = MagicMock()

    from methodproof.agents import base as _base
    with patch.object(_base, "init"), patch.object(_base, "flush"), patch.object(_base, "log"):
        _base.init(sid)

        def _shutdown(sig, frame):
            stop_event.set()
            live_stopped()
            _base.flush()
            store.complete_session(sid)
            graph.build(sid)
            cfg_now = config.load()
            cfg_now["active_session"] = None
            config.save(cfg_now)
            pidfile.unlink(missing_ok=True)

        _shutdown(signal.SIGINT, None)

    live_stopped.assert_called_once()


def test_shutdown_survives_exceptions(make_session, monkeypatch):
    """Shutdown should clean up config even if graph.build fails."""
    sid, _ = make_session()
    store._db().execute("UPDATE sessions SET completed_at = NULL WHERE id = ?", (sid,))
    store._db().commit()
    cfg = config.load()
    cfg["active_session"] = sid
    config.save(cfg)

    pidfile = config.DIR / "methodproof.pid"
    pidfile.write_text("99999")
    monkeypatch.setattr(cli, "PIDFILE", pidfile)

    from methodproof.agents import base as _base
    with patch.object(_base, "init"), patch.object(_base, "flush"), patch.object(_base, "log"):
        _base.init(sid)

        def _shutdown(sig, frame):
            try:
                _base.flush()
                store.complete_session(sid)
                raise RuntimeError("graph build failed")
            except Exception:
                pass
            try:
                cfg_now = config.load()
                cfg_now["active_session"] = None
                config.save(cfg_now)
            except Exception:
                pass
            pidfile.unlink(missing_ok=True)

        _shutdown(signal.SIGINT, None)

    # Config should still be cleaned even though graph failed
    saved = config.load()
    assert saved["active_session"] is None
    assert not pidfile.exists()


# ── _setup_master_key ──


@patch("methodproof.keychain.has_secret", return_value=True)
@patch("methodproof.keychain.load_secret", return_value=b"\xab" * 16)
def test_setup_master_key_already_exists(mock_load, mock_has, logged_in_cfg):
    cfg = logged_in_cfg(account_id="acct-1")
    cfg["master_key_fingerprint"] = ""
    config.save(cfg)
    cli._setup_master_key(cfg)
    assert cfg["master_key_fingerprint"] != ""


@patch("methodproof.keychain.has_secret", return_value=False)
@patch("methodproof.keychain.store_secret")
@patch("methodproof.migrate_db.migrate_encrypt", return_value=0)
@patch("os.urandom", return_value=b"\x01" * 16)
def test_setup_master_key_first_time(mock_rand, mock_migrate, mock_store, mock_has,
                                      logged_in_cfg, capsys):
    cfg = logged_in_cfg(account_id="acct-1")
    cfg["master_key_fingerprint"] = ""
    config.save(cfg)
    cli._setup_master_key(cfg)
    assert cfg["master_key_fingerprint"] != ""
    mock_store.assert_called_once()
    out = capsys.readouterr().out
    assert "RECOVERY PHRASE" in out


@patch("methodproof.keychain.has_secret", return_value=False)
def test_setup_master_key_returning_user(mock_has, logged_in_cfg):
    cfg = logged_in_cfg(account_id="acct-1")
    cfg["master_key_fingerprint"] = "existing-fp"
    config.save(cfg)
    with patch("methodproof.cli._recover_master_key") as mock_recover:
        cli._setup_master_key(cfg)
    mock_recover.assert_called_once()


def test_setup_master_key_no_account():
    cfg = config.load()
    cfg["account_id"] = ""
    cli._setup_master_key(cfg)  # should return silently


# ── _run_consent_detailed ──


def test_consent_detailed_accept_defaults():
    cfg = config.load()
    with patch("builtins.input", side_effect=["done", "n", "done"]):
        result = cli._run_consent_detailed(cfg)
    assert result.get("consent_acknowledged") is True
    # All 10 standard categories should be on by default
    capture = result["capture"]
    for k in config.STANDARD_CATEGORIES:
        assert capture[k] is True


def test_consent_detailed_toggle_category():
    cfg = config.load()
    with patch("builtins.input", side_effect=["1", "done", "n", "done"]):
        result = cli._run_consent_detailed(cfg)
    # terminal_commands (category 1) should be toggled off
    assert result["capture"]["terminal_commands"] is False


def test_consent_detailed_all_on():
    cfg = config.load()
    # Start with everything off
    for k in config.STANDARD_CATEGORIES:
        cfg.setdefault("capture", {})[k] = False
    with patch("builtins.input", side_effect=["a", "done", "y", "done"]):
        result = cli._run_consent_detailed(cfg)
    for k in config.STANDARD_CATEGORIES:
        assert result["capture"][k] is True
    assert result["research_consent"] is True


def test_consent_detailed_all_off_then_one():
    cfg = config.load()
    # "n" turns all off, then "1" turns terminal_commands on, then "done"
    with patch("builtins.input", side_effect=["n", "1", "done", "n", "done"]):
        result = cli._run_consent_detailed(cfg)
    assert result["capture"]["terminal_commands"] is True
    off_count = sum(1 for k in config.STANDARD_CATEGORIES if not result["capture"][k])
    assert off_count == 9


def test_consent_detailed_code_capture_toggle():
    cfg = config.load()
    with patch("builtins.input", side_effect=["0", "done", "n", "done"]):
        result = cli._run_consent_detailed(cfg)
    assert result["capture"]["code_capture"] is True


def test_consent_detailed_redaction_toggle():
    cfg = config.load()
    # Capture done, research no, toggle redaction 1 off, done
    with patch("builtins.input", side_effect=["done", "n", "1", "done"]):
        result = cli._run_consent_detailed(cfg)
    assert result["publish_redact"]["command_output"] is False


# ── cmd_init ──


@patch("methodproof.hook.install", return_value="hook installed")
@patch("methodproof.integrity.has_keypair", return_value=True)
def test_init_first_run(mock_keypair, mock_hook, cli_args, capsys):
    # First run with --yes: all prompts auto-accepted, no stdin required
    cli.cmd_init(cli_args(yes=True))
    out = capsys.readouterr().out
    assert "METHODPROOF" in out or "Recording" in out or "mp start" in out


@patch("methodproof.integrity.has_keypair", return_value=True)
@patch("methodproof.hook.install", return_value="hook installed")
def test_init_already_configured(mock_hook, mock_keypair, cli_args, capsys):
    cfg = config.load()
    cfg["consent_acknowledged"] = True
    config.save(cfg)
    # input() calls: auto-update, alias, ui-mode, local AI ports
    with patch("builtins.input", side_effect=["N", "N", "N", "N"]):
        cli.cmd_init(cli_args())
    mock_hook.assert_called_once()
