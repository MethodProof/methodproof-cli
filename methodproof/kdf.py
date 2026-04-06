"""Key derivation from master secret — HKDF-SHA256 with versioned info strings."""

from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def derive_master(entropy: bytes) -> bytes:
    """128-bit entropy → 256-bit master secret."""
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=b"master-v1").derive(entropy)


def derive_db_key(master: bytes, account_id: str) -> bytes:
    """Master secret → AES-256 key for local DB field encryption."""
    return HKDF(
        algorithm=SHA256(), length=32,
        salt=account_id.encode(), info=b"local-db-v1",
    ).derive(master)


def derive_bind_key(master: bytes, account_id: str) -> bytes:
    """Master secret → HMAC key for session binding signatures."""
    return HKDF(
        algorithm=SHA256(), length=32,
        salt=account_id.encode(), info=b"session-bind-v1",
    ).derive(master)
