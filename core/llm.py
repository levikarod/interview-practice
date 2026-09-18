"""The one place this app talks to a model.

Two backends behind one interface, chosen by the LLM_BACKEND env var:
ClaudeCliClient ("cli", the default) shells out to `claude -p` and bills your
Claude subscription; AnthropicApiClient ("api") uses ANTHROPIC_API_KEY.

The tradeoff between them is the opposite of the obvious one, measured rather
than guessed. A CLI call carries ~40K tokens of Claude Code scaffolding that
cannot be stripped from outside the CLI, of which only ~3-5K is our payload, so
the API backend is roughly 10x cheaper per call. The subscription's advantage is
that it spends rate limits instead of money, not that it costs less.

Five properties of the subprocess call were established by spike and each has a
way of failing quietly if changed. They are also recorded in CLAUDE.md:

1. No --bare. Bare mode ignores the subscription login entirely and exits with
   "Not logged in", because it never reads OAuth credentials or the keychain.
2. cwd is runtime/sandbox, which is empty. A non-bare `claude -p` run loads
   CLAUDE.md, hooks and MCP servers from its working directory, so running from
   the repo root would inject this project's own instructions into every call.
3. The payload goes on stdin, never argv. Argv caps at 32767 characters on
   Windows and ~256KB on macOS, and a transcript plus stories exceeds that.
4. Failures arrive as is_error=true alongside subtype="success". Checking the
   exit code or the subtype alone will each mislead you.
5. Real input token counts live in the cache fields. usage.input_tokens alone
   reads about 2 no matter how large the prompt was.

Tools are denied rather than merely unused: this is text in, text out, with no
file or network access.
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
SANDBOX = REPO_ROOT / "runtime" / "sandbox"

DEFAULT_MODEL = "claude-opus-5"
TIMEOUT_SECONDS = 300
NO_TOOLS = ""


class LLMError(RuntimeError):
    pass


@dataclass
class Completion:
    """A model response plus what it cost. `data` is populated only when a
    schema was supplied."""

    text: str = ""
    data: dict[str, Any] | None = None
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


class ClaudeCliClient:
    """Runs `claude -p` as a subprocess, using your Claude Code login."""

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
                cmd, input=payload, cwd=SANDBOX,
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

        if envelope.get("is_error"):
            raise LLMError(f"claude failed: {str(envelope.get('result'))[:400]}")

        usage = envelope.get("usage") or {}
        return Completion(
            text=envelope.get("result") or "",
            data=envelope.get("structured_output"),
            cost_usd=float(envelope.get("total_cost_usd") or 0.0),
            tokens_in=(usage.get("input_tokens", 0)
                       + usage.get("cache_read_input_tokens", 0)
                       + usage.get("cache_creation_input_tokens", 0)),
            tokens_out=usage.get("output_tokens", 0),
            model=self.model,
        )


class AnthropicApiClient:
    """Calls the Anthropic API directly. Needs ANTHROPIC_API_KEY."""

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
