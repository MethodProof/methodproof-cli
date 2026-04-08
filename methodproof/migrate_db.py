"""Encrypt existing plaintext events in local DB after key setup."""

from methodproof import store
from methodproof.crypto import SENSITIVE_FIELDS, encrypt_field
from methodproof.store import _compress_meta, _decompress_meta


def migrate_encrypt(db_key: bytes) -> int:
    """Encrypt plaintext sensitive fields in all events. Returns count encrypted."""
    db = store._db()
    rows = db.execute(
        "SELECT id, metadata FROM events ORDER BY timestamp"
    ).fetchall()
    if not rows:
        return 0

    encrypted = 0
    batch = []
    for row in rows:
        meta = _decompress_meta(row["metadata"])
        changed = False
        for field in SENSITIVE_FIELDS:
            val = meta.get(field)
            if isinstance(val, str) and val and not val.startswith("e2e:v1:"):
                meta[field] = encrypt_field(val, db_key)
                changed = True
        if changed:
            batch.append((_compress_meta(meta), row["id"]))
            encrypted += 1
        if len(batch) >= 500:
            _flush_batch(db, batch)
            batch = []

    if batch:
        _flush_batch(db, batch)
    return encrypted


def _flush_batch(db, batch: list[tuple[str, str]]) -> None:
    db.executemany("UPDATE events SET metadata = ? WHERE id = ?", batch)
    db.commit()
