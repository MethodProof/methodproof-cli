"""Tests for CLI share commands — push, publish, tag, delete, review, view."""

import json
from unittest.mock import patch

import pytest

from methodproof import cli, config, store


# ── cmd_push ──


def test_push_not_logged_in(cli_args):
    with pytest.raises(SystemExit):
        cli.cmd_push(cli_args())


@patch("methodproof.sync.push", return_value="remote-abc")
@patch("methodproof.sync.sync_research_consent")
def test_push_happy_path(mock_consent, mock_push, logged_in_cfg, make_session, cli_args, capsys):
    logged_in_cfg()
    sid, _ = make_session()
    cli.cmd_push(cli_args(session_id=sid))
    out = capsys.readouterr().out
    assert "remote-abc" in out or "Pushed" in out
    mock_push.assert_called_once()


@patch("methodproof.sync.sync_research_consent")
def test_push_no_sessions(mock_consent, logged_in_cfg, cli_args):
    logged_in_cfg()
    with pytest.raises(SystemExit):
        cli.cmd_push(cli_args())


# ── cmd_tag ──


def test_tag_adds_tags(make_session, cli_args, capsys):
    sid, _ = make_session()
    cli.cmd_tag(cli_args(session_id=sid[:8], tags="python,ai"))
    s = store.get_session(sid)
    tags = json.loads(s["tags"])
    assert "python" in tags
    assert "ai" in tags


def test_tag_merges_existing(make_session, cli_args):
    sid, _ = make_session()
    store.update_tags(sid, ["existing"])
    cli.cmd_tag(cli_args(session_id=sid[:8], tags="new"))
    s = store.get_session(sid)
    tags = json.loads(s["tags"])
    assert "existing" in tags
    assert "new" in tags


# ── cmd_delete ──


def test_delete_with_confirmation(make_session, cli_args, capsys):
    sid, _ = make_session()
    with patch("builtins.input", return_value="y"):
        cli.cmd_delete(cli_args(session_id=sid[:8]))
    assert store.get_session(sid) is None
    assert "Deleted" in capsys.readouterr().out


def test_delete_cancelled(make_session, cli_args, capsys):
    sid, _ = make_session()
    with patch("builtins.input", return_value="n"):
        cli.cmd_delete(cli_args(session_id=sid[:8]))
    assert store.get_session(sid) is not None
    assert "Aborted" in capsys.readouterr().out


def test_delete_force(make_session, cli_args, capsys):
    sid, _ = make_session()
    cli.cmd_delete(cli_args(session_id=sid[:8], force=True))
    assert store.get_session(sid) is None


# ── cmd_review ──


def test_review_no_events(cli_args, capsys):
    sid = "deadbeef" * 4
    store.create_session(sid, "/tmp")
    store.complete_session(sid)
    cli.cmd_review(cli_args(session_id=sid))
    assert "No events" in capsys.readouterr().out


def test_review_shows_breakdown(make_session, cli_args, capsys):
    sid, _ = make_session(n_events=5)
    cli.cmd_review(cli_args(session_id=sid))
    out = capsys.readouterr().out
    assert "5" in out
    assert "events" in out
    assert "fields:" in out


# ── cmd_view ──


@patch("methodproof.viewer.view")
def test_view_delegates(mock_view, make_session, cli_args):
    sid, _ = make_session()
    cli.cmd_view(cli_args(session_id=sid))
    mock_view.assert_called_once()
    assert mock_view.call_args[0][0]["id"] == sid


# ── cmd_publish ──


@patch("methodproof.sync.push", return_value="remote-pub")
@patch("methodproof.sync.sync_metadata")
@patch("methodproof.sync.sync_research_consent")
def test_publish_unsynced_pushes_first(mock_consent, mock_meta, mock_push,
                                        logged_in_cfg, make_session, cli_args, capsys):
    logged_in_cfg()
    sid, _ = make_session()
    cli.cmd_publish(cli_args(session_id=sid))
    mock_push.assert_called_once()
    s = store.get_session(sid)
    assert s["visibility"] == "public"


@patch("methodproof.sync.sync_metadata")
@patch("methodproof.sync.sync_research_consent")
def test_publish_already_synced(mock_consent, mock_meta, logged_in_cfg, make_session, cli_args, capsys):
    logged_in_cfg()
    sid, _ = make_session()
    store.mark_synced(sid, "remote-existing")
    cli.cmd_publish(cli_args(session_id=sid))
    mock_meta.assert_called_once()
    s = store.get_session(sid)
    assert s["visibility"] == "public"
