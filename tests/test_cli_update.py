"""Tests for CLI update and extension commands."""

import json
from unittest.mock import MagicMock, patch

import pytest

from methodproof import cli, config


# ── _get_current_version ──


def test_get_current_version():
    result = cli._get_current_version()
    assert isinstance(result, str)
    assert "." in result or result == "0.0.0"


# ── _check_pypi_version ──


@patch("urllib.request.urlopen")
def test_check_pypi_version_success(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"info": {"version": "1.2.3"}}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp
    assert cli._check_pypi_version() == "1.2.3"


@patch("urllib.request.urlopen", side_effect=Exception("offline"))
def test_check_pypi_version_failure(mock_urlopen):
    assert cli._check_pypi_version() is None


# ── cmd_update ──


def test_update_auto_on(cli_args, capsys):
    cli.cmd_update(cli_args(auto=True))
    cfg = config.load()
    assert cfg["auto_update"] is True
    assert "ON" in capsys.readouterr().out


def test_update_auto_off(cli_args, capsys):
    cfg = config.load()
    cfg["auto_update"] = True
    config.save(cfg)
    cli.cmd_update(cli_args(auto=False))
    cfg = config.load()
    assert cfg["auto_update"] is False
    assert "OFF" in capsys.readouterr().out


@patch("methodproof.cli._check_pypi_version", return_value=None)
def test_update_pypi_unreachable(mock_pypi, cli_args, capsys):
    cli.cmd_update(cli_args())
    assert "Could not reach PyPI" in capsys.readouterr().out


@patch("methodproof.cli._check_pypi_version", return_value="0.7.7")
@patch("methodproof.cli._get_current_version", return_value="0.7.7")
def test_update_already_current(mock_ver, mock_pypi, cli_args, capsys):
    cli.cmd_update(cli_args())
    assert "up to date" in capsys.readouterr().out


@patch("subprocess.run")
@patch("methodproof.cli._check_pypi_version", return_value="0.8.0")
@patch("methodproof.cli._get_current_version", return_value="0.7.7")
def test_update_runs_pip(mock_ver, mock_pypi, mock_run, cli_args, capsys):
    mock_run.return_value = MagicMock(returncode=0)
    cli.cmd_update(cli_args())
    mock_run.assert_called_once()
    assert "Updated" in capsys.readouterr().out


@patch("subprocess.run")
@patch("methodproof.cli._check_pypi_version", return_value="0.8.0")
@patch("methodproof.cli._get_current_version", return_value="0.7.7")
def test_update_pip_fails(mock_ver, mock_pypi, mock_run, cli_args, capsys):
    mock_run.return_value = MagicMock(returncode=1)
    cli.cmd_update(cli_args())
    assert "failed" in capsys.readouterr().out.lower()


# ── cmd_extension ──


@patch("webbrowser.open")
def test_extension_install(mock_browser, cli_args):
    cli.cmd_extension(cli_args(ext_cmd="install"))
    mock_browser.assert_called_once()


@patch("urllib.request.urlopen")
def test_extension_status_paired(mock_urlopen, cli_args, capsys):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"paired": True}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp
    cli.cmd_extension(cli_args(ext_cmd="status"))
    out = capsys.readouterr().out
    assert "paired" in out.lower() or "connected" in out.lower()


@patch("urllib.request.urlopen", side_effect=Exception("refused"))
def test_extension_status_not_running(mock_urlopen, cli_args, capsys):
    cli.cmd_extension(cli_args(ext_cmd="status"))
    out = capsys.readouterr().out
    assert "not running" in out.lower() or "no active" in out.lower()


def test_extension_no_subcmd(cli_args, capsys):
    cli.cmd_extension(cli_args(ext_cmd=None))
    out = capsys.readouterr().out
    assert "Usage" in out or "pair" in out
