"""Route tests. Each test gets its own profile folders and database, so the real
profile/, profile.example/ and runtime/app.db are never touched."""

from __future__ import annotations

import shutil
from datetime import date

import pytest
from fastapi.testclient import TestClient

import main
from core import db, profile_store

SAMPLE_CV = (profile_store.EXAMPLE_DIR / "cv.md").read_text(encoding="utf-8")


@pytest.fixture
def client(monkeypatch, tmp_path):
    example = tmp_path / "example"
    shutil.copytree(profile_store.EXAMPLE_DIR, example)
    monkeypatch.setattr(profile_store, "EXAMPLE_DIR", example)
    monkeypatch.setattr(profile_store, "REAL_DIR", tmp_path / "profile")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    return TestClient(main.app)


@pytest.fixture
def own_profile(client):
    """A real (non-sample) profile, built from the sample CV's text."""
    assert client.put("/api/cv", json={"markdown": SAMPLE_CV}).status_code == 200
    assert client.post("/api/cv/build").status_code == 200
    return client


def first_story_id(client) -> str:
    return client.get("/api/stories").json()[0]["id"]


class TestStories:
    def test_one_story_in_full(self, client):
        story = client.get("/api/stories/vanta-idempotency-keys").json()
        assert story["title"]
        assert "claim" in story and "situation" in story

    def test_unknown_story_is_404(self, client):
        assert client.get("/api/stories/nope").status_code == 404

    def test_verify_on_sample_profile_is_refused(self, client):
        """The sample lives in a committed folder. The UI must not edit it."""
        before = (profile_store.EXAMPLE_DIR / "stories" /
                  "vanta-idempotency-keys.md").read_text(encoding="utf-8")
        response = client.post("/api/stories/vanta-idempotency-keys/verify")
        assert response.status_code == 409
        after = (profile_store.EXAMPLE_DIR / "stories" /
                 "vanta-idempotency-keys.md").read_text(encoding="utf-8")
        assert before == after

    def test_verify_stamps_today(self, own_profile):
        story_id = first_story_id(own_profile)
        story = own_profile.post(f"/api/stories/{story_id}/verify").json()
        assert story["status"] == "verified"
        assert story["verified"] == date.today().isoformat()


def patch_for(story_id: str) -> dict:
    return {"story_id": story_id, "is_new": False, "situation": "Sellers double-posted.",
            "task": "", "action": "Added a dedup key.", "result": "", "reflection": ""}


class TestStoryAdditions:
    def test_listed_with_the_current_story(self, own_profile, record_run):
        story_id = first_story_id(own_profile)
        record_run(db.DB_PATH, "r1", patch=patch_for(story_id))
        [item] = own_profile.get("/api/story-additions").json()
        assert item["run_id"] == "r1"
        assert item["story"]["id"] == story_id
        assert own_profile.get("/api/profile").json()["pending_additions"] == 1

    def test_accept_writes_only_the_chosen_sections(self, own_profile, record_run):
        story_id = first_story_id(own_profile)
        record_run(db.DB_PATH, "r1", patch=patch_for(story_id))
        response = own_profile.post("/api/story-additions/r1/accept",
                                    json={"sections": ["action"]})
        assert response.status_code == 200
        story = own_profile.get(f"/api/stories/{story_id}").json()
        assert story["action"] == "Added a dedup key."
        assert story["situation"] == ""
        assert story["status"] == "draft"
        assert own_profile.get("/api/story-additions").json() == []

    def test_accepting_twice_is_404(self, own_profile, record_run):
        story_id = first_story_id(own_profile)
        record_run(db.DB_PATH, "r1", patch=patch_for(story_id))
        own_profile.post("/api/story-additions/r1/accept", json={"sections": ["action"]})
        again = own_profile.post("/api/story-additions/r1/accept",
                                 json={"sections": ["action"]})
        assert again.status_code == 404

    def test_accept_with_no_sections_is_400(self, own_profile, record_run):
        record_run(db.DB_PATH, "r1", patch=patch_for(first_story_id(own_profile)))
        response = own_profile.post("/api/story-additions/r1/accept",
                                    json={"sections": []})
        assert response.status_code == 400

    def test_dismiss_clears_without_writing(self, own_profile, record_run):
        story_id = first_story_id(own_profile)
        record_run(db.DB_PATH, "r1", patch=patch_for(story_id))
        assert own_profile.post("/api/story-additions/r1/dismiss").status_code == 200
        assert own_profile.get("/api/story-additions").json() == []
        assert own_profile.get(f"/api/stories/{story_id}").json()["action"] == ""
