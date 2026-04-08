"""Tests for the CLI security system — hash chain, BIP39, KDF, keychain, encryption, binding, migration, lock."""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from methodproof import config, store
from methodproof.binding import compute_binding, compute_device_id
from methodproof.bip39 import entropy_to_phrase, phrase_to_entropy
from methodproof.crypto import SENSITIVE_FIELDS, decrypt_field, encrypt_field, encrypt_metadata
from methodproof.integrity import compute_event_hash
from methodproof.kdf import derive_bind_key, derive_db_key, derive_master
from methodproof.migrate_db import migrate_encrypt


# ── Fixtures ──


@pytest.fixture(autouse=True)
def tmp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(store, "_conn", None)
    store.init_db()
    return tmp_path


def _event(etype: str = "file_edit", meta: dict | None = None) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "type": etype,
        "timestamp": time.time(),
        "metadata": meta or {"path": "a.py"},
    }


# ── 1. Hash Chain ──


def test_hash_chain_with_account_id():
    e = _event()
    h = compute_event_hash(e, "genesis", account_id="acct-1")
    assert len(h) == 64 and h != "genesis"


def test_hash_chain_legacy_no_account_id():
    e = _event()
    h = compute_event_hash(e, "genesis", account_id="")
    assert len(h) == 64


def test_account_id_changes_hash():
    e = _event()
    h1 = compute_event_hash(e, "genesis", account_id="acct-1")
    h2 = compute_event_hash(e, "genesis", account_id="acct-2")
    assert h1 != h2


def test_chain_integrity():
    events = [_event() for _ in range(5)]
    prev = "genesis"
    hashes = []
    for e in events:
        prev = compute_event_hash(e, prev)
        hashes.append(prev)
    assert len(set(hashes)) == 5  # all unique


def test_tamper_detection():
    e = _event()
    h = compute_event_hash(e, "genesis")
    e["type"] = "terminal_cmd"  # tamper
    h2 = compute_event_hash(e, "genesis")
    assert h != h2


def test_prev_hash_matters():
    e = _event()
    h1 = compute_event_hash(e, "genesis")
    h2 = compute_event_hash(e, "different-prev")
    assert h1 != h2


# ── 2. BIP39 ──


def test_bip39_round_trip_random():
    for _ in range(100):
        entropy = os.urandom(16)
        phrase = entropy_to_phrase(entropy)
        assert phrase_to_entropy(phrase) == entropy


def test_bip39_known_vector():
    entropy = b"\x00" * 16
    phrase = entropy_to_phrase(entropy)
    assert len(phrase.split()) == 12
    assert phrase_to_entropy(phrase) == entropy


def test_bip39_bad_checksum():
    # Use fixed entropy so the checksum corruption is deterministic
    phrase = entropy_to_phrase(b"\x00" * 16)
    words = phrase.split()
    # Flip the last word to a word that changes the checksum bits
    words[-1] = "zone"
    with pytest.raises(ValueError, match="checksum"):
        phrase_to_entropy(" ".join(words))


def test_bip39_wrong_word_count():
    with pytest.raises(ValueError, match="12 words"):
        phrase_to_entropy("abandon ability able")


def test_bip39_unknown_word():
    with pytest.raises(ValueError, match="Unknown word"):
        phrase_to_entropy("abandon " * 11 + "zzzznotaword")


def test_bip39_wrong_entropy_length():
    with pytest.raises(ValueError, match="16 bytes"):
        entropy_to_phrase(b"\x00" * 8)


# ── 3. KDF ──


def test_kdf_deterministic():
    entropy = os.urandom(16)
    assert derive_master(entropy) == derive_master(entropy)


def test_kdf_different_accounts():
    master = derive_master(os.urandom(16))
    k1 = derive_db_key(master, "acct-1")
    k2 = derive_db_key(master, "acct-2")
    assert k1 != k2


def test_kdf_db_key_differs_from_bind_key():
    master = derive_master(os.urandom(16))
    assert derive_db_key(master, "x") != derive_bind_key(master, "x")


def test_kdf_output_length():
    master = derive_master(os.urandom(16))
    assert len(master) == 32
    assert len(derive_db_key(master, "a")) == 32
    assert len(derive_bind_key(master, "a")) == 32


# ── 4. Keychain ──


def test_keychain_store_load_delete(monkeypatch: pytest.MonkeyPatch):
    from methodproof import keychain
    monkeypatch.setattr(keychain, "_fallback_path", lambda: config.DIR / "master.key")
    # Force file fallback by making keyring import fail
    with patch.dict("sys.modules", {"keyring": None}):
        keychain.store_secret("acct-1", b"\xab" * 16)
        assert keychain.load_secret("acct-1") == b"\xab" * 16
        assert keychain.has_secret("acct-1")
        keychain.delete_secret("acct-1")
        assert not keychain.has_secret("acct-1")


def test_keychain_fallback_creates_file(monkeypatch: pytest.MonkeyPatch):
    from methodproof import keychain
    monkeypatch.setattr(keychain, "_fallback_path", lambda: config.DIR / "master.key")
    with patch.dict("sys.modules", {"keyring": None}):
        keychain.store_secret("acct-1", b"\xcd" * 16)
        assert (config.DIR / "master.key").exists()


def test_keychain_load_missing_returns_none(monkeypatch: pytest.MonkeyPatch):
    from methodproof import keychain
    monkeypatch.setattr(keychain, "_fallback_path", lambda: config.DIR / "master.key")
    with patch.dict("sys.modules", {"keyring": None}):
        assert keychain.load_secret("nonexistent") is None


# ── 5. Encryption ──


def test_encrypt_decrypt_round_trip():
    key = derive_db_key(derive_master(os.urandom(16)), "a")
    ct = encrypt_field("secret data", key)
    assert ct.startswith("e2e:v1:")
    assert decrypt_field(ct, key) == "secret data"


def test_decrypt_wrong_key_fails():
    k1 = derive_db_key(derive_master(os.urandom(16)), "a")
    k2 = derive_db_key(derive_master(os.urandom(16)), "b")
    ct = encrypt_field("secret", k1)
    with pytest.raises(Exception):
        decrypt_field(ct, k2)


def test_encrypt_metadata_covers_sensitive_fields():
    key = derive_db_key(derive_master(os.urandom(16)), "a")
    meta = {f: f"value-{f}" for f in SENSITIVE_FIELDS}
    meta["safe_field"] = "untouched"
    encrypted = encrypt_metadata(meta, key)
    for f in SENSITIVE_FIELDS:
        assert encrypted[f].startswith("e2e:v1:")
    assert encrypted["safe_field"] == "untouched"


def test_decrypt_plaintext_passthrough():
    key = os.urandom(32)
    assert decrypt_field("just plain text", key) == "just plain text"


# ── 6. Session Binding ──


def test_binding_deterministic():
    key = os.urandom(32)
    b1 = compute_binding(key, "s1", "a1", "d1", 1000.0)
    b2 = compute_binding(key, "s1", "a1", "d1", 1000.0)
    assert b1 == b2


def test_binding_different_inputs():
    key = os.urandom(32)
    b1 = compute_binding(key, "s1", "a1", "d1", 1000.0)
    b2 = compute_binding(key, "s2", "a1", "d1", 1000.0)
    assert b1 != b2


def test_device_id_deterministic():
    assert compute_device_id() == compute_device_id()


def test_device_id_length():
    assert len(compute_device_id()) == 16


# ── 7. DB Migration (plaintext -> encrypted) ──


def test_migrate_encrypts_plaintext():
    sid = uuid.uuid4().hex
    store.create_session(sid, "/tmp")
    store.insert_events(sid, [
        {"id": "e1", "type": "llm_prompt", "timestamp": 1.0,
         "metadata": {"prompt_text": "hello world"}},
    ])
    key = derive_db_key(derive_master(os.urandom(16)), "a")
    count = migrate_encrypt(key)
    assert count == 1
    row = store._db().execute("SELECT metadata FROM events WHERE id = 'e1'").fetchone()
    meta = store._decompress_meta(row["metadata"])
    assert "e2e:v1:" in meta["prompt_text"]


def test_migrate_idempotent():
    sid = uuid.uuid4().hex
    store.create_session(sid, "/tmp")
    store.insert_events(sid, [
        {"id": "e1", "type": "llm_prompt", "timestamp": 1.0,
         "metadata": {"prompt_text": "hello"}},
    ])
    key = derive_db_key(derive_master(os.urandom(16)), "a")
    assert migrate_encrypt(key) == 1
    assert migrate_encrypt(key) == 0  # already encrypted


def test_migrate_skips_non_sensitive():
    sid = uuid.uuid4().hex
    store.create_session(sid, "/tmp")
    store.insert_events(sid, [
        {"id": "e1", "type": "file_edit", "timestamp": 1.0,
         "metadata": {"path": "/a.py", "lines_added": 5}},
    ])
    key = derive_db_key(derive_master(os.urandom(16)), "a")
    assert migrate_encrypt(key) == 0


# ── 8. Lock / Purge ──


def test_lock_clears_keychain(monkeypatch: pytest.MonkeyPatch):
    from methodproof import keychain, lock as lock_mod
    monkeypatch.setattr(keychain, "_fallback_path", lambda: config.DIR / "master.key")
    # Prevent platform notification attempt
    monkeypatch.setattr(lock_mod.config, "load", lambda: {"token": ""})
    with patch.dict("sys.modules", {"keyring": None}):
        keychain.store_secret("acct-1", b"\xab" * 16)
        lock_mod.lock("acct-1")
        assert not keychain.has_secret("acct-1")


def test_purge_deletes_db(monkeypatch: pytest.MonkeyPatch):
    from methodproof import keychain, lock as lock_mod
    monkeypatch.setattr(keychain, "_fallback_path", lambda: config.DIR / "master.key")
    monkeypatch.setattr(lock_mod.config, "load", lambda: {"token": ""})
    store.reset_connection()  # release DB handle before purge
    with patch.dict("sys.modules", {"keyring": None}):
        keychain.store_secret("acct-1", b"\xab" * 16)
        lock_mod.lock("acct-1", purge=True)
        assert not config.DB_PATH.exists()


# ── 9. E2E Lifecycle ──


def test_e2e_session_lifecycle():
    entropy = os.urandom(16)
    account_id = "acct-lifecycle"
    master = derive_master(entropy)
    db_key = derive_db_key(master, account_id)
    bind_key = derive_bind_key(master, account_id)
    device_id = compute_device_id()
    sid = uuid.uuid4().hex
    binding = compute_binding(bind_key, sid, account_id, device_id, time.time())
    store.create_session(sid, "/tmp", account_id=account_id,
                         session_binding=binding, device_id=device_id)
    events = [_event(meta={"prompt_text": f"prompt-{i}"}) for i in range(3)]
    for e in events:
        e["metadata"] = encrypt_metadata(dict(e["metadata"]), db_key)
    store.insert_events(sid, events)
    prev = "genesis"
    hashes = []
    for e in events:
        prev = compute_event_hash(e, prev, account_id=account_id)
        hashes.append((e["id"], prev))
    store.insert_event_hashes(hashes)
    stored = store.get_event_hashes(sid)
    assert len(stored) == 3
    session = store.get_session(sid)
    assert session["account_id"] == account_id
    assert session["session_binding"] == binding


# ── 10. Plagiarism Resistance ──


def test_account_a_chain_fails_with_account_b():
    e = _event()
    h_a = compute_event_hash(e, "genesis", account_id="account-A")
    h_b = compute_event_hash(e, "genesis", account_id="account-B")
    assert h_a != h_b


def test_binding_wrong_account_mismatches():
    key = os.urandom(32)
    b_a = compute_binding(key, "s1", "account-A", "d1", 1000.0)
    b_b = compute_binding(key, "s1", "account-B", "d1", 1000.0)
    assert b_a != b_b


def test_cross_account_chain_cannot_verify():
    events = [_event() for _ in range(3)]
    prev_a = "genesis"
    hashes_a = []
    for e in events:
        prev_a = compute_event_hash(e, prev_a, account_id="A")
        hashes_a.append(prev_a)
    # Replay same events with account B
    prev_b = "genesis"
    for i, e in enumerate(events):
        prev_b = compute_event_hash(e, prev_b, account_id="B")
        assert prev_b != hashes_a[i]
