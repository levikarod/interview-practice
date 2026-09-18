"""FastAPI entry point.

Routes only. All logic lives in `core/` so it stays testable without a server.

Run: uv run uvicorn main:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core import profile_store
from core.profile_store import ProfileNotSetUp

REPO_ROOT = Path(__file__).resolve().parent
WEB_DIR = REPO_ROOT / "web"

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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
