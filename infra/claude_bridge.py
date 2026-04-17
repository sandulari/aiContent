"""Claude bridge — exposes the host's `claude` CLI to the Docker stack.

Runs on the host (not inside Docker) and shells out to the `claude`
binary which is already authenticated against the user's Claude Max
subscription. The Docker API container POSTs here instead of calling
the Anthropic pay-per-call API.

Endpoints:
    GET  /health
    POST /chat  — body: { system_prompt, messages: [{role, content}], model? }

Run:
    python3 infra/claude_bridge.py

The daemon binds to 127.0.0.1:7777 + 0.0.0.0:7777 so macOS Docker's
`host.docker.internal` resolves. On macOS you'll see both a loopback
and a bridge-accessible listener.

Stateless: every request spawns a fresh `claude -p` subprocess with
--no-session-persistence. Each POST sends the full conversation
history, which the bridge serialises into a single prompt.

This is a single-user dev/personal tool. Do not expose to the public
internet. The subscription's ToS applies (personal use).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# ── Config ────────────────────────────────────────────────────────────
CLAUDE_BIN = os.environ.get(
    "CLAUDE_BRIDGE_BIN",
    os.path.expanduser("~/.local/bin/claude"),
)
BIND_HOST = os.environ.get("CLAUDE_BRIDGE_HOST", "0.0.0.0")
BIND_PORT = int(os.environ.get("CLAUDE_BRIDGE_PORT", "7777"))
DEFAULT_MODEL = os.environ.get("CLAUDE_BRIDGE_MODEL", "sonnet")
SUBPROCESS_TIMEOUT = int(os.environ.get("CLAUDE_BRIDGE_TIMEOUT", "120"))
MAX_PROMPT_CHARS = int(os.environ.get("CLAUDE_BRIDGE_MAX_PROMPT", "120000"))

# Simple semaphore so we don't spawn 20 `claude` subprocesses if the
# frontend spams. Personal subscription + sequential is fine.
MAX_CONCURRENT = int(os.environ.get("CLAUDE_BRIDGE_CONCURRENCY", "2"))
_semaphore = threading.Semaphore(MAX_CONCURRENT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bridge] %(levelname)s %(message)s",
)
log = logging.getLogger("claude-bridge")


# ── Serialisation helpers ─────────────────────────────────────────────

def _messages_to_prompt(messages: list[dict]) -> str:
    """Serialise chat history into a single text prompt.

    `claude -p` takes ONE prompt as argv. For multi-turn chats we
    flatten the conversation into a tagged-block format that matches
    how Claude naturally reads conversations.
    """
    lines = []
    for m in messages:
        role = (m.get("role") or "").lower()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"[USER]\n{content}")
        elif role == "assistant":
            lines.append(f"[ASSISTANT]\n{content}")
        elif role == "system":
            # Prepend system messages as context — they're usually
            # handled via --system-prompt, but accept inline too.
            lines.append(f"[CONTEXT]\n{content}")
    lines.append("[ASSISTANT]")  # cue Claude to respond as assistant
    return "\n\n".join(lines)


def _extract_text_from_claude_json(raw_stdout: str) -> tuple[str, dict]:
    """Pull the human-readable text out of `claude -p --output-format json`.

    Returns (text, meta). On parse failure, returns the raw stdout and
    an empty meta dict — callers must handle that gracefully.
    """
    try:
        parsed = json.loads(raw_stdout)
    except json.JSONDecodeError:
        return raw_stdout.strip(), {}

    if parsed.get("is_error"):
        return "", {"error": parsed.get("result") or "Claude error", **parsed}

    text = parsed.get("result") or ""
    meta = {
        "duration_ms": parsed.get("duration_ms"),
        "session_id": parsed.get("session_id"),
        "num_turns": parsed.get("num_turns"),
        "cost_usd": parsed.get("total_cost_usd"),
    }
    return text, meta


def _strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` fences that Claude wraps around JSON
    responses even when we ask it not to."""
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", stripped, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return stripped


# ── Claude CLI invocation ─────────────────────────────────────────────

def _run_claude(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Shell out to `claude -p` and return a result dict.

    Returns:
        { "ok": bool, "text": str, "meta": dict, "error": str? }
    """
    if not os.path.isfile(CLAUDE_BIN):
        return {"ok": False, "text": "", "error": f"claude binary missing at {CLAUDE_BIN}"}

    if len(user_prompt) > MAX_PROMPT_CHARS:
        return {"ok": False, "text": "", "error": "prompt too long"}

    cmd = [
        CLAUDE_BIN,
        "-p",
        "--no-session-persistence",
        "--model",
        model,
        "--output-format",
        "json",
        "--dangerously-skip-permissions",
    ]
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    cmd.append(user_prompt)

    log.info(
        "claude -p call: model=%s system_chars=%d user_chars=%d",
        model, len(system_prompt or ""), len(user_prompt),
    )

    with _semaphore:
        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT,
                # Inherit user's environment so subscription auth is
                # found. No shell=True — argv list is injection-safe.
            )
        except subprocess.TimeoutExpired:
            log.warning("claude subprocess timed out after %ds", SUBPROCESS_TIMEOUT)
            return {"ok": False, "text": "", "error": "claude subprocess timed out"}
        except Exception as exc:
            log.exception("claude subprocess failed")
            return {"ok": False, "text": "", "error": f"subprocess error: {exc}"}
        elapsed = time.time() - start

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "")[-400:]
        log.warning("claude -p exit %d: %s", proc.returncode, stderr_tail)
        return {
            "ok": False,
            "text": "",
            "error": f"claude exit {proc.returncode}: {stderr_tail}",
        }

    text, meta = _extract_text_from_claude_json(proc.stdout)
    if not text:
        return {
            "ok": False,
            "text": "",
            "meta": meta,
            "error": meta.get("error", "empty claude response"),
        }

    text = _strip_code_fences(text)
    meta["elapsed_sec"] = round(elapsed, 2)
    log.info("claude response %d chars in %.1fs", len(text), elapsed)
    return {"ok": True, "text": text, "meta": meta}


# ── HTTP server ───────────────────────────────────────────────────────

class BridgeHandler(BaseHTTPRequestHandler):
    def _json(self, status: int, body: dict):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):
        log.info("%s - %s", self.address_string(), format % args)

    def do_GET(self):
        if self.path == "/health":
            ok = os.path.isfile(CLAUDE_BIN)
            return self._json(200 if ok else 500, {
                "ok": ok,
                "bin": CLAUDE_BIN,
                "version_check": "run /version for full check",
            })
        if self.path == "/version":
            try:
                proc = subprocess.run(
                    [CLAUDE_BIN, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return self._json(200, {"version": proc.stdout.strip()})
            except Exception as e:
                return self._json(500, {"error": str(e)})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/chat":
            return self._json(404, {"error": "not found"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            return self._json(400, {"error": f"bad json: {e}"})

        system_prompt = body.get("system_prompt") or ""
        messages = body.get("messages") or []
        model = body.get("model") or DEFAULT_MODEL

        if not isinstance(messages, list) or not messages:
            return self._json(400, {"error": "messages must be a non-empty list"})
        if not isinstance(system_prompt, str):
            return self._json(400, {"error": "system_prompt must be a string"})

        prompt = _messages_to_prompt(messages)
        result = _run_claude(system_prompt, prompt, model=model)
        status = 200 if result.get("ok") else 502
        return self._json(status, result)


def main():
    if not os.path.isfile(CLAUDE_BIN):
        log.error("claude binary not found at %s", CLAUDE_BIN)
        sys.exit(1)
    log.info("claude bridge starting on %s:%d -> %s", BIND_HOST, BIND_PORT, CLAUDE_BIN)
    log.info("max concurrency: %d  timeout: %ds", MAX_CONCURRENT, SUBPROCESS_TIMEOUT)
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), BridgeHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
