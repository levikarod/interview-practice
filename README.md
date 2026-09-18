# Interview Practice

Practise spoken interview answers against **your own CV and story bank**.

You start a question, answer out loud against a timer, and get back short
actionable feedback. The distinguishing job of that feedback is not "was that a
good answer" in the abstract — it's:

> **Here is what you had available and didn't say.**

That only works if the tool holds your actual material, so it does: your CV, your
stories, and your guardrails all live on disk as Markdown you can edit.

---

## Status

Being built in phases, and the core loop works end to end: record an answer, get
it transcribed locally, and get back what you had in your own material and didn't
say. What runs today:

| | |
|---|---|
| ✅ | CV (PDF, Markdown or text) → `cv.md` → `cv.json` → story stubs |
| ✅ | Story bank: parse, render, `stub → draft → verified` lifecycle |
| ✅ | Guardrails: flags CV figures with nothing behind them |
| ✅ | Sample profile so the app runs with zero setup |
| ✅ | Record against a hard-stop timer, transcribe locally, measure delivery |
| ✅ | Retrieval, feedback, and per-answer cost — the point of the whole thing |
| ⬜ | Applying AI-proposed story patches (they're generated, not yet reviewable) |
| ⬜ | Answer history over time |
| ⬜ | Browser setup screen with an editable review step |

---

## Quickstart

**Prerequisites:** Python 3.11+ and [uv](https://docs.astral.sh/uv/). For the
feedback step (not yet wired up) you'll also want the Claude Code CLI installed
and logged in, or `ANTHROPIC_API_KEY` set.

```bash
git clone <repo> && cd interview-practice
uv sync
uv run uvicorn main:app --reload
```

Open <http://localhost:8000>.

With no profile set up, it runs on `profile.example/` — a fictional engineer with
a CV, six stories and guardrails already in place. You can click around
immediately without handing your CV to a stranger's repo.

## Using your own CV

Point it at your CV — PDF, Markdown or plain text:

```bash
uv run python -m core.ingest ~/path/to/cv.pdf
```

That writes `profile/cv.md`, derives `profile/cv.json`, creates one **story stub**
per CV bullet, and lists the figures you'd struggle to defend. Reload the page;
no restart needed.

Re-run it any time to re-derive after editing `cv.md`:

```bash
uv run python -m core.ingest
```

Two things it won't destroy: re-deriving never overwrites a story you've already
filled in, and ingesting a new CV refuses to clobber an existing `cv.md` — pass
`--force` if replacing it is genuinely what you want.

### How ingestion works

```
cv.pdf ─┐
cv.txt ─┼─ text ─→ [one model call] ─→ cv.md ─→ [parse, no model] ─→ cv.json
cv.md  ─┘                                ↑                              │
                                         └── edit this by hand ─────────┘
```

**`cv.md` is the source of truth; `cv.json` is a derived cache.** The PDF is
never parsed structurally — no column detection, no heading heuristics. Its text
goes to the model, whose only job is normalising *any* CV into this one format.
Layout chaos is what a model is good at and what a regex parser is bad at.

A Markdown CV that already carries `<!--meta-->` blocks skips the model entirely,
because it's already in the target format.

> **`profile/` is gitignored and must stay that way.** It holds real personal
> data. The repo ships `profile.example/` so the code can be public and your
> material doesn't have to be.

---

## Transcription

Runs locally with faster-whisper and costs nothing. No system ffmpeg needed — it
decodes through PyAV, which ships its own.

The CV doubles as the speech model's glossary: tech terms from `cv.json` are
passed as an `initial_prompt`, with distinctive names first (an internal capital
or a digit — ClickHouse, RabbitMQ, k6), because the prompt budget is small and
"Python" needs no help. Measured on one clip, that turned "two **salary**
workers" into "two **Celery** workers".

Model size, measured on a 25s clip at CPU int8:

| | named entities | speed | a 120s answer |
|---|---|---|---|
| `small.en` (default) | 4/6 | 0.44x realtime | ~53s |
| `medium.en` | 4/6 | 1.73x realtime | ~3.5 min |

Same entities, but `medium.en` was clearly better on the surrounding sentence —
"the **lock alone** was not enough" where `small.en` heard "the **local owner**
was". That phrase is what the analysis step reads, so it matters. It still isn't
the default, because 3.5 minutes per answer breaks the practice loop. Set
`WHISPER_MODEL=medium.en` to trade pace for accuracy.

Those numbers come from synthesised speech, which is harder for Whisper than a
real voice — treat them as a floor.

First run downloads the weights (~0.5GB), which the UI warns about.

## How it works

```
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

**SQLite holds what happened** (sessions, transcripts, feedback, cost).
**Markdown holds what you know** (`profile/`). So the profile stays git-diffable
and hand-editable, and the AI's proposed additions arrive as reviewable diffs
rather than opaque database rows.

### The story bank grows as you practise

A CV bullet becomes a **stub** — it knows what you *claim*, but not the story
behind it:

```
status: stub     →  claim only, derived from a CV bullet
status: draft    →  STAR detail proposed from a transcript, unreviewed
status: verified →  you confirmed the wording and the facts
```

That progression is the product. A stub is already useful on day one — feedback
can say *"your CV claims 20+ repositories and you never mentioned the number"* —
and each answer you give fills in the empty sections.

---

## Design decisions

Three choices that are load-bearing, and the reasoning behind them.

**Exactly one model call per answer.** Transcription is local, pace and filler
metrics are plain code, retrieval is plain code. The model is reserved for the
one step that genuinely needs judgment.

**No embeddings, no vector store.** Retrieval is tag and alias overlap. The whole
profile is ~30–60K tokens against a 1M-token context window, so retrieval focuses
the prompt rather than enabling it — when a match is uncertain the correct fix is
*send more stories*, not retrieve more cleverly. Vector search would add an
embedding model, a store, a chunking strategy, an index to keep in sync, and a
silent wrong-neighbour failure mode, for no capability gain. Worth revisiting
past a few hundred stories; not before.

**Two LLM backends, one interface.** `ClaudeCliClient` shells out to `claude -p`
and bills your subscription. `AnthropicApiClient` uses an API key. Measured
during a spike, the tradeoff is the opposite of what you'd assume:

| | subscription (`claude -p`) | raw API |
|---|---|---|
| Cost per analysis | ~$0.24 *(rate limits, not dollars)* | ~$0.04 |
| Tokens per call | ~48K, of which ~3.2K is ours | just our payload |

The gap is Claude Code's own scaffolding, which can't be stripped from outside
the CLI and is billed per turn. So the subscription's advantage isn't that it's
cheaper — it's that it spends rate limits instead of money.

Two things follow. Trimming our prompt is nearly pointless: our content is ~3% of
the call. And the ratio is ~4x rather than the 10x a trivial probe suggests,
because output tokens dominate once the response is real and both backends pay
those. Pick per run with `LLM_BACKEND`.

---

## Development

```bash
uv run pytest                    # 34 tests, no model calls
uv run uvicorn main:app --reload
```

```
core/
  schemas.py        Pydantic models — one declaration produces the JSON Schema
                    sent to the model AND validates what comes back
  profile_store.py  read/write the Markdown profile (byte-identical round-trip)
  ingest.py         CV → profile → story stubs
main.py             routes only; logic lives in core/ so it tests without a server
profile.example/    fictional, committed — sample data and test fixtures
profile/            gitignored — your real material
```

Tests use `profile.example/` exclusively. Nothing in `profile/` may appear in a
test, a fixture, or a commit.

See [CLAUDE.md](CLAUDE.md) for the invariants that aren't obvious from the code —
particularly the LLM subprocess contract, which was established by measurement
and has four separate ways to get it subtly wrong.
