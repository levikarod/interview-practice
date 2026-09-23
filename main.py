"""FastAPI entry point.

Routes only. All logic lives in `core/` so it stays testable without a server.

Run: uv run uvicorn main:app --reload
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from datetime import date
from pathlib import Path

from fastapi import Body, FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from pypdf.errors import PyPdfError

from core import (db, ingest, jd, llm, patches, profile_store, questions, runs,
                  transcribe)
from core.schemas import Question, Story, StoryPatch, StoryStatus
from core.profile_store import ProfileNotSetUp

REPO_ROOT = Path(__file__).resolve().parent
WEB_DIR = REPO_ROOT / "web"
AUDIO_DIR = REPO_ROOT / "runtime" / "audio"

app = FastAPI(title="Interview Practice", version="0.1.0")

SAMPLE_IS_READ_ONLY = ("This is the sample profile. Upload your own CV on the "
                       "Profile page before changing anything.")


def _writable_dir() -> Path:
    """The active profile, refusing the committed sample."""
    try:
        directory = profile_store.profile_dir()
    except ProfileNotSetUp as exc:
        raise HTTPException(409, str(exc)) from exc
    if profile_store.is_example(directory):
        raise HTTPException(409, SAMPLE_IS_READ_ONLY)
    return directory


def _active_stories() -> list[Story]:
    try:
        return profile_store.load_stories()
    except ProfileNotSetUp:
        return []


def _find_story(story_id: str, stories: list[Story]) -> Story | None:
    return next((s for s in stories if s.id == story_id), None)


@app.get("/api/profile")
def get_profile() -> dict:
    """Summary of the active profile, and whether it's the bundled sample.

    The UI shows a banner when `is_example` is true, so nobody mistakes Mara
    Okonjo's stories for their own.
    """
    try:
        directory = profile_store.profile_dir()
    except ProfileNotSetUp as exc:
        return {"ready": False, "reason": str(exc)}

    profile = profile_store.load_profile(directory)
    stories = profile_store.load_stories(directory)

    return {
        "ready": True,
        "is_example": profile_store.is_example(directory),
        "needs_ingest": profile_store.needs_ingest(directory),
        "name": profile.name,
        "headline": profile.headline,
        "roles": len(profile.roles),
        "bullets": sum(len(r.bullets) for r in profile.roles),
        "has_guardrails": bool(profile_store.load_guardrails(directory).strip()),
        "model_cached": transcribe.is_model_cached(),
        "whisper_model": transcribe.DEFAULT_MODEL,
        "stories": {
            "total": len(stories),
            "stub": sum(1 for s in stories if s.status.value == "stub"),
            "draft": sum(1 for s in stories if s.status.value == "draft"),
            "verified": sum(1 for s in stories if s.status.value == "verified"),
        },
        "unsourced_metrics": ingest.unsourced_metrics(profile),
        "pending_additions": len(db.pending_patches(profile_store.kind())),
    }


NO_ROLES = ("No roles were found. Each role needs a '### Title, Employer "
            "(Location) (Dates)' heading under '## Experience'. Compare it with "
            "the sample CV's layout, then build again.")


@app.post("/api/cv")
async def upload_cv(file: UploadFile, replace: bool = Form(False)) -> dict:
    """Convert an uploaded CV into cv.md and return it for review.

    The upload lives in a temporary folder only while it is read, so the
    original file is not kept. Conversion is a model call, so it runs off the
    event loop.
    """
    suffix = Path(file.filename or "cv.txt").suffix.lower()
    data = await file.read()
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / f"cv{suffix}"
        source.write_bytes(data)
        try:
            markdown = await asyncio.to_thread(
                ingest.ingest_file, source, profile_store.REAL_DIR, None, replace)
        except ingest.CvAlreadyExists as exc:
            raise HTTPException(409, "You already have a CV. Replace it?") from exc
        except (ValueError, PyPdfError) as exc:
            raise HTTPException(400, f"Couldn't read that file: {exc}") from exc
        except llm.LLMError as exc:
            raise HTTPException(502, f"Converting the CV failed: {exc}") from exc
    return {"markdown": markdown}


@app.get("/api/cv")
def get_cv() -> dict:
    try:
        return {"markdown": profile_store.load_cv_markdown()}
    except ProfileNotSetUp:
        return {"markdown": ""}


@app.put("/api/cv")
def save_cv(payload: dict = Body(...)) -> dict:
    markdown = str(payload.get("markdown") or "")
    if not markdown.strip():
        raise HTTPException(400, "The CV is empty.")
    profile_store.REAL_DIR.mkdir(parents=True, exist_ok=True)
    (profile_store.REAL_DIR / "cv.md").write_text(markdown, encoding="utf-8")
    return {"saved": True}


@app.post("/api/cv/build")
def build_cv() -> dict:
    """cv.md to profile and story stubs: the same `derive` the CLI runs.

    Parsed first and refused when no roles come out, so a misread CV never
    leaves behind a cv.json that makes an empty profile look finished.
    """
    source = profile_store.REAL_DIR / "cv.md"
    if not source.exists():
        raise HTTPException(409, "Upload a CV first.")
    if not ingest.parse_cv_markdown(source.read_text(encoding="utf-8")).roles:
        raise HTTPException(422, NO_ROLES)

    result = ingest.derive(profile_store.REAL_DIR)
    return {
        "roles": result["roles"],
        "bullets": result["bullets"],
        "stubs_created": len(result["stubs_created"]),
        "stories_kept": len(result["stories_kept"]),
        "unsourced_metrics": result["unsourced_metrics"],
    }


@app.get("/api/guardrails")
def get_guardrails() -> dict:
    try:
        return {"markdown": profile_store.load_guardrails(),
                "editable": not profile_store.is_example()}
    except ProfileNotSetUp:
        return {"markdown": "", "editable": False}


@app.put("/api/guardrails")
def save_guardrails(payload: dict = Body(...)) -> dict:
    directory = _writable_dir()
    (directory / "guardrails.md").write_text(str(payload.get("markdown") or ""),
                                             encoding="utf-8")
    return {"saved": True}


@app.get("/api/stories")
def list_stories() -> list[dict]:
    """Every story, lightweight - enough for a list view, no bodies."""
    return [
        {
            "id": s.id,
            "title": s.title,
            "status": s.status.value,
            "role": s.role,
            "metric": s.metric,
            "tags": s.tags,
            "is_empty": s.is_empty(),
        }
        for s in _active_stories()
    ]


@app.get("/api/stories/{story_id}")
def get_story(story_id: str) -> dict:
    story = _find_story(story_id, _active_stories())
    if story is None:
        raise HTTPException(404, f"Unknown story {story_id!r}")
    return story.model_dump(mode="json")


@app.post("/api/stories/{story_id}/verify")
def verify_story(story_id: str) -> dict:
    directory = _writable_dir()
    story = _find_story(story_id, profile_store.load_stories(directory))
    if story is None:
        raise HTTPException(404, f"Unknown story {story_id!r}")
    verified = story.model_copy(update={"status": StoryStatus.VERIFIED,
                                        "verified": date.today().isoformat()})
    profile_store.save_story(verified, directory)
    return verified.model_dump(mode="json")


@app.get("/api/story-additions")
def list_additions() -> list[dict]:
    """Story additions proposed by past answers and not yet decided on, each with
    the story as it stands now so the two can be compared."""
    stories = {s.id: s for s in _active_stories()}
    return [
        {**p, "story": stories[p["patch"]["story_id"]].model_dump(mode="json")
         if p["patch"]["story_id"] in stories else None}
        for p in db.pending_patches(profile_store.kind())
    ]


@app.post("/api/story-additions/{run_id}/accept")
def accept_addition(run_id: str, payload: dict = Body(...)) -> dict:
    directory = _writable_dir()
    pending = db.pending_patch(run_id, "own")
    if pending is None:
        raise HTTPException(404, "No pending story addition for that answer.")
    try:
        patch = StoryPatch.model_validate(pending["patch"])
        current = _find_story(patch.story_id, profile_store.load_stories(directory))
        story = patches.apply_patch(current, patch, payload.get("sections") or [],
                                    f"transcript:{run_id}")
        profile_store.save_story(story, directory)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.record_decision(run_id, "accepted")
    return story.model_dump(mode="json")


@app.post("/api/story-additions/{run_id}/dismiss")
def dismiss_addition(run_id: str) -> dict:
    if db.pending_patch(run_id, profile_store.kind()) is None:
        raise HTTPException(404, "No pending story addition for that answer.")
    db.record_decision(run_id, "dismissed")
    return {"dismissed": run_id}


@app.get("/api/questions")
def list_questions(include_disabled: bool = False) -> list[dict]:
    """The merged bank. `include_disabled` shows questions you've turned off."""
    core_ids = {q.id for q in questions.load_core()}
    return [
        {**q.model_dump(), "is_core": q.id in core_ids}
        for q in questions.load_questions(include_disabled=include_disabled)
    ]


@app.put("/api/questions/{question_id}")
def save_question(question_id: str, question: Question) -> dict:
    """Create or edit a question.

    Edits to a shipped question are written to your own layer rather than to the
    committed bank, so the repo stays pristine and a pull never fights you.
    """
    _writable_dir()
    if question.id != question_id:
        raise HTTPException(400, "id in the body must match the URL")

    if question.source == "core" and question.enabled:
        question = question.model_copy(update={"source": "custom"})

    saved = questions.upsert(question)
    return saved.model_dump()


@app.post("/api/questions")
def add_question(question: Question) -> dict:
    _writable_dir()
    existing = {q.id for q in questions.load_questions(include_disabled=True)}
    if not question.id or question.id in existing:
        question = question.model_copy(
            update={"id": questions.slug(question.text, existing)})
    return questions.upsert(question.model_copy(update={"source": "custom"})).model_dump()


@app.post("/api/questions/bulk")
def add_questions(payload: list[Question] = Body(...)) -> dict:
    """Accept a batch, which is how generated questions are kept."""
    _writable_dir()
    saved = questions.upsert_many(payload)
    return {"saved": [q.model_dump() for q in saved]}


@app.delete("/api/questions/{question_id}")
def remove_question(question_id: str) -> dict:
    _writable_dir()
    if not questions.delete(question_id):
        raise HTTPException(404, f"Unknown question {question_id!r}")
    return {"deleted": question_id}


@app.post("/api/jd/generate")
def generate_from_jd(payload: dict = Body(...)) -> dict:
    """Draft questions from a job description. Nothing is saved."""
    try:
        drafted, completion = jd.generate(payload.get("text", ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return {
        "role_summary": drafted.role_summary,
        "questions": [q.model_dump() for q in drafted.questions],
        "cost_usd": round(completion.cost_usd, 4),
    }


@app.get("/api/questions/next")
def next_question(exclude: str = "") -> dict:
    """A question to ask, avoiding ids listed in `exclude` (comma separated)."""
    asked = {qid for qid in exclude.split(",") if qid}
    question = questions.pick_question(exclude=asked)
    if question is None:
        raise HTTPException(404, "No questions available.")
    return question.model_dump()


@app.post("/api/answer")
async def submit_answer(audio: UploadFile, question_id: str = Form(...)) -> dict:
    """Accept a recorded answer and start processing it.

    Returns immediately with a run id; the browser follows progress on
    /api/runs/{id}/events. Transcription is far too slow to block a request on.
    """
    if questions.get_question(question_id) is None:
        raise HTTPException(400, f"Unknown question {question_id!r}")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(audio.filename or "answer.webm").suffix or ".webm"
    path = AUDIO_DIR / f"{question_id}-{uuid.uuid4().hex[:8]}{suffix}"
    path.write_bytes(await audio.read())

    run = runs.create_run(question_id, path)
    asyncio.create_task(runs.process(run))
    return {"run_id": run.id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = runs.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Unknown run")
    return run.snapshot()


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> EventSourceResponse:
    """Stage changes for one run, as server-sent events."""
    async def stream():
        async for event in runs.events(run_id):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(stream())


@app.get("/api/history")
def get_history(question_id: str = "", limit: int = 20) -> dict:
    """Past answers, newest first. Filter by question to watch one improve."""
    return {
        "runs": db.history(question_id or None, limit),
        "totals": db.totals(),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
