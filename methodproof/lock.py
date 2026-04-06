"""Lock/purge — destroy local key access, optionally delete all data."""

import sys

from methodproof import config, store


def lock(account_id: str, purge: bool = False) -> None:
    """Destroy master secret from keychain. Optionally delete DB entirely."""
    from methodproof.keychain import delete_secret
    delete_secret(account_id)

    if purge:
        import shutil
        if config.DB_PATH.exists():
            config.DB_PATH.unlink()
            # Clean up WAL/SHM files
            for suffix in (".db-wal", ".db-shm"):
                p = config.DB_PATH.with_suffix(suffix)
                if p.exists():
                    p.unlink()
        print("  Database deleted.")
    else:
        print("  Master key destroyed. Encrypted fields are now inaccessible.")
        print("  Structural metadata (types, timestamps, paths) remains.")
        print("  Restore with: mp login (enter recovery phrase)")

    # Notify platform (best-effort)
    cfg = config.load()
    if cfg.get("token"):
        try:
            from methodproof.sync import _request
            from methodproof.binding import compute_device_id
            _request("POST", "/personal/lock-event", cfg["api_url"], cfg["token"],
                     {"device_id": compute_device_id(), "purged": purge})
        except Exception:
            pass

    # Clear master key fingerprint from config
    cfg["master_key_fingerprint"] = ""
    config.save(cfg)
