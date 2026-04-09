"""Tests for CLI config commands — consent, journal, reset, lock, uninstall."""

from unittest.mock import patch

import pytest

from methodproof import cli, config


# ── cmd_journal ──


def test_journal_on(cli_args, capsys):
    with patch("builtins.input", return_value="y"):
        cli.cmd_journal(cli_args(journal_cmd="on"))
    cfg = config.load()
    assert cfg["journal_mode"] is True


def test_journal_off(cli_args, capsys):
    cfg = config.load()
    cfg["journal_mode"] = True
    config.save(cfg)
    cli.cmd_journal(cli_args(journal_cmd="off"))
    cfg = config.load()
    assert cfg["journal_mode"] is False


def test_journal_status(cli_args, capsys):
    cli.cmd_journal(cli_args(journal_cmd="status"))
    out = capsys.readouterr().out
    assert "journal" in out.lower()


def test_journal_no_subcmd(cli_args, capsys):
    cli.cmd_journal(cli_args(journal_cmd=None))
    assert "Usage" in capsys.readouterr().out


# ── cmd_reset ──


def test_reset_clears_auth(logged_in_cfg, cli_args, capsys):
    logged_in_cfg(email="test@mp.com")
    with patch("builtins.input", return_value="y"):
        cli.cmd_reset(cli_args())
    cfg = config.load()
    assert cfg["token"] == ""
    assert cfg["account_id"] == ""
    assert "Cleared" in capsys.readouterr().out


def test_reset_cancelled(logged_in_cfg, cli_args, capsys):
    logged_in_cfg()
    with patch("builtins.input", return_value="n"):
        cli.cmd_reset(cli_args())
    cfg = config.load()
    assert cfg["token"] != ""  # unchanged


def test_reset_force(logged_in_cfg, cli_args):
    logged_in_cfg()
    cli.cmd_reset(cli_args(force=True))
    cfg = config.load()
    assert cfg["token"] == ""


# ── cmd_lock ──


def test_lock_no_account(cli_args, capsys):
    cli.cmd_lock(cli_args())
    assert "Nothing to lock" in capsys.readouterr().out


@patch("methodproof.lock.lock")
def test_lock_with_confirmation(mock_lock, logged_in_cfg, cli_args, capsys):
    logged_in_cfg(account_id="acct-1")
    with patch("builtins.input", return_value="y"):
        cli.cmd_lock(cli_args())
    mock_lock.assert_called_once_with("acct-1", purge=False)


@patch("methodproof.lock.lock")
def test_lock_purge(mock_lock, logged_in_cfg, cli_args):
    logged_in_cfg(account_id="acct-1")
    cli.cmd_lock(cli_args(force=True, purge=True))
    mock_lock.assert_called_once_with("acct-1", purge=True)


def test_lock_cancelled(logged_in_cfg, cli_args, capsys):
    logged_in_cfg(account_id="acct-1")
    with patch("builtins.input", return_value="n"):
        cli.cmd_lock(cli_args())
    assert "Cancelled" in capsys.readouterr().out


# ── cmd_consent ──


@patch("methodproof.sync.sync_research_consent")
def test_consent_saves_config(mock_sync, logged_in_cfg, cli_args, capsys):
    logged_in_cfg()
    with patch("methodproof.cli._run_consent_detailed") as mock_consent:
        mock_consent.return_value = config.load()
        cli.cmd_consent(cli_args())
    mock_consent.assert_called_once()
    assert "settings saved" in capsys.readouterr().out


# ── cmd_uninstall ──


def test_uninstall_force_removes_dir(cli_args, capsys):
    cli.cmd_uninstall(cli_args(force=True))
    out = capsys.readouterr().out
    assert "pip uninstall" in out


def test_uninstall_cancelled(cli_args, capsys):
    with patch("builtins.input", return_value="n"):
        cli.cmd_uninstall(cli_args())
    assert "Cancelled" in capsys.readouterr().out
