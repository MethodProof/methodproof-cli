"""Proxy daemon — local mitmproxy that decodes AI API traffic.

Security controls:
- Only decodes domains in DOMAIN_RULES (AI APIs only)
- Strips Authorization, x-api-key, api-key headers before decoding
- Events posted to bridge (localhost:9877) → consent gates → storage
- Non-AI traffic passes through unmodified
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


BRIDGE_URL = "http://localhost:9877/events"
_DECODER_BIN = shutil.which("mp-decoder")

# AI API domains — only these get decoded. All other traffic passes through.
AI_DOMAINS = {
    "api.openai.com", "api.anthropic.com", "api.together.ai", "api.groq.com",
    "api.mistral.ai", "api.cerebras.ai", "openrouter.ai", "api.x.ai",
    "api.deepseek.com", "api.fireworks.ai", "api.perplexity.ai", "api.cohere.com",
    "generativelanguage.googleapis.com", "dashscope.aliyuncs.com",
    "copilot-proxy.githubusercontent.com", "api.githubcopilot.com",
}

# Headers to strip before decoding (security)
_STRIP_HEADERS = {"authorization", "x-api-key", "api-key", "x-goog-api-key"}


def _post_event(event_type: str, metadata: dict) -> None:
    """Post event to bridge. Fail silently."""
    body = json.dumps({"events": [{"type": event_type, "timestamp": time.time(), "metadata": metadata}]}).encode()
    req = urllib.request.Request(BRIDGE_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass


def _is_ai_domain(domain: str) -> bool:
    for ai in AI_DOMAINS:
        if domain == ai or domain.endswith(f".{ai}"):
            return True
    if "localhost" in domain and any(p in domain for p in [":11434", ":18789", ":1234"]):
        return True
    if "bedrock-runtime" in domain and "amazonaws.com" in domain:
        return True
    if "openai.azure.com" in domain:
        return True
    return False


def _decode_via_binary(provider: str, direction: str, body: dict, latency_ms: float = 0) -> dict | None:
    """Call mp-decoder binary. Returns decoded data or None."""
    if not _DECODER_BIN:
        return None
    payload = json.dumps({"provider": provider, "direction": direction, "body": body, "latency_ms": latency_ms})
    try:
        result = subprocess.run(
            [_DECODER_BIN], input=payload, capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def _match_provider(domain: str, path: str) -> str | None:
    """Match domain+path to decoder provider name."""
    if not _DECODER_BIN:
        return None
    try:
        result = subprocess.run(
            [_DECODER_BIN, "match", domain, path], capture_output=True, text=True, timeout=1,
        )
        name = result.stdout.strip()
        return name if name and name != "null" else None
    except Exception:
        return None


class ProxyAddon:
    """mitmproxy addon that decodes AI API traffic and posts to bridge."""

    def __init__(self):
        self._pending: dict[str, dict] = {}

    def request(self, flow):
        domain = flow.request.pretty_host
        if not _is_ai_domain(domain):
            return
        # Strip credentials before storing
        for header in _STRIP_HEADERS:
            flow.request.headers.pop(header, None)
        self._pending[flow.id] = {
            "domain": domain,
            "path": flow.request.path,
            "method": flow.request.method,
            "start_time": time.time(),
            "req_body": flow.request.get_text() or "",
        }

    def response(self, flow):
        req = self._pending.pop(flow.id, None)
        if not req:
            return
        domain = req["domain"]
        path = req["path"]
        latency_ms = (time.time() - req["start_time"]) * 1000

        provider = _match_provider(domain, path)
        if not provider:
            return

        # Decode request → llm_prompt
        try:
            req_json = json.loads(req["req_body"])
        except (json.JSONDecodeError, ValueError):
            return
        decoded = _decode_via_binary(provider, "request", req_json)
        if decoded and decoded.get("kind") == "prompt":
            _post_event(decoded.get("event_type", "llm_prompt"), decoded.get("metadata", {}))

        # Decode response → llm_completion
        try:
            resp_json = json.loads(flow.response.get_text() or "{}")
        except (json.JSONDecodeError, ValueError):
            return
        decoded = _decode_via_binary(provider, "response", resp_json, latency_ms)
        if decoded and decoded.get("kind") == "completion":
            _post_event(decoded.get("event_type", "llm_completion"), decoded.get("metadata", {}))


def main():
    parser = argparse.ArgumentParser(description="MethodProof proxy daemon")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--cert-dir", type=str, default=str(Path.home() / ".methodproof" / "proxy-certs"))
    args = parser.parse_args()

    from mitmproxy.options import Options
    from mitmproxy.tools.dump import DumpMaster

    opts = Options(listen_port=args.port, confdir=args.cert_dir)
    m = DumpMaster(opts)
    m.addons.add(ProxyAddon())
    try:
        m.run()
    except KeyboardInterrupt:
        m.shutdown()


if __name__ == "__main__":
    main()
