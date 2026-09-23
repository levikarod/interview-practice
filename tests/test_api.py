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


def upload(client, name: str, data: bytes, replace: bool = False):
    return client.post("/api/cv", files={"file": (name, data)},
                       data={"replace": "true" if replace else "false"})


class TestCvUpload:
    def test_formatted_markdown_needs_no_model_call(self, client):
        """The autouse guard fails any real model call, so a 200 proves none ran."""
        response = upload(client, "cv.md", SAMPLE_CV.encode())
        assert response.status_code == 200
        assert response.json()["markdown"].startswith("# Mara Okonjo")
        assert (profile_store.REAL_DIR / "cv.md").exists()

    def test_plain_text_is_converted_by_one_model_call(self, client, fake_llm):
        fake = fake_llm(text="# Ana Ruiz\n")
        response = upload(client, "cv.txt", b"Ana Ruiz, backend engineer.")
        assert response.json()["markdown"] == "# Ana Ruiz\n"
        assert len(fake.calls) == 1

    def test_an_existing_cv_is_not_replaced_without_asking(self, client):
        upload(client, "cv.md", SAMPLE_CV.encode())
        assert upload(client, "cv.md", SAMPLE_CV.encode()).status_code == 409
        assert upload(client, "cv.md", SAMPLE_CV.encode(), replace=True).status_code == 200

    def test_unsupported_file_is_400(self, client):
        assert upload(client, "cv.docx", b"PK").status_code == 400


class TestCvBuild:
    def test_save_then_build_makes_a_story_bank(self, client):
        client.put("/api/cv", json={"markdown": SAMPLE_CV})
        result = client.post("/api/cv/build").json()
        assert result["roles"] > 0
        assert result["stubs_created"] > 0
        profile = client.get("/api/profile").json()
        assert profile["is_example"] is False
        assert profile["needs_ingest"] is False

    def test_cv_without_roles_is_rejected_before_anything_is_written(self, client):
        """Otherwise the profile reads as ready with nothing in it."""
        client.put("/api/cv", json={"markdown": "# Ana Ruiz\n\nNo roles here.\n"})
        response = client.post("/api/cv/build")
        assert response.status_code == 422
        assert "Experience" in response.json()["detail"]
        assert not (profile_store.REAL_DIR / "cv.json").exists()

    def test_empty_cv_is_400(self, client):
        assert client.put("/api/cv", json={"markdown": "   "}).status_code == 400

    def test_building_with_no_cv_is_409(self, client):
        assert client.post("/api/cv/build").status_code == 409

    def test_get_returns_the_active_cv(self, client):
        assert client.get("/api/cv").json()["markdown"].startswith("# Mara Okonjo")


class TestGuardrails:
    def test_sample_profile_guardrails_are_read_only(self, client):
        before = (profile_store.EXAMPLE_DIR / "guardrails.md").read_text(encoding="utf-8")
        assert client.get("/api/guardrails").json()["editable"] is False
        assert client.put("/api/guardrails", json={"markdown": "x"}).status_code == 409
        after = (profile_store.EXAMPLE_DIR / "guardrails.md").read_text(encoding="utf-8")
        assert before == after

    def test_saved_on_your_own_profile(self, own_profile):
        own_profile.put("/api/guardrails", json={"markdown": "Never say I led it."})
        got = own_profile.get("/api/guardrails").json()
        assert got == {"markdown": "Never say I led it.", "editable": True}


class TestProfile:
    def test_reports_numbers_to_defend(self, own_profile):
        profile = own_profile.get("/api/profile").json()
        assert isinstance(profile["unsourced_metrics"], list)
        assert profile["pending_additions"] == 0
