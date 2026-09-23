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
