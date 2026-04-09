"""Tests for CLI auth commands — login, logout, accounts, switch, _require_auth."""

import time
from unittest.mock import MagicMock, patch

import pytest

from methodproof import cli, config


# ── _require_auth ──


def test_require_auth_valid_token(logged_in_cfg, fake_jwt):
    cfg = logged_in_cfg(account_id="acct-1")
    result = cli._require_auth(cfg)
    assert result == "acct-1"


def test_require_auth_no_token():
    cfg = config.load()
    cfg["token"] = ""
    with pytest.raises(SystemExit):
        cli._require_auth(cfg)


def test_require_auth_expired_refresh_succeeds(logged_in_cfg, fake_jwt):
    expired_token = fake_jwt(user_id="acct-1", exp=time.time() - 100)
    cfg = logged_in_cfg(account_id="acct-1", token=expired_token)
    cfg["refresh_token"] = "valid-refresh"
    config.save(cfg)

    new_token = fake_jwt(user_id="acct-1", exp=time.time() + 3600)
    with patch("methodproof.sync._refresh_token", return_value=(new_token, "new-refresh")):
        result = cli._require_auth(cfg)
    assert result == "acct-1"
    saved = config.load()
    assert saved["token"] == new_token


def test_require_auth_expired_within_grace(logged_in_cfg, fake_jwt):
    expired_token = fake_jwt(user_id="acct-1", exp=time.time() - 100)
    cfg = logged_in_cfg(account_id="acct-1", token=expired_token)
    cfg["last_auth_at"] = time.time() - 3600  # 1h ago, within 24h grace
    config.save(cfg)

    with patch("methodproof.sync._refresh_token", return_value=None):
        result = cli._require_auth(cfg)
    assert result == "acct-1"


def test_require_auth_expired_outside_grace(logged_in_cfg, fake_jwt):
    expired_token = fake_jwt(user_id="acct-1", exp=time.time() - 100)
    cfg = logged_in_cfg(account_id="acct-1", token=expired_token)
    cfg["last_auth_at"] = time.time() - 100000  # way outside 24h
    cfg["refresh_token"] = ""
    config.save(cfg)

    with pytest.raises(SystemExit):
        cli._require_auth(cfg)


# ── cmd_logout ──


def test_logout_clears_auth(logged_in_cfg, cli_args, capsys):
    logged_in_cfg(email="user@test.com")
    cli.cmd_logout(cli_args())
    cfg = config.load()
    assert cfg["token"] == ""
    assert cfg["account_id"] == ""
    assert "Logged out" in capsys.readouterr().out


def test_logout_already_logged_out(cli_args, capsys):
    cli.cmd_logout(cli_args())
    assert "Not logged in" in capsys.readouterr().out


# ── cmd_accounts ──


def test_accounts_no_profiles(cli_args, capsys):
    cli.cmd_accounts(cli_args())
    assert "No accounts" in capsys.readouterr().out


def test_accounts_lists_multiple(logged_in_cfg, fake_jwt, cli_args, capsys):
    cfg = logged_in_cfg(account_id="acct-a", email="a@test.com")
    config.save_active_profile(cfg)
    cfg["account_id"] = "acct-b"
    cfg["email"] = "b@test.com"
    cfg["token"] = fake_jwt(user_id="acct-b")
    config.save_active_profile(cfg)
    config.save(cfg)

    cli.cmd_accounts(cli_args())
    out = capsys.readouterr().out
    assert "a@test.com" in out
    assert "b@test.com" in out
    assert "*" in out  # active marker


def test_accounts_shows_expired_token(logged_in_cfg, fake_jwt, cli_args, capsys):
    expired = fake_jwt(user_id="acct-x", exp=time.time() - 100)
    logged_in_cfg(account_id="acct-x", email="x@test.com", token=expired)
    config.save_active_profile(config.load())

    cli.cmd_accounts(cli_args())
    assert "expired" in capsys.readouterr().out


# ── cmd_switch ──


def test_switch_by_email(logged_in_cfg, fake_jwt, cli_args, capsys):
    cfg = logged_in_cfg(account_id="acct-a", email="a@test.com")
    config.save_active_profile(cfg)
    cfg["account_id"] = "acct-b"
    cfg["email"] = "b@test.com"
    cfg["token"] = fake_jwt(user_id="acct-b")
    config.save_active_profile(cfg)
    config.save(cfg)

    with patch("methodproof.cli._setup_master_key"):
        cli.cmd_switch(cli_args(account="a@test.com"))
    saved = config.load()
    assert saved["account_id"] == "acct-a"
    assert "Switched to" in capsys.readouterr().out


def test_switch_by_id_prefix(logged_in_cfg, fake_jwt, cli_args, capsys):
    cfg = logged_in_cfg(account_id="acct-a", email="a@test.com")
    config.save_active_profile(cfg)
    cfg["account_id"] = "acct-b"
    cfg["email"] = "b@test.com"
    cfg["token"] = fake_jwt(user_id="acct-b")
    config.save_active_profile(cfg)
    config.save(cfg)

    with patch("methodproof.cli._setup_master_key"):
        cli.cmd_switch(cli_args(account="acct-a"))
    assert config.load()["account_id"] == "acct-a"


def test_switch_no_match(logged_in_cfg, cli_args, capsys):
    cfg = logged_in_cfg(account_id="acct-a")
    config.save_active_profile(cfg)
    config.save(cfg)

    cli.cmd_switch(cli_args(account="zzz"))
    assert "No account matching" in capsys.readouterr().out


def test_switch_already_active(logged_in_cfg, cli_args, capsys):
    cfg = logged_in_cfg(account_id="acct-a", email="a@test.com")
    config.save_active_profile(cfg)
    config.save(cfg)

    cli.cmd_switch(cli_args(account="acct-a"))
    assert "Already active" in capsys.readouterr().out


def test_switch_no_stored_accounts(cli_args, capsys):
    cli.cmd_switch(cli_args())
    assert "No stored accounts" in capsys.readouterr().out


def test_switch_interactive_picker(logged_in_cfg, fake_jwt, cli_args, capsys):
    cfg = logged_in_cfg(account_id="acct-a", email="a@test.com")
    config.save_active_profile(cfg)
    cfg["account_id"] = "acct-b"
    cfg["email"] = "b@test.com"
    cfg["token"] = fake_jwt(user_id="acct-b")
    config.save_active_profile(cfg)
    config.save(cfg)

    with patch("builtins.input", return_value="1"), \
         patch("methodproof.cli._setup_master_key"):
        cli.cmd_switch(cli_args())  # no account arg → interactive
    assert config.load()["account_id"] == "acct-a"


def test_switch_interactive_cancel(logged_in_cfg, fake_jwt, cli_args, capsys):
    cfg = logged_in_cfg(account_id="acct-a", email="a@test.com")
    config.save_active_profile(cfg)
    cfg["account_id"] = "acct-b"
    cfg["token"] = fake_jwt(user_id="acct-b")
    config.save_active_profile(cfg)
    config.save(cfg)

    with patch("builtins.input", side_effect=KeyboardInterrupt):
        cli.cmd_switch(cli_args())
    assert "Cancelled" in capsys.readouterr().out


# ── cmd_login ──


@patch("methodproof.sync.sync_research_consent")
@patch("methodproof.cli._setup_master_key")
@patch("webbrowser.open")
@patch("time.sleep")
@patch("methodproof.sync._request")
def test_login_happy_path(mock_req, mock_sleep, mock_browser, mock_key, mock_consent,
                          fake_jwt, cli_args, capsys):
    token = fake_jwt(user_id="new-user")
    mock_req.side_effect = [
        {"code": "abc", "auth_url": "https://auth.test/abc"},  # POST /auth/cli/start
        {"status": "complete", "token": token, "refresh_token": "ref-1"},  # poll
    ]
    cli.cmd_login(cli_args())
    cfg = config.load()
    assert cfg["token"] == token
    assert cfg["account_id"] == "new-user"
    mock_browser.assert_called_once()
    out = capsys.readouterr().out
    assert "Logged in" in out


@patch("methodproof.sync._request")
def test_login_already_logged_in_decline(mock_req, logged_in_cfg, cli_args, capsys):
    logged_in_cfg(email="current@test.com")
    with patch("builtins.input", return_value="n"):
        cli.cmd_login(cli_args())
    mock_req.assert_not_called()  # never started auth flow


@patch("methodproof.sync.sync_research_consent")
@patch("methodproof.cli._setup_master_key")
@patch("webbrowser.open")
@patch("time.sleep")
@patch("methodproof.sync._request")
def test_login_switch_stashes_profile(mock_req, mock_sleep, mock_browser, mock_key, mock_consent,
                                      logged_in_cfg, fake_jwt, cli_args):
    logged_in_cfg(account_id="old-acct", email="old@test.com")
    new_token = fake_jwt(user_id="new-acct")
    mock_req.side_effect = [
        {"code": "x", "auth_url": "https://auth.test/x"},
        {"status": "complete", "token": new_token, "refresh_token": "r"},
    ]
    with patch("builtins.input", return_value="y"):
        cli.cmd_login(cli_args())
    cfg = config.load()
    assert cfg["account_id"] == "new-acct"
    # Old profile should be stashed
    assert "old-acct" in cfg.get("profiles", {})


@patch("webbrowser.open")
@patch("time.sleep")
@patch("methodproof.sync._request")
def test_login_timeout(mock_req, mock_sleep, mock_browser, cli_args, capsys):
    mock_req.side_effect = [
        {"code": "x", "auth_url": "https://auth.test/x"},
    ] + [Exception("pending")] * 60  # all polls fail
    cli.cmd_login(cli_args())
    assert "timed out" in capsys.readouterr().out
