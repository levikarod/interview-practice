<div align="center">

# Interview Practice

**Answer interview questions out loud. Get told what you had and didn't say.**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Local first](https://img.shields.io/badge/transcription-local%20%26%20free-informational)](#design-decisions)

</div>

**You already knew the answer. You just didn't say it in the room.**

A practice tool with no access to your material can only grade an answer in the
abstract. This one reads your CV, your stories, and your own notes on what you
can't defend — so it can name exactly what you left out.

**The question**

> Walk me through a production incident you owned end to end.

**What you actually said**, transcribed on your own machine:

> So we had a bunch of customers getting charged twice. I killed the worker that
> was doing it and we refunded everyone. Then I wrote the postmortem.

**The one thing**

> Open with the scale: 1,400 customers over nine hours.

**Left on the table**

- **You said "a bunch".** It was **1,400 customers over nine hours** — and your
  guardrails mark that figure as solid, to be defended without hedging.
- **The real cause never came out.** A batch job built its insert by hand and
  never set the idempotency key, so the constraint covered a column that path
  never filled.

**Would get challenged**

- *"It was a pretty bad day but we got it sorted."* — "Sorted" is unverifiable,
  and you have a real answer you didn't give.
  **Say instead:** all 1,400 refunded in two days.

Then **Try again now** asks the same question, and the next feedback opens with
what you fixed since last time.

Every point traces back to a story you wrote. The findings are real output from
the bundled sample profile, reproducible on a fresh clone in about a minute.

---

## Quick start

```bash
git clone https://github.com/levikarod/interview-practice
cd interview-practice
uv sync
uv run uvicorn main:app --reload
```

Open <http://localhost:8000>. With no profile set up it runs on
`profile.example/` — a fictional engineer with a CV, six stories and guardrails
already in place.

Then open **Profile** and upload your own CV (PDF, Markdown or plain text). You
check what was read, click **Build story bank**, and you're practising on your
own material.

The same thing works from the command line if you prefer:

```bash
uv run python -m core.ingest ~/path/to/cv.pdf
```

**Requires** Python 3.11+, [uv](https://docs.astral.sh/uv/), and a Chromium
browser. For feedback you also need the Claude Code CLI installed and logged in
(2.1.205+), or `ANTHROPIC_API_KEY` with `LLM_BACKEND=api`.

## What it does

- **Names what you left out.** Every point traces back to one of your own
  stories or CV bullets, by id.
- **Catches what won't survive a follow-up.** Claims your guardrails block,
  figures you can't source, anything you overstated.
- **Your voice never leaves your machine.** faster-whisper transcribes on your
  own CPU: free, offline, no upload.
- **Trains you to land it inside the window.** Recording stops when the timer
  does, because that is the real constraint.
- **Tells you if you rushed or rambled.** Pace, filler count and longest pause,
  computed as arithmetic rather than a model's opinion.
- **Turns a CV bullet into a story you can tell.** Each answer fills in the
  detail behind a claim you're already making.
- **Rehearses the questions that role will actually ask.** Paste a job
  description; it drafts questions where its requirements meet your material.

## What it will not do

- **Send your CV anywhere you didn't choose.** `profile/` is gitignored;
  transcription is local; only the feedback step calls a model.
- **Invent a story you didn't tell it.** A stub carries a claim and nothing
  else, and the prompt says so explicitly.
- **Replace a mock interview with a person.** It cannot read a room, push back,
  or follow a hunch.
- **Score you.** No rating, no percentage. "Good answer" is not a measurement.
- **Run as a hosted service.** See [the note on other people](#running-this-for-other-people).

---

## How it works

```text
browser                         FastAPI                         disk
───────                         ───────                         ────
MediaRecorder  ──webm/opus──▶  POST /api/answer
   + timer                        │
                                  ├─▶ transcribe.py ──▶ faster-whisper ──▶ text + word times
                                  │                                          (local, free)
                                  ├─▶ metrics.py ──────────────────────▶ wpm, fillers, pauses
                                  │     (pure code, no model call)
                                  │
                                  ├─▶ retrieve.py ─────────────────────▶ profile/  (Markdown)
                                  │     tag/alias overlap, top-K            cv.json
                                  │     NOT embeddings                      stories/*.md
                                  │                                         guardrails.md
                                  └─▶ analyze.py ──▶ llm.py ──▶ `claude -p --json-schema`
                                                                   (your subscription)
SSE  ◀──stage events───────────  GET /api/runs/{id}/events              │
feedback UI ◀──feedback JSON────────────────────────────────────────────┘
                                                                  runtime/app.db
```

**SQLite holds what happened. Markdown holds what you know.** Practice runs are
an append-only log, so they belong in a database. Your CV and stories are
material you edit and review, so they stay as files you can diff.

## Your material

Everything the feedback is judged against lives in `profile/`, which is
gitignored. The repo ships `profile.example/` so the code can be public and your
material doesn't have to be.

| File | What it is |
|---|---|
| `cv.md` | **Source of truth.** Generated from your PDF, then yours to edit |
| `cv.json` | Derived cache. Re-derived whenever `cv.md` changes |
| `stories/*.md` | One story per CV bullet, `stub → draft → verified` |
| `guardrails.md` | Claims you can't defend and figures that are stale |
| `questions.yaml` | Your questions, overriding the shipped bank by id |

A story starts as a **stub** — it knows what you *claim*, but not the story
behind it. That's already enough for feedback to say *"your CV claims 20+
repositories and you never mentioned the number."* Each answer fills in the
empty sections.

<details>
<summary><b>How ingestion works</b> — PDF, Markdown or text → one format</summary>

```text
cv.pdf ─┐
cv.txt ─┼─ text ─→ [one model call] ─→ cv.md ─→ [parse, no model] ─→ cv.json
cv.md  ─┘                                ↑                              │
                                         └── edit this by hand ─────────┘
```

The PDF is **never parsed structurally** — no column detection, no heading
heuristics. Its text goes to the model, whose only job is normalising *any* CV
into this one format. Layout chaos is what a model is good at and a regex parser
is bad at.

A Markdown CV that already carries `<!--meta-->` blocks skips the model
entirely. Re-run `core.ingest` any time to re-derive; it never overwrites a
story you've filled in, and refuses to clobber an existing `cv.md` without
`--force`.

</details>

## Questions

The **Questions** section browses the bank, edits any question, and drafts new
ones from a job description.

**Two layers.** `questions/core.yaml` is committed and works for anyone. Yours
live in gitignored `profile/questions.yaml` and win on id collision — so editing
a shipped question writes an override, and `git pull` never fights your edits.

Generated questions are short and open, and **never name the specifics you're
meant to be recalling**:

| ✗ | ✓ |
|---|---|
| Walk me through how your row-level security rewrote a query to substitute per-user values, and show me why that didn't cost you query performance. | Where does per-tenant isolation live in your query path? |

The second one makes you supply the mechanism. The first hands it to you, so
rehearsing against it teaches nothing. The specificity moves to the tags and the
note, which you don't see while answering.

Nothing is saved until you pick. A bank that fills itself is worse than one that
stays small.

---

## Design decisions

The interesting part of this repo is what it deliberately doesn't do.

| Decision | Why |
|---|---|
| **One model call per answer** | Transcription is local, metrics are code, retrieval is code. The model is reserved for the one step needing judgment |
| **No embeddings, no vector store** | The whole profile fits in a 1M context window. Retrieval focuses the prompt rather than enabling it |
| **Schema constraints, not prompt pleas** | One Pydantic model generates the JSON Schema *and* validates the reply. Length caps are `max_length`, not requests |
| **Markdown corpus, not a database** | AI-proposed story additions arrive as reviewable git diffs |
| **Two LLM backends, one interface** | Subscription by default, API key as an alternative. Measured, not assumed |

<details>
<summary><b>Why no vector search</b> — and when that would change</summary>

Retrieval is tag and alias overlap. The whole profile is ~30–60K tokens against
a 1M-token context window, so when a match is uncertain the correct fix is *send
more stories*, not retrieve more cleverly.

Vector search would add an embedding model, a store, a chunking strategy, an
index to keep in sync, and a silent wrong-neighbour failure mode, for no
capability gain.

The one real weakness of lexical matching is vocabulary drift — a question
saying "exactly-once" should still reach a story tagged "idempotency". The
`aliases:` field handles that, so the corpus format solves it rather than the
retriever.

**Revisit if** the bank passes a few hundred stories, or transcripts of past
answers become searchable material in their own right.

</details>

<details>
<summary><b>What a call actually costs</b> — measured, and the surprise in it</summary>

| | subscription (`claude -p`) | raw API |
|---|---|---|
| One analysis | ~$0.24 *(rate limits, not dollars)* | ~$0.04 |
| Tokens per call | ~48K, of which ~3.2K is ours | just our payload |
| Questions from a JD | ~$1.50 (per application, not per answer) | — |

The gap is Claude Code's own scaffolding, billed per turn and not strippable
from outside the CLI.

Two things follow. **Trimming our prompt is nearly pointless** — our content is
~3% of the call; the levers are the backend or the model. And the ratio is ~4x,
not the 10x a trivial probe suggests, because output tokens dominate once the
response is real and both backends pay those.

</details>

<details>
<summary><b>Transcription</b> — why <code>small.en</code>, and the CV as a glossary</summary>

Local, free, and no system ffmpeg needed — faster-whisper decodes through PyAV,
which ships its own.

The CV doubles as the speech model's glossary. Tech terms from `cv.json` go in
as an `initial_prompt`, distinctive names first (internal capital or a digit —
ClickHouse, RabbitMQ, k6), because the budget is small and "Python" needs no
help. Measured on one clip, that turned "two **salary** workers" into "two
**Celery** workers".

Model size, on a 25s clip at CPU int8:

| | named entities | speed | a 120s answer |
|---|---|---|---|
| `small.en` (default) | 4/6 | 0.44x realtime | ~53s |
| `medium.en` | 4/6 | 1.73x realtime | ~3.5 min |

Same entities, but `medium.en` reads the surrounding sentence better — "the
**lock alone** was not enough" where `small.en` heard "the **local owner**
was". That phrase is what the analysis step reads, so it matters. It still isn't
the default: 3.5 minutes per answer breaks the practice loop. Set
`WHISPER_MODEL=medium.en` to trade pace for accuracy.

Those numbers come from synthesised speech, which is harder for Whisper than a
real voice — treat them as a floor. First run downloads ~0.5GB of weights.

</details>

---

## Configuration

All optional; every one has a working default.

| Variable | Default | What it changes |
|---|---|---|
| `LLM_BACKEND` | `cli` | `cli` uses your Claude subscription, `api` uses `ANTHROPIC_API_KEY` |
| `CLAUDE_BIN` | auto | Pin a specific `claude` executable |
| `WHISPER_MODEL` | `small.en` | `medium.en` is more accurate and ~4x slower |
| `WHISPER_COMPUTE` | `int8` | CTranslate2 compute type |

> **Two installs of Claude Code?** A stale npm one often shadows the current
> native one on PATH. The app picks the newest it can find and reports the
> version if it's too old, so this usually resolves itself.

## Development

```bash
uv run pytest                    # 170 tests, none make a model call
uv run uvicorn main:app --reload
```

```text
core/
  schemas.py        Pydantic models — the single source of truth
  llm.py            ClaudeCliClient | AnthropicApiClient behind one interface
  transcribe.py     faster-whisper wrapper
  profile_store.py  read/write the Markdown profile (byte-identical round-trip)
  ingest.py         CV → profile → story stubs
  retrieve.py       tag/alias overlap
  analyze.py        the one model call
  jd.py             questions from a job description
  runs.py           per-run asyncio.Queue, drained by SSE
  patches.py        merge a reviewed story addition into a story
  db.py             sqlite
main.py             routes only; logic lives in core/ so it tests without a server
web/
  index.html        the shell: section rail + view
  app.js            hash router
  lib.js            fetch and formatting helpers
  sections/         one module per section: practice, questions, stories, profile
  style.css
profile.example/    fictional, committed — sample data and test fixtures
profile/            gitignored — your real material
```

Tests use `profile.example/` exclusively, and `tests/conftest.py` makes building
a real LLM client inside a test raise. See [CLAUDE.md](CLAUDE.md) for the
invariants that aren't obvious from the code.

## Running this for other people

Anthropic's terms don't allow third-party products to offer claude.ai login.
Running this locally on your own machine and your own login is you using Claude
Code, which is fine — as is someone cloning it and running it against their own
install. **Hosting it as a service for other people is not.** The API-key
backend exists so the repo never depends on that.

## Licence

[MIT](LICENSE).
