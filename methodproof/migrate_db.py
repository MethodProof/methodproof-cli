"""Encrypt existing plaintext events in local DB after key setup."""

import json

from methodproof import store
from methodproof.crypto import SENSITIVE_FIELDS, encrypt_field


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
        meta = json.loads(row["metadata"])
        changed = False
        for field in SENSITIVE_FIELDS:
            val = meta.get(field)
            if isinstance(val, str) and val and not val.startswith("e2e:v1:"):
                meta[field] = encrypt_field(val, db_key)
                changed = True
        if changed:
            batch.append((json.dumps(meta), row["id"]))
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
