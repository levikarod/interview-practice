"""FastAPI entry point.

Routes only. All logic lives in `core/` so it stays testable without a server.

Run: uv run uvicorn main:app --reload
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import Body, FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from core import db, jd, profile_store, questions, runs, transcribe
from core.schemas import Question
from core.profile_store import ProfileNotSetUp

REPO_ROOT = Path(__file__).resolve().parent
WEB_DIR = REPO_ROOT / "web"
AUDIO_DIR = REPO_ROOT / "runtime" / "audio"

app = FastAPI(title="Interview Practice", version="0.1.0")


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
    }


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
        for s in profile_store.load_stories()
    ]


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
    if question.id != question_id:
        raise HTTPException(400, "id in the body must match the URL")

    if question.source == "core" and question.enabled:
        question = question.model_copy(update={"source": "custom"})

    saved = questions.upsert(question)
    return saved.model_dump()


@app.post("/api/questions")
def add_question(question: Question) -> dict:
    existing = {q.id for q in questions.load_questions(include_disabled=True)}
    if not question.id or question.id in existing:
        question = question.model_copy(
            update={"id": questions.slug(question.text, existing)})
    return questions.upsert(question.model_copy(update={"source": "custom"})).model_dump()


@app.post("/api/questions/bulk")
def add_questions(payload: list[Question] = Body(...)) -> dict:
    """Accept a batch, which is how generated questions are kept."""
    saved = questions.upsert_many(payload)
    return {"saved": [q.model_dump() for q in saved]}


@app.delete("/api/questions/{question_id}")
def remove_question(question_id: str) -> dict:
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


@app.get("/questions")
def questions_page() -> FileResponse:
    return FileResponse(WEB_DIR / "questions.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
