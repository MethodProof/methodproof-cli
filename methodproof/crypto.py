"""E2E encryption — AES-256-GCM with company-held keys."""

import hashlib
import os
from base64 import b64decode, b64encode

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None  # type: ignore[assignment, misc]

_NONCE_BYTES = 12
SENSITIVE_FIELDS = frozenset({"prompt_text", "response_text", "command", "output_snippet", "diff", "query"})


def _require_crypto() -> None:
    if AESGCM is None:
        raise RuntimeError("E2E encryption requires: pip install 'methodproof[e2e]'")


def fingerprint(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


def encrypt_field(plaintext: str, key: bytes) -> str:
    _require_crypto()
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return f"e2e:v1:{fingerprint(key)}:{b64encode(nonce + ciphertext).decode()}"


def decrypt_field(encrypted: str, key: bytes) -> str:
    _require_crypto()
    if not encrypted.startswith("e2e:v1:"):
        return encrypted
    parts = encrypted.split(":", 3)
    raw = b64decode(parts[3])
    nonce, ct = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, ct, None).decode()


def encrypt_metadata(metadata: dict, key: bytes) -> dict:
    for field in SENSITIVE_FIELDS:
        if field in metadata and isinstance(metadata[field], str):
            metadata[field] = encrypt_field(metadata[field], key)
    return metadata
