"""The one place this app talks to a model.

Two backends behind one interface:

    ClaudeCliClient    shells out to `claude -p`, billed to your subscription
    AnthropicApiClient uses ANTHROPIC_API_KEY, billed per token

Pick with the LLM_BACKEND env var ("cli" by default, or "api").

The tradeoff is the opposite of what you'd assume, measured rather than guessed:
a CLI call carries ~40K tokens of Claude Code scaffolding we can't strip, of
which only ~3-5K is our payload. The API backend sends just our payload and is
roughly 10x cheaper per call. The subscription's advantage is that it spends
rate limits instead of money, not that it costs less.

Every detail of the subprocess call below was established by spike. See the
"LLM subprocess contract" section of CLAUDE.md before changing any of it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parent.parent
# Deliberately empty. A non-bare `claude -p` run loads CLAUDE.md, hooks and MCP
# servers from its working directory; running from the repo root would inject
# this project's own instructions into every call.
SANDBOX = REPO_ROOT / "runtime" / "sandbox"

DEFAULT_MODEL = "claude-opus-5"
TIMEOUT_SECONDS = 300

# Denied rather than merely unused: we want text in, text out, no file access.
NO_TOOLS = ""


class LLMError(RuntimeError):
    pass


@dataclass
class Completion:
    """A model response plus what it cost."""

    text: str = ""
    data: dict[str, Any] | None = None      # populated when a schema was given
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


class LLMClient(Protocol):
    def complete(
        self, instruction: str, payload: str = "",
        schema: dict[str, Any] | None = None,
        system: str | None = None,
    ) -> Completion: ...


# --------------------------------------------------------------------------- #
# Subscription backend
# --------------------------------------------------------------------------- #

class ClaudeCliClient:
    """Runs `claude -p` as a subprocess. Uses your Claude Code login."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        exe = shutil.which("claude")
        if not exe:
            raise LLMError(
                "`claude` is not on PATH. Install the Claude Code CLI and log in, "
                "or set LLM_BACKEND=api with an ANTHROPIC_API_KEY."
            )
        self.exe = exe
        SANDBOX.mkdir(parents=True, exist_ok=True)

    def complete(
        self, instruction: str, payload: str = "",
        schema: dict[str, Any] | None = None,
        system: str | None = None,
    ) -> Completion:
        cmd = [
            self.exe, "-p", instruction,
            "--output-format", "json",
            # NOT --bare: bare mode ignores the subscription login entirely and
            # fails with "Not logged in".
            "--allowedTools", NO_TOOLS,
            "--permission-prompts", "none",
            "--model", self.model,
        ]
        if schema is not None:
            cmd += ["--json-schema", json.dumps(schema)]
        if system:
            cmd += ["--system-prompt", system]

        try:
            proc = subprocess.run(
                cmd,
                input=payload,          # stdin, never argv: argv caps at 32767
                cwd=SANDBOX,            # chars on Windows and ~256KB on macOS
                capture_output=True, text=True, encoding="utf-8",
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"claude timed out after {TIMEOUT_SECONDS}s") from exc

        if proc.returncode != 0 and not proc.stdout.strip():
            raise LLMError(f"claude exited {proc.returncode}: {proc.stderr[:400]}")

        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError(f"claude returned non-JSON: {proc.stdout[:400]}") from exc

        # Failures arrive as is_error=true with subtype="success" and a non-zero
        # exit. Checking exit code or subtype alone will both mislead you.
        if envelope.get("is_error"):
            raise LLMError(f"claude failed: {str(envelope.get('result'))[:400]}")

        usage = envelope.get("usage") or {}
        return Completion(
            text=envelope.get("result") or "",
            data=envelope.get("structured_output"),
            cost_usd=float(envelope.get("total_cost_usd") or 0.0),
            # Real input lands in the cache fields; `input_tokens` alone reads ~2.
            tokens_in=(usage.get("input_tokens", 0)
                       + usage.get("cache_read_input_tokens", 0)
                       + usage.get("cache_creation_input_tokens", 0)),
            tokens_out=usage.get("output_tokens", 0),
            model=self.model,
        )


# --------------------------------------------------------------------------- #
# API backend
# --------------------------------------------------------------------------- #

class AnthropicApiClient:
    """Uses the Anthropic API directly. Needs ANTHROPIC_API_KEY."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise LLMError(
                "The api backend needs the anthropic package: uv sync --extra api"
            ) from exc
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("LLM_BACKEND=api but ANTHROPIC_API_KEY is not set.")
        self.model = model
        self._client = anthropic.Anthropic()

    def complete(
        self, instruction: str, payload: str = "",
        schema: dict[str, Any] | None = None,
        system: str | None = None,
    ) -> Completion:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "messages": [{"role": "user",
                          "content": f"{instruction}\n\n{payload}".strip()}],
        }
        if system:
            kwargs["system"] = system
        if schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": schema}
            }

        message = self._client.messages.create(**kwargs)
        text = "".join(b.text for b in message.content if b.type == "text")
        return Completion(
            text=text,
            data=json.loads(text) if schema is not None and text else None,
            tokens_in=message.usage.input_tokens,
            tokens_out=message.usage.output_tokens,
            model=self.model,
        )


# --------------------------------------------------------------------------- #
# Test double
# --------------------------------------------------------------------------- #

@dataclass
class FakeLLMClient:
    """Canned responses, so tests never make a real call or spend anything."""

    text: str = ""
    data: dict[str, Any] | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(
        self, instruction: str, payload: str = "",
        schema: dict[str, Any] | None = None,
        system: str | None = None,
    ) -> Completion:
        self.calls.append({"instruction": instruction, "payload": payload,
                           "schema": schema, "system": system})
        return Completion(text=self.text, data=self.data, model="fake")


def get_client(model: str = DEFAULT_MODEL) -> LLMClient:
    backend = os.environ.get("LLM_BACKEND", "cli").lower()
    if backend == "api":
        return AnthropicApiClient(model)
    if backend == "cli":
        return ClaudeCliClient(model)
    raise LLMError(f"Unknown LLM_BACKEND {backend!r}. Use 'cli' or 'api'.")
