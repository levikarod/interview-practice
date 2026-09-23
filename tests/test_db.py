"""Tests for the practice log: previous attempts and pending story additions."""

from __future__ import annotations

from core import db


class TestLatestFeedback:
    def test_newest_attempt_at_that_question(self, record_run, tmp_path):
        path = tmp_path / "t.db"
        record_run(path, "r1", at=1.0, headline="old")
        record_run(path, "r2", at=2.0, headline="new")
        record_run(path, "r3", at=3.0, headline="other", question_id="other")
        assert db.latest_feedback("idempotency", path)["headline"] == "new"

    def test_none_when_never_answered(self, tmp_path):
        assert db.latest_feedback("idempotency", tmp_path / "t.db") is None


PATCH = {"story_id": "queue", "is_new": False, "situation": "", "task": "",
         "action": "Added a dedup key.", "result": "", "reflection": ""}


class TestPendingPatches:
    def test_a_run_with_a_patch_is_pending(self, record_run, tmp_path):
        path = tmp_path / "t.db"
        record_run(path, "r1", patch=PATCH)
        pending = db.pending_patches(path)
        assert [p["run_id"] for p in pending] == ["r1"]
        assert pending[0]["patch"]["action"] == "Added a dedup key."

    def test_a_run_without_a_patch_is_not(self, record_run, tmp_path):
        path = tmp_path / "t.db"
        record_run(path, "r1", patch=None)
        assert db.pending_patches(path) == []

    def test_a_decision_clears_it_for_good(self, record_run, tmp_path):
        """Accepted or dismissed, an addition must never come back."""
        path = tmp_path / "t.db"
        record_run(path, "r1", patch=PATCH)
        record_run(path, "r2", patch=PATCH)
        db.record_decision("r1", "accepted", path)
        db.record_decision("r2", "dismissed", path)
        assert db.pending_patches(path) == []
        assert db.pending_patch("r1", path) is None

    def test_newest_first(self, record_run, tmp_path):
        path = tmp_path / "t.db"
        record_run(path, "old", at=1.0, patch=PATCH)
        record_run(path, "new", at=2.0, patch=PATCH)
        assert [p["run_id"] for p in db.pending_patches(path)] == ["new", "old"]
