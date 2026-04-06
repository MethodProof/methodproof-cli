"""Event chain hashing and Ed25519 attestation signing."""

import hashlib
import json
from pathlib import Path
from typing import Any


def compute_event_hash(event: dict[str, Any], prev_hash: str, account_id: str = "") -> str:
    """SHA-256 chain link. Includes account_id when present (new format), omits for legacy."""
    metadata_hash = hashlib.sha256(
        json.dumps(event.get("metadata", {}), sort_keys=True, default=str).encode()
    ).hexdigest()
    if account_id:
        payload = f"{event['id']}:{account_id}:{event['type']}:{event['timestamp']}:{metadata_hash}:{prev_hash}"
    else:
        payload = f"{event['id']}:{event['type']}:{event['timestamp']}:{metadata_hash}:{prev_hash}"
    return hashlib.sha256(payload.encode()).hexdigest()


# ── Ed25519 keypair (requires `pip install methodproof[signing]`) ──

def _key_dir() -> Path:
    from methodproof import config
    return config.DIR


def has_keypair() -> bool:
    d = _key_dir()
    return (d / "signing.key").exists() and (d / "signing.pub").exists()


def generate_keypair() -> bytes:
    """Generate Ed25519 keypair, save to ~/.methodproof/, return public key PEM."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )
    key = Ed25519PrivateKey.generate()
    d = _key_dir()
    priv_path = d / "signing.key"
    pub_path = d / "signing.pub"
    priv_path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    from methodproof.config import secure_file
    secure_file(priv_path)
    pub_bytes = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    pub_path.write_bytes(pub_bytes)
    return pub_bytes


def get_public_key_pem() -> bytes:
    return (_key_dir() / "signing.pub").read_bytes()


def sign_attestation(
    session_id: str, root_hash: str, leaf_hash: str,
    event_count: int, cli_version: str, binary_hash: str,
) -> str:
    """Ed25519 sign the attestation payload. Returns base64-encoded signature."""
    from base64 import b64encode
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    payload = f"{session_id}:{root_hash}:{leaf_hash}:{event_count}:{cli_version}:{binary_hash}"
    key = load_pem_private_key((_key_dir() / "signing.key").read_bytes(), password=None)
    return b64encode(key.sign(payload.encode())).decode()


def compute_binary_hash() -> str:
    """SHA-256 of all .py files in the methodproof package (detects source modifications)."""
    import methodproof
    pkg_dir = Path(methodproof.__file__).parent
    h = hashlib.sha256()
    for f in sorted(pkg_dir.rglob("*.py")):
        h.update(f.read_bytes())
    return h.hexdigest()
