"""Tests for multi-account profile switching."""

import json
from pathlib import Path

import pytest

from methodproof import config


# ── Fixtures ──


@pytest.fixture(autouse=True)
def tmp_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    # Write defaults to disk so load() parses JSON — avoids shared refs with _DEFAULTS
    (tmp_path / "config.json").write_text(json.dumps(dict(config._DEFAULTS), indent=2))
    return tmp_path


def _make_cfg(**overrides) -> dict:
    """Build a config dict with defaults + overrides, then save it."""
    cfg = config.load()
    cfg.update(overrides)
    config.save(cfg)
    return cfg


# ── save_active_profile ──


def test_save_active_profile_stores_all_profile_keys():
    cfg = _make_cfg(account_id="aaa-111", token="tok-a", email="a@test.com")
    config.save_active_profile(cfg)
    reloaded = config.load()
    assert "aaa-111" in reloaded["profiles"]
    p = reloaded["profiles"]["aaa-111"]
    for k in config._PROFILE_KEYS:
        assert k in p


def test_save_active_profile_noop_without_account_id():
    cfg = _make_cfg(account_id="", token="tok-orphan")
    config.save_active_profile(cfg)
    reloaded = config.load()
    assert reloaded["profiles"] == {}


def test_save_active_profile_overwrites_stale_entry():
    cfg = _make_cfg(account_id="aaa-111", token="old-token")
    config.save_active_profile(cfg)
    cfg["token"] = "new-token"
    config.save_active_profile(cfg)
    reloaded = config.load()
    assert reloaded["profiles"]["aaa-111"]["token"] == "new-token"


# ── restore_profile ──


def test_restore_swaps_active_to_target():
    cfg = _make_cfg(account_id="aaa-111", token="tok-a", email="a@test.com")
    config.save_active_profile(cfg)
    cfg["account_id"] = "bbb-222"
    cfg["token"] = "tok-b"
    cfg["email"] = "b@test.com"
    config.save_active_profile(cfg)
    config.save(cfg)

    ok = config.restore_profile(cfg, "aaa-111")
    assert ok
    assert cfg["account_id"] == "aaa-111"
    assert cfg["token"] == "tok-a"
    assert cfg["email"] == "a@test.com"


def test_restore_stashes_current_before_swapping():
    cfg = _make_cfg(account_id="aaa-111", token="tok-a")
    config.save_active_profile(cfg)
    cfg["account_id"] = "bbb-222"
    cfg["token"] = "tok-b"
    config.save_active_profile(cfg)
    config.save(cfg)

    config.restore_profile(cfg, "aaa-111")
    reloaded = config.load()
    assert reloaded["profiles"]["bbb-222"]["token"] == "tok-b"


def test_restore_returns_false_for_unknown_profile():
    cfg = _make_cfg(account_id="aaa-111", token="tok-a")
    assert config.restore_profile(cfg, "nonexistent") is False


def test_restore_persists_to_disk():
    cfg = _make_cfg(account_id="aaa-111", token="tok-a", email="a@test.com")
    config.save_active_profile(cfg)
    cfg["account_id"] = "bbb-222"
    cfg["token"] = "tok-b"
    config.save_active_profile(cfg)
    config.save(cfg)

    config.restore_profile(cfg, "aaa-111")
    reloaded = config.load()
    assert reloaded["account_id"] == "aaa-111"
    assert reloaded["token"] == "tok-a"


# ── list_profiles ──


def test_list_profiles_empty_when_no_accounts():
    cfg = _make_cfg()
    assert config.list_profiles(cfg) == []


def test_list_profiles_includes_unsaved_active():
    cfg = _make_cfg(account_id="aaa-111", email="a@test.com")
    result = config.list_profiles(cfg)
    assert len(result) == 1
    assert result[0]["active"] is True
    assert result[0]["account_id"] == "aaa-111"


def test_list_profiles_marks_active_correctly():
    cfg = _make_cfg(account_id="aaa-111", token="tok-a")
    config.save_active_profile(cfg)
    cfg["account_id"] = "bbb-222"
    cfg["token"] = "tok-b"
    config.save_active_profile(cfg)
    config.save(cfg)

    result = config.list_profiles(cfg)
    active = [p for p in result if p["active"]]
    inactive = [p for p in result if not p["active"]]
    assert len(active) == 1
    assert active[0]["account_id"] == "bbb-222"
    assert len(inactive) == 1
    assert inactive[0]["account_id"] == "aaa-111"


def test_list_profiles_multiple_accounts():
    cfg = _make_cfg(account_id="aaa-111", token="tok-a")
    config.save_active_profile(cfg)
    cfg["account_id"] = "bbb-222"
    cfg["token"] = "tok-b"
    config.save_active_profile(cfg)
    cfg["account_id"] = "ccc-333"
    cfg["token"] = "tok-c"
    config.save_active_profile(cfg)
    config.save(cfg)

    assert len(config.list_profiles(cfg)) == 3


# ── find_profile ──


def test_find_by_exact_email():
    cfg = _make_cfg(account_id="aaa-111", email="a@test.com")
    config.save_active_profile(cfg)
    assert config.find_profile(cfg, "a@test.com") == "aaa-111"


def test_find_by_email_case_insensitive():
    cfg = _make_cfg(account_id="aaa-111", email="Alice@Test.com")
    config.save_active_profile(cfg)
    assert config.find_profile(cfg, "alice@test.com") == "aaa-111"


def test_find_by_account_id_prefix():
    cfg = _make_cfg(account_id="aaa-111-full-uuid")
    config.save_active_profile(cfg)
    assert config.find_profile(cfg, "aaa-111") == "aaa-111-full-uuid"


def test_find_returns_none_for_no_match():
    cfg = _make_cfg(account_id="aaa-111")
    config.save_active_profile(cfg)
    assert config.find_profile(cfg, "zzz") is None


def test_find_strips_whitespace():
    cfg = _make_cfg(account_id="aaa-111", email="a@test.com")
    config.save_active_profile(cfg)
    assert config.find_profile(cfg, "  a@test.com  ") == "aaa-111"


# ── Round-trip: login → switch → switch back ──


def test_full_swap_roundtrip():
    """Simulate: login as A, login as B, switch back to A, verify both intact."""
    cfg = _make_cfg(
        account_id="user-a", token="tok-a", email="a@mp.com",
        journal_mode=True, journal_credits=5,
    )
    config.save_active_profile(cfg)

    # "Login" as B
    cfg["account_id"] = "user-b"
    cfg["token"] = "tok-b"
    cfg["email"] = "b@mp.com"
    cfg["journal_mode"] = False
    cfg["journal_credits"] = 2
    config.save_active_profile(cfg)
    config.save(cfg)

    # Switch to A
    config.restore_profile(cfg, "user-a")
    assert cfg["token"] == "tok-a"
    assert cfg["journal_mode"] is True
    assert cfg["journal_credits"] == 5

    # Switch back to B
    config.restore_profile(cfg, "user-b")
    assert cfg["token"] == "tok-b"
    assert cfg["journal_mode"] is False
    assert cfg["journal_credits"] == 2


def test_swap_preserves_device_level_settings():
    """Consent and capture settings are device-level, not swapped."""
    cfg = _make_cfg(account_id="user-a", token="tok-a")
    cfg["capture"]["music"] = False
    config.save(cfg)
    config.save_active_profile(cfg)

    cfg["account_id"] = "user-b"
    cfg["token"] = "tok-b"
    config.save_active_profile(cfg)
    config.save(cfg)

    config.restore_profile(cfg, "user-a")
    reloaded = config.load()
    assert reloaded["capture"]["music"] is False  # device setting unchanged


def test_e2e_state_swaps_with_profile():
    """E2E mode and fingerprint are per-account."""
    cfg = _make_cfg(
        account_id="user-a", token="tok-a",
        e2e_mode=True, e2e_fingerprint="fp-aaa",
    )
    config.save_active_profile(cfg)

    cfg["account_id"] = "user-b"
    cfg["token"] = "tok-b"
    cfg["e2e_mode"] = False
    cfg["e2e_fingerprint"] = ""
    config.save_active_profile(cfg)
    config.save(cfg)

    config.restore_profile(cfg, "user-a")
    assert cfg["e2e_mode"] is True
    assert cfg["e2e_fingerprint"] == "fp-aaa"

    config.restore_profile(cfg, "user-b")
    assert cfg["e2e_mode"] is False
    assert cfg["e2e_fingerprint"] == ""
