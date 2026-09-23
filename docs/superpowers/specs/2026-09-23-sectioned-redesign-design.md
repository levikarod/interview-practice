# Sectioned redesign: focus-mode practice, stories, profile upload, retention-first feedback

Date: 2026-09-23
Status: approved in conversation, pending spec review

## Intent

Make the app usable end to end without a terminal, and make its feedback stick.

- A new user uploads a CV in the browser and starts practising. The README's
  `python -m core.ingest` command becomes optional, not required.
- Practising a question is distraction-free: the question and the timer, nothing else.
- Story bank, questions, and profile each get their own section.
- Feedback is organised for learning retention: one headline to act on, a
  green/amber/red breakdown, an immediate retry, and explicit credit for what
  improved since the last attempt.

Constraints carried from `CLAUDE.md`, unchanged: local single-user app, FastAPI +
vanilla JS with no build step, exactly one model call per answer, no embeddings,
`profile/` never committed, blocking work off the event loop, tests never make a
real model call.

## Out of scope (considered, not built now)

- **Settings section.** Reserved as a fifth nav entry. Candidate settings: whisper
  model, LLM backend (subscription CLI vs raw API), default answer seconds,
  microphone choice. The router makes adding it one module plus one nav entry.
- Spaced resurfacing of questions with open misses.
- Free-form editing of story text in the browser (review of AI additions only).

## 1. Structure

One HTML shell, `web/index.html`, with hash routes:

| Route | Section |
|---|---|
| `#/practice` (default) | Practice |
| `#/questions` | Questions (today's `/questions` page, moved) |
| `#/stories`, `#/stories/<id>` | Story bank |
| `#/profile` | Profile and CV upload |

- A slim left rail: Practice, Questions, Stories, Profile. Below ~720px it becomes a
  bottom bar.
- Each section is a native ES module in `web/sections/` exporting
  `mount(root, params)` and optionally `unmount()`. `web/app.js` becomes the router
  and nothing else. Shared fetch/DOM helpers live in `web/lib.js`.
- `web/questions.html` and the `/questions` server route are removed;
  `web/questions.js` becomes `web/sections/questions.js` with behaviour unchanged.
- First run: if `/api/profile` reports no real CV (`is_example` or `needs_ingest`),
  the app routes to `#/profile`. The sample profile still works; a single status
  line on Practice says it is sample data and links to Profile.
- The three banners (sample, setup unfinished, model download) collapse into one
  status line on Practice, showing whichever applies.

## 2. Practice

**Home state** (rail visible): answer count, story progress by status, the last
question attempted with a "Retry it" shortcut, and a Start button.

**Focus mode** (entered on Start; rail and status line hidden):

- The question, large, in the reading face.
- A full-bleed hairline across the viewport that drains as time runs out, with the
  countdown digits large beside it.
- A red on-air lamp that lights while recording.
- Controls only: Record / Stop, Different question, and Esc to leave.
- Recording auto-stops when the timer runs out (existing behaviour).

**Processing**: the same focus screen shows the four stages (transcribing,
measuring, checking against your stories, done) from the existing SSE stream, then
becomes the feedback view.

## 3. Feedback

Rendered top to bottom:

1. **The one thing**: `headline`, one sentence, large.
2. **Fixed since last time**: `fixed_since_last`, shown only when non-empty.
3. **Landed** (green): `strengths`, at most 3.
4. **Left on the table** (amber): `missed_points`, each linking to
   `#/stories/<source_story_id>`.
5. **Would get challenged** (brick): `risky_claims`, showing the quote, why, and a
   "Say instead" line.
6. Compact strip: STAR coverage chips plus pace, fillers, longest pause.
7. "What you said", collapsed.
8. Actions: **Try again now** (primary, re-enters focus mode on the same question)
   and **Next question**.
9. When `story_patch` is present: "1 story addition to review", linking to Stories.

### Schema changes (`core/schemas.py`)

- `Feedback.headline: str`: required, one sentence, the single most important change.
- `Feedback.fixed_since_last: list[str]`: `max_length=3`, default empty. Filled
  only when a previous attempt is supplied.
- `RiskyClaim.say_instead: str`: a defensible rewording in the candidate's voice.
- `Feedback.fixes` is removed. Its job is taken by `headline` and `say_instead`.
- `strengths`, `missed_points`, `star_coverage`, `story_patch` are unchanged.

Old runs keep their stored JSON. History is read raw (`db.history` does not
validate), and the frontend renders missing fields as absent.

### Previous attempt (`core/analyze.py`)

`build_payload` gains an optional `previous: dict | None`, the most recent stored
feedback for the same question (`db.history(question_id, limit=1)`). When present,
it appends a `## Their previous attempt at this question` section listing that
attempt's headline, missed points, and risky quotes. `runs.process` looks the
previous attempt up before calling `analyse`. Still one model call.

`prompts/analyze.md` gains short sections for `headline`, `say_instead`, and
`fixed_since_last`. The last of these reports only what the previous attempt missed
or got wrong and this one now gets right, and stays empty otherwise. The `fixes`
section is removed.

## 4. Stories

- A list grouped Stub, Draft, Verified, with a progress bar across the bank.
- A detail view (`#/stories/<id>`) showing the full story.
- **To review** tray: pending story additions from past runs. Each shows current
  and proposed text per section with a checkbox per section. Accept or Dismiss.
- Accept rules (`core/patches.py`, pure function
  `apply_patch(story: Story | None, patch: StoryPatch, sections: list[str]) -> Story`):
  - Only the chosen sections are written, and only when the patch value is non-empty.
  - A `stub` becomes `draft`. A `verified` story being changed also returns to
    `draft`, because its wording is no longer what a human confirmed.
  - `is_new` with no existing story creates one: title from the id, status `draft`,
    source `transcript:<run_id>`.
- **Mark verified** sets status `verified` and `verified` to today's ISO date.
- Files change only on Accept or Verify, through `profile_store.save_story`, which
  already round-trips byte-stably, so every change is a small git diff.

Decisions are recorded in a new table in `core/db.py`:

```sql
CREATE TABLE IF NOT EXISTS patch_decisions (
    run_id     TEXT PRIMARY KEY,
    decision   TEXT NOT NULL,
    decided_at REAL NOT NULL
);
```

Pending means a run has a non-null `story_patch` and no decision row.

## 5. Profile and CV upload

- **No CV yet**: a drop zone (PDF, Markdown, text). On drop, "Converting your CV…"
  while one model call runs.
- **Review**: the resulting `cv.md` in an editable textarea, with a hint to check
  role titles and employers. **Build story bank** saves, then derives.
- **Ready**: name, headline, roles and bullet counts; **Numbers to defend** (from
  `unsourced_metrics`); **Edit CV** (textarea, then rebuild); **Upload a new CV**
  (confirms, then passes `replace=true`); a **Guardrails** textarea that saves to
  `guardrails.md`.
- Rebuilding never overwrites filled stories. That is `derive`'s existing guarantee.
- Uploading writes to `profile/`, never `profile.example/`.

## 6. API additions (`main.py`, routes only)

| Route | Behaviour | Errors |
|---|---|---|
| `POST /api/cv` multipart `file`, form `replace: bool` | save the upload to `runtime/uploads/`, `ingest_file(..., REAL_DIR, overwrite=replace)` via `asyncio.to_thread`, return `{markdown}` | 409 on `CvAlreadyExists`; 400 on an unreadable file |
| `GET /api/cv` | `{markdown}` of the active profile | |
| `PUT /api/cv` `{markdown}` | write `profile/cv.md` | 400 if empty |
| `POST /api/cv/build` | `derive(REAL_DIR)`, return counts and `unsourced_metrics` | 422 if no roles are found, with the CLI's guidance text |
| `GET /api/guardrails`, `PUT /api/guardrails` | read / write `guardrails.md` in the active profile | |
| `GET /api/stories/{id}` | full story | 404 |
| `POST /api/stories/{id}/verify` | set verified and date | 404 |
| `GET /api/story-additions` | pending patches with current story text alongside | |
| `POST /api/story-additions/{run_id}/accept` `{sections}` | `apply_patch`, save, record decision | 404 unknown or already decided |
| `POST /api/story-additions/{run_id}/dismiss` | record decision | 404 |

`GET /api/profile` additionally returns `unsourced_metrics` and `pending_additions`
(a count).

## 7. Visual system

The concept is a rehearsal room with an on-air light. The lamp is the one bold
element; everything else stays quiet.

| Token | Light | Role |
|---|---|---|
| paper | `#EEF1F4` | background |
| ink | `#1B2330` | text |
| muted | `#5E6A7A` | secondary text |
| on-air | `#E0402F` | recording lamp only |
| landed | `#2E7D5B` | green feedback |
| table | `#B7791F` | amber feedback |
| challenged | `#B03A2E` | brick feedback, distinct from on-air |

Dark-mode equivalents are defined as tokens under `prefers-color-scheme: dark`.

- Type: **Literata** for the question, the headline, and the timer digits (tabular
  figures). **Public Sans** for the UI. Both come from Google Fonts, with system
  fallbacks.
- Left-aligned throughout; the reading measure is capped around 70ch.
- Motion: only the draining timer line and the lamp's pulse, plus response-to-action
  transitions. `prefers-reduced-motion` disables the pulse.
- Quality floor: visible keyboard focus, usable at 390px, contrast AA on feedback
  colours against paper in both themes.

## 8. Testing

- `tests/test_patches.py`: chosen sections only; empty values ignored; stub to
  draft; verified to draft on change; new-story creation.
- `tests/test_analyze.py`: the payload includes the previous-attempt section when
  given and omits it otherwise; `FakeLLMClient` returns the new fields and they
  validate.
- `tests/test_db.py` (new): pending additions exclude decided runs.
- `tests/test_api.py` (new, FastAPI `TestClient`, `tmp_path` profile, fake LLM):
  upload, then PUT, then build; a 409 on existing without `replace`; accept and
  dismiss flows; verify.
- The frontend is validated by driving the running app in a browser at 1920, 1024,
  and 390 widths.

## 9. Docs

- README: getting started becomes "run the server, open the page, upload your CV".
  The CLI remains documented as an alternative.
- `CLAUDE.md`: note the section-module layout and the `patch_decisions` table.
