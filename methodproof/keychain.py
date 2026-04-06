"""OS keychain storage for master secret — macOS Keychain, Linux secret-service, Windows Credential Manager."""

import sys
from pathlib import Path

_SERVICE = "methodproof"
_FALLBACK_WARNING = (
    "  No OS keychain available. Master secret stored as file (owner-only permissions).\n"
    "  For better security, install a keyring backend (e.g., gnome-keyring).\n"
)


def _fallback_path() -> Path:
    from methodproof import config
    return config.DIR / "master.key"


def store_secret(account_id: str, secret: bytes) -> None:
    """Store master secret in OS keychain, or fall back to file."""
    try:
        import keyring
        keyring.set_password(_SERVICE, account_id, secret.hex())
    except Exception:
        _store_file(secret)
        sys.stderr.write(_FALLBACK_WARNING)


def load_secret(account_id: str) -> bytes | None:
    """Load master secret from OS keychain or fallback file."""
    try:
        import keyring
        val = keyring.get_password(_SERVICE, account_id)
        if val:
            return bytes.fromhex(val)
    except Exception as exc:
        sys.stderr.write(f"keychain.load_failed account={account_id} error={exc}\n")
    return _load_file()


def delete_secret(account_id: str) -> None:
    """Remove master secret from keychain and fallback file."""
    try:
        import keyring
        keyring.delete_password(_SERVICE, account_id)
    except Exception as exc:
        sys.stderr.write(f"keychain.delete_failed account={account_id} error={exc}\n")
    path = _fallback_path()
    if path.exists():
        path.unlink()


def has_secret(account_id: str) -> bool:
    return load_secret(account_id) is not None


def _store_file(secret: bytes) -> None:
    from methodproof.config import ensure_dirs, secure_file
    ensure_dirs()
    path = _fallback_path()
    path.write_text(secret.hex())
    secure_file(path)


def _load_file() -> bytes | None:
    path = _fallback_path()
    if not path.exists():
        return None
    try:
        return bytes.fromhex(path.read_text().strip())
    except (ValueError, OSError):
        return None
