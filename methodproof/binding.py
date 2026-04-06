"""Session binding — HMAC ties sessions to account + device."""

import hashlib
import hmac
import os
import platform
import sys
import time as _time


def compute_binding(bind_key: bytes, session_id: str, account_id: str,
                    device_id: str, created_at: float) -> str:
    """HMAC-SHA256 binding signature for a session."""
    msg = f"{session_id}:{account_id}:{device_id}:{created_at}".encode()
    return hmac.new(bind_key, msg, hashlib.sha256).hexdigest()


def compute_device_id() -> str:
    """Deterministic device fingerprint — hash of stable machine attributes."""
    parts = [
        platform.node(),
        platform.system(),
        platform.machine(),
        platform.python_version(),
        _time.tzname[0],
        str(os.cpu_count()),
    ]
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:16]
