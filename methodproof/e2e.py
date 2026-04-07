"""E2E encryption mode — personal key management and session release."""

import argparse
import getpass
import hashlib
import json
import os
import sys
from base64 import b64decode, b64encode

from methodproof import config, store


_RESET = "\033[0m"


def print_e2e_intro() -> None:
    """Show E2E mode introduction."""
    print("  ┌─────────────────────────────────────────────────────┐")
    print("  │  E2E Mode — personal encryption                     │")
    print("  └─────────────────────────────────────────────────────┘")
    print("  When enabled, session content (prompts, responses, diffs,")
    print("  terminal output) is encrypted with a key only you hold.")
    print("  The MethodProof platform cannot read encrypted fields.")
    print()
    print("  Tradeoff: narration and AI features are unavailable for")
    print("  encrypted sessions. You can release individual sessions")
    print("  from E2E later to enable narration.")
    print()
    print("  Structural data (graph, timing, threads, scoring) is")
    print("  always available regardless of E2E status.")
    print()
    print("  Try it:  mp start --e2e")
    print("  Toggle:  mp e2e on / off / status")
    print()


def _prompt_passphrase() -> str:
    """Prompt for a passphrase (12+ chars, confirmed)."""
    while True:
        pp = getpass.getpass("Passphrase (12+ characters): ")
        if len(pp) < 12:
            print("Passphrase must be at least 12 characters.")
            continue
        confirm = getpass.getpass("Confirm passphrase: ")
        if pp != confirm:
            print("Passphrases do not match.")
            continue
        return pp


def _wrap_key(raw_key: bytes, passphrase: str) -> tuple[bytes, bytes]:
    """Derive wrapping key from passphrase, encrypt raw_key. Returns (salt, blob)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(16)
    wrapping_key = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, 600_000, dklen=32)
    nonce = os.urandom(12)
    ciphertext = AESGCM(wrapping_key).encrypt(nonce, raw_key, None)
    blob = nonce + ciphertext
    return salt, blob


def _unwrap_key(blob_b64: str, salt_hex: str, passphrase: str, iterations: int = 600_000) -> bytes:
    """Decrypt recovery blob to recover raw key."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = bytes.fromhex(salt_hex)
    wrapping_key = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, iterations, dklen=32)
    raw = b64decode(blob_b64)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(wrapping_key).decrypt(nonce, ct, None)


def _setup_key(cfg: dict) -> None:
    """First-time key generation and registration."""
    from methodproof import keychain
    from methodproof.crypto import fingerprint
    from methodproof.sync import _request

    account_id = cfg.get("account_id", "")
    token = cfg.get("token", "")
    api_url = cfg.get("api_url", "")
    if not token or not account_id:
        print("E2E requires login. Run `methodproof login` first.")
        sys.exit(1)

    print("E2E Mode — Personal Encryption\n")
    print("A 256-bit key will be generated and stored in your OS keychain.")
    print("You will set a recovery passphrase in case you lose keychain access.\n")

    answer = input("Enable E2E mode? [y/N] ").strip().lower()
    if answer != "y":
        print("E2E mode not enabled.")
        return

    raw_key = os.urandom(32)
    fp = fingerprint(raw_key)
    passphrase = _prompt_passphrase()
    salt, blob = _wrap_key(raw_key, passphrase)

    # Store raw key in keychain
    keychain.store_secret(f"e2e:{account_id}", raw_key)

    # Register with platform
    _request("POST", "/personal/e2e-keys", api_url, token, {
        "key_fingerprint": fp,
        "recovery_blob": b64encode(blob).decode(),
        "recovery_salt": salt.hex(),
        "recovery_params": {"alg": "pbkdf2-sha256", "iterations": 600_000},
    })

    cfg["e2e_mode"] = True
    cfg["e2e_fingerprint"] = fp
    config.save(cfg)

    # Passphrase warning box
    W = "\033[1;97m"
    Y = "\033[93m"
    D = "\033[90m"
    R = _RESET
    print(f"\n  ┌──────────────────────────────────────────────────┐")
    print(f"  │  {W}RECOVERY PASSPHRASE — REMEMBER THIS{R}             │")
    print(f"  │                                                  │")
    print(f"  │  {D}Your key is stored in the OS keychain.{R}          │")
    print(f"  │  {D}If you lose keychain access, recover with:{R}      │")
    print(f"  │  {Y}  mp e2e recover{R}                                │")
    print(f"  │                                                  │")
    print(f"  │  {D}Without the passphrase, encrypted sessions{R}      │")
    print(f"  │  {D}cannot be recovered.{R}                            │")
    print(f"  └──────────────────────────────────────────────────┘\n")
    print("E2E mode ON. Content will be encrypted with your personal key.")
    print("Run `methodproof start --e2e` to begin an encrypted session.\n")


def _cmd_on(cfg: dict) -> None:
    """Enable E2E mode."""
    if cfg.get("e2e_fingerprint"):
        cfg["e2e_mode"] = True
        config.save(cfg)
        print("E2E mode ON.")
    else:
        _setup_key(cfg)


def _cmd_off(cfg: dict) -> None:
    """Disable E2E mode."""
    cfg["e2e_mode"] = False
    config.save(cfg)
    print("E2E mode OFF. Sessions will use standard encryption.")


def _cmd_status(cfg: dict) -> None:
    """Show E2E mode status."""
    enabled = cfg.get("e2e_mode", False)
    fp = cfg.get("e2e_fingerprint", "")
    if enabled:
        print(f"E2E mode: ON (fingerprint: {fp})")
    else:
        print("E2E mode: OFF")
        if fp:
            print(f"  Key registered (fingerprint: {fp}) but mode is disabled.")
            print("  Enable with: methodproof e2e on")
            return
        print("  No key registered. Enable with: methodproof e2e on")
        return

    # Check keychain
    account_id = cfg.get("account_id", "")
    if account_id:
        from methodproof.keychain import has_secret
        if has_secret(f"e2e:{account_id}"):
            print("  Key: present in OS keychain")
        else:
            print("  Key: NOT in keychain (run `mp e2e recover` to restore)")


def _cmd_recover(cfg: dict) -> None:
    """Recover E2E key from platform-stored recovery blob."""
    from methodproof import keychain
    from methodproof.crypto import fingerprint
    from methodproof.sync import _request

    token = cfg.get("token", "")
    api_url = cfg.get("api_url", "")
    account_id = cfg.get("account_id", "")
    if not token:
        print("Recovery requires login. Run `methodproof login` first.")
        sys.exit(1)

    # List keys to find the active fingerprint, then fetch recovery data
    keys = _request("GET", "/personal/e2e-keys", api_url, token)
    if not isinstance(keys, list) or not keys:
        print("No E2E keys registered on your account.")
        return

    active = [k for k in keys if not k.get("revoked_at")]
    if not active:
        print("No active E2E keys found.")
        return

    fp = active[0]["fingerprint"]
    recovery = _request("GET", f"/personal/e2e-keys/{fp}/recovery", api_url, token)
    blob_b64 = recovery["recovery_blob"]
    salt_hex = recovery["recovery_salt"]
    params = recovery.get("recovery_params", {})
    iterations = params.get("iterations", 600_000)

    print(f"Recovering key (fingerprint: {fp})\n")
    passphrase = getpass.getpass("Recovery passphrase: ")

    try:
        raw_key = _unwrap_key(blob_b64, salt_hex, passphrase, iterations)
    except Exception:
        print("Decryption failed. Wrong passphrase or corrupted recovery data.")
        sys.exit(1)

    if fingerprint(raw_key) != fp:
        print("Key fingerprint mismatch. Recovery data may be corrupted.")
        sys.exit(1)

    keychain.store_secret(f"e2e:{account_id}", raw_key)
    cfg["e2e_fingerprint"] = fp
    config.save(cfg)
    print(f"Key recovered and stored in OS keychain (fingerprint: {fp}).")


def _cmd_release(cfg: dict, session_id: str) -> None:
    """Release a session from E2E encryption."""
    from methodproof import keychain
    from methodproof.crypto import decrypt_field, SENSITIVE_FIELDS
    from methodproof.sync import _request

    token = cfg.get("token", "")
    api_url = cfg.get("api_url", "")
    account_id = cfg.get("account_id", "")
    if not token:
        print("Release requires login. Run `methodproof login` first.")
        sys.exit(1)

    e2e_key = keychain.load_secret(f"e2e:{account_id}")
    if not e2e_key:
        print("E2E key not found in keychain. Run `mp e2e recover` first.")
        sys.exit(1)

    events = store.get_events(session_id)
    if not events:
        print(f"No events found for session {session_id}.")
        sys.exit(1)

    decrypted_events = []
    for ev in events:
        meta = json.loads(ev.get("metadata", "{}"))
        has_encrypted = False
        for field in SENSITIVE_FIELDS:
            val = meta.get(field, "")
            if isinstance(val, str) and val.startswith("e2e:v1:"):
                meta[field] = decrypt_field(val, e2e_key)
                has_encrypted = True
        if has_encrypted:
            decrypted_events.append({"event_id": ev["id"], "metadata": meta})

    if not decrypted_events:
        print("No encrypted fields found in this session.")
        return

    # Resolve remote_id
    sessions = store.list_sessions()
    remote_id = None
    for s in sessions:
        if s["id"] == session_id or (s.get("remote_id") and s["id"].startswith(session_id)):
            remote_id = s.get("remote_id")
            session_id = s["id"]
            break

    if not remote_id:
        print("Session not synced to platform. Push first with `mp push`.")
        sys.exit(1)

    _request("POST", f"/personal/sessions/{remote_id}/release-e2e", api_url, token,
             {"events": decrypted_events})
    print(f"Session released ({len(decrypted_events)} events decrypted).")
    print("Narration will be generated shortly.")


def cmd_e2e(args: argparse.Namespace) -> None:
    """E2E encryption mode — personal key management."""
    subcmd = getattr(args, "e2e_cmd", None)
    cfg = config.load()

    if subcmd == "on":
        _cmd_on(cfg)
    elif subcmd == "off":
        _cmd_off(cfg)
    elif subcmd == "status":
        _cmd_status(cfg)
    elif subcmd == "recover":
        _cmd_recover(cfg)
    elif subcmd == "release":
        session_id = getattr(args, "session_id", "")
        if not session_id:
            print("Usage: methodproof e2e release <session-id>")
            sys.exit(1)
        _cmd_release(cfg, session_id)
    else:
        print("Usage: methodproof e2e [on|off|status|recover|release <session-id>]")
