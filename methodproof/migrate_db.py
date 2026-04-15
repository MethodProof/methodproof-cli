"""Encrypt existing plaintext events in local DB after key setup.

Two layers:
- `migrate_encrypt` — field-level AES on six sensitive metadata keys.
- `migrate_to_sqlcipher` — whole-database SQLCipher encryption via the
  `sqlcipher_export()` recipe. Runs once on first login.
"""

import os

from methodproof import config, store
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


class DaemonActiveError(RuntimeError):
    """Raised when migrate_to_sqlcipher is called while the recording daemon
    is still running. The daemon holds an FD on the original DB file; renaming
    it out from under the daemon causes WAL/SHM file collisions and silent
    data loss for the active session. Caller must stop the daemon first."""


def _daemon_alive() -> bool:
    """True if a recording daemon is running. Mirrors cli._is_daemon_alive
    but lives here to avoid a circular import."""
    pidfile = config.DIR / "methodproof.pid"
    if not pidfile.exists():
        return False
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError, OSError):
        return False
    try:
        import subprocess
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "args="], text=True).strip()
        return "methodproof" in out
    except Exception:
        return False


def migrate_to_sqlcipher(db_key: bytes) -> bool:
    """Re-encrypt the entire local DB with SQLCipher using `db_key`.

    Idempotent — returns False if the DB is already encrypted (sentinel file
    present). On success, leaves a `.plaintext.bak` file alongside the new
    encrypted DB so a failed conversion is recoverable, and writes a
    `.encrypted` sentinel so future opens require the key.

    Raises `DaemonActiveError` if the recording daemon is still running.
    Callers should `mp stop` first.
    """
    from sqlcipher3 import dbapi2 as sqlite3

    flag = store._encrypted_flag_path()
    if flag.exists():
        return False

    if _daemon_alive():
        raise DaemonActiveError(
            "recording daemon is active — run `mp stop` before encrypting "
            "the local database (the daemon holds file descriptors that "
            "would conflict with SQLCipher's WAL files)"
        )

    db_path = config.DB_PATH
    if not db_path.exists():
        # Nothing to migrate — first run with no DB yet. Just mark as encrypted
        # so the next _db() call opens fresh in encrypted mode.
        store.set_db_key(db_key)
        flag.touch()
        return True

    store.reset_connection()

    target = db_path.with_suffix(".db.encrypting")
    if target.exists():
        target.unlink()

    src = sqlite3.connect(str(db_path))
    try:
        src.execute(f"ATTACH DATABASE '{target}' AS encrypted KEY \"x'{db_key.hex()}'\"")
        src.execute("SELECT sqlcipher_export('encrypted')")

        # Sanity-check row counts table-by-table
        tables = [
            r[0] for r in src.execute(
                "SELECT name FROM main.sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for name in tables:
            src_count = src.execute(f"SELECT count(*) FROM main.{name}").fetchone()[0]
            dst_count = src.execute(f"SELECT count(*) FROM encrypted.{name}").fetchone()[0]
            if src_count != dst_count:
                src.execute("DETACH DATABASE encrypted")
                src.close()
                target.unlink(missing_ok=True)
                raise RuntimeError(
                    f"sqlcipher migration row-count mismatch on {name}: "
                    f"src={src_count} dst={dst_count}"
                )

        src.execute("DETACH DATABASE encrypted")
    finally:
        src.close()

    # Atomic swap: original → .plaintext.bak, encrypting → original
    bak = db_path.with_suffix(".db.plaintext.bak")
    if bak.exists():
        bak.unlink()
    os.rename(db_path, bak)
    os.rename(target, db_path)

    # Clean up WAL/shm artifacts from the old plaintext file (they belong to
    # the now-renamed .plaintext.bak and would confuse SQLite if left alongside
    # the new encrypted DB under the original name).
    for suffix in ("-wal", "-shm"):
        leftover = db_path.parent / (db_path.name + suffix)
        if leftover.exists():
            leftover.unlink()

    flag.touch()
    store.set_db_key(db_key)
    return True
