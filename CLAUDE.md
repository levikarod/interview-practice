# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

A local webapp for practising spoken interview answers. You start a question,
answer against a timer, the answer is transcribed locally, and one Claude call
returns structured feedback judged against *your own* CV and story bank.

The feedback's distinguishing job is **"here is what you had available and didn't
say"** — not generic answer coaching.

## Architecture in one paragraph

FastAPI serves a vanilla-JS page. The browser records with `MediaRecorder` and
POSTs audio. The server transcribes locally with faster-whisper, computes pace and
filler metrics in plain code, retrieves relevant stories by tag overlap, and makes
**exactly one** Claude call that returns a schema-validated `Feedback` object.
Progress streams back over SSE.

**SQLite holds what happened** (sessions, transcripts, feedback, cost).
**Markdown holds what you know** (`profile/`: cv.md, stories, guardrails), so the
profile stays git-diffable and the AI's proposed additions arrive as reviewable
diffs.

## Invariants

These are not style preferences. Each one was established by measurement or is a
correctness requirement.

### 1. Never commit `profile/`

It holds real personal data — phone numbers, employer detail, candid notes. It is
gitignored. Do not add it, do not `git add -f` it, do not copy its contents into
a committed file, a test fixture, or a commit message. Use `profile.example/`.

### 2. Blocking work never runs on the event loop

faster-whisper and the `claude` subprocess both block. They go through
`asyncio.to_thread(...)`. If you block the loop, SSE progress events stall until
the work finishes — the symptom looks like a frontend bug and is not one.

### 3. The LLM subprocess contract

Established by spike, not by reading docs. All four matter:

- **No `--bare`.** Bare mode ignores the subscription login and demands an API
  key. Verified: it exits 1 with `"Not logged in"`.
- **`cwd` must be `runtime/sandbox/`** (empty). A non-bare `-p` run loads
  `CLAUDE.md`, hooks and MCP servers from its working directory. Run it from the
  repo root and this very file gets injected into every call.
- **Payload goes on stdin**, never argv. Argv caps at 32767 chars on Windows and
  ~256KB on macOS; a transcript plus stories exceeds that, and stdin avoids
  shell-escaping quotes and newlines three different ways.
- **Errors surface as `is_error: true` with `subtype: "success"`.** Check
  `is_error`. Exit code and subtype alone will both lie to you.

### 4. One model call per answer

Transcription is local, metrics are code, retrieval is code. If you are adding a
second call to the answer path, that is a design change — raise it, don't just
add it.

### 5. No embeddings / no vector store

Retrieval is tag and alias overlap. The whole profile fits in the context window,
so retrieval focuses the prompt rather than enabling it. When a match is
uncertain the fix is **send more stories**, not retrieve more cleverly. This is a
deliberate decision documented in the README; don't quietly reverse it.

### 6. Module docstrings yes, inline comments no

`.claude/rules/general.md` says zero comments. This repo amends that one step:
each file keeps a module docstring explaining what it is for and why it works the
way it does, because the repo is meant to be read. Line-level `#` and `//`
commentary does not survive.

When you delete a comment that carried a real finding — a measured number, a
failure mode, a trap — move it into the module docstring or into this file.
Don't just delete it. Function docstrings and Pydantic `Field(description=...)`
are both fine; the latter is not even a comment, it reaches the model.

### 7. Force UTF-8 on console output

Windows consoles default to cp1252 and will raise `UnicodeEncodeError` on an
em-dash. Any CLI entry point wraps stdout in UTF-8. The data is fine; the
terminal is not.

## Commands

```bash
uv sync                          # install
uv run uvicorn main:app --reload # serve on :8000
uv run pytest                    # tests
uv run python -m core.ingest <cv.pdf>   # CLI ingest (same code path as the UI)
```

## Testing

`metrics.py`, `retrieve.py` and the frontmatter parser are pure functions and are
unit-tested directly. `llm.py` has a `FakeLLMClient` so `analyze.py` is testable
without spending anything — **tests must never make a real model call.**

Fixtures come from `profile.example/`, never from `profile/`.

## Cost, for context when changing the prompt

An analysis call costs about $0.24 on Opus 5. Measured breakdown: ~20K
cache-write and ~28K cache-read of Claude Code scaffolding against ~3.2K of our
own content, billed per turn across two turns.

Consequence: **trimming our prompt saves less than you would expect** — our
content is about 3% of the call. If you want it cheaper, the levers are the
backend or the model, not the payload.

The raw-API backend skips the scaffolding and costs roughly $0.04 for the same
work, about 4x less. It is not 10x: output tokens dominate once the response is
real, and both backends pay those.
