"""Local proxy mode — opt-in mitmproxy for capturing AI API traffic.

Security: Requires explicit consent. Only decodes AI API domains.
Strips credentials. Events flow through standard consent gates.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from methodproof import config

PROXY_PORT = 8080
PID_FILE = config.DIR / "proxy.pid"
CERT_DIR = config.DIR / "proxy-certs"
LOG_FILE = config.DIR / "proxy.log"

_CONSENT_KEY = "proxy_consent"
_CONSENT_TEXT = """
MethodProof Local Proxy — Deep Capture Mode

This starts a local HTTP proxy that intercepts AI API traffic to capture
prompt and completion data from ANY tool on your machine.

What it captures:
  • Prompts and completions from AI APIs (OpenAI, Anthropic, Google, etc.)
  • Model names, token counts, latency
  • Only domains classified as AI APIs — all other traffic passes through

What it does NOT capture:
  • Credentials (API keys, auth headers are stripped)
  • Non-AI traffic (banking, email, social media)
  • Anything if ai_prompts/ai_responses consent is disabled

Requirements:
  • Install the proxy CA certificate (run: methodproof proxy cert)
  • Configure your tools to use http://localhost:8080 as HTTP proxy

All captured data is subject to your existing consent settings.
"""


def _is_consented() -> bool:
    cfg = config.load()
    return cfg.get(_CONSENT_KEY, False) is True


def _set_consent(value: bool) -> None:
    cfg = config.load()
    cfg[_CONSENT_KEY] = value
    config.save(cfg)


def _is_running() -> int | None:
    if not PID_FILE.exists():
        return None
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        PID_FILE.unlink(missing_ok=True)
        return None


def cmd_proxy(args) -> None:
    subcmd = getattr(args, "proxy_cmd", None)
    if subcmd == "start":
        _start()
    elif subcmd == "stop":
        _stop()
    elif subcmd == "status":
        _status()
    elif subcmd == "cert":
        _cert()
    else:
        print("Usage: methodproof proxy [start|stop|status|cert]")


def _start() -> None:
    if _is_running():
        print(f"Proxy already running (PID {PID_FILE.read_text().strip()})")
        return

    if not _is_consented():
        print(_CONSENT_TEXT)
        answer = input("Enable local proxy? [y/N] ").strip().lower()
        if answer != "y":
            print("Proxy not started.")
            return
        _set_consent(True)
        from methodproof.agents.base import log
        log("info", "proxy.consent_granted")

    try:
        import mitmproxy  # noqa: F401
    except ImportError:
        print("mitmproxy not installed. Run: pip install methodproof[proxy]")
        return

    CERT_DIR.mkdir(parents=True, exist_ok=True)

    # Start mitmproxy as background process
    cmd = [
        sys.executable, "-m", "methodproof.proxy_daemon",
        "--port", str(PROXY_PORT),
        "--cert-dir", str(CERT_DIR),
    ]
    proc = subprocess.Popen(
        cmd, stdout=open(LOG_FILE, "a"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid))
    print(f"Proxy started on localhost:{PROXY_PORT} (PID {proc.pid})")
    print(f"Configure tools: export HTTPS_PROXY=http://localhost:{PROXY_PORT}")
    print(f"Install CA cert: methodproof proxy cert")


def _stop() -> None:
    pid = _is_running()
    if not pid:
        print("Proxy not running.")
        return
    os.kill(pid, signal.SIGTERM)
    PID_FILE.unlink(missing_ok=True)
    print(f"Proxy stopped (PID {pid})")


def _status() -> None:
    pid = _is_running()
    if pid:
        print(f"Proxy running on localhost:{PROXY_PORT} (PID {pid})")
        print(f"Consent: {'granted' if _is_consented() else 'not granted'}")
    else:
        print("Proxy not running.")


def _cert() -> None:
    cert_path = CERT_DIR / "mitmproxy-ca-cert.pem"
    if not cert_path.exists():
        print("CA certificate not generated yet. Start the proxy first:")
        print("  methodproof proxy start")
        return
    print(f"CA certificate: {cert_path}")
    print()
    print("Install instructions:")
    if sys.platform == "darwin":
        print(f"  sudo security add-trusted-cert -d -r trustRoot \\")
        print(f"    -k /Library/Keychains/System.keychain {cert_path}")
    elif sys.platform == "linux":
        print(f"  sudo cp {cert_path} /usr/local/share/ca-certificates/methodproof.crt")
        print(f"  sudo update-ca-certificates")
    else:
        print(f"  Import {cert_path} into your system certificate store.")
    print()
    print("For individual tools, set:")
    print(f"  export HTTPS_PROXY=http://localhost:{PROXY_PORT}")
    print(f"  export SSL_CERT_FILE={cert_path}")
