"""Tests for the two-layer question bank and JD generation.

The committed `questions/core.yaml` must never be modified by anything a user
does, so several of these assert on its contents staying put.
"""

from __future__ import annotations

import pytest

from core import jd, questions as Q
from core.schemas import GeneratedQuestions, Question


@pytest.fixture
def bank(tmp_path):
    """An empty profile directory to use as the user layer."""
    (tmp_path / "cv.md").write_text("# Someone\n", encoding="utf-8")
    return tmp_path


CORE_TEXT = Q.CORE_BANK.read_text(encoding="utf-8")


class TestLayering:
    def test_core_bank_loads_without_a_profile(self, bank):
        assert len(Q.load_questions(bank)) >= 20

    def test_your_layer_overrides_core_by_id(self, bank):
        Q.upsert(Question(id="idempotency", text="Rewritten", seconds=90), bank)
        merged = {q.id: q for q in Q.load_questions(bank)}
        assert merged["idempotency"].text == "Rewritten"
        assert merged["idempotency"].seconds == 90

    def test_editing_never_touches_the_committed_bank(self, bank):
        """A pull must not fight your edits, and your edits must not end up in
        everyone else's repo."""
        Q.upsert(Question(id="idempotency", text="Rewritten"), bank)
        assert Q.CORE_BANK.read_text(encoding="utf-8") == CORE_TEXT

    def test_override_does_not_duplicate_the_question(self, bank):
        before = len(Q.load_questions(bank))
        Q.upsert(Question(id="idempotency", text="Rewritten"), bank)
        assert len(Q.load_questions(bank)) == before


class TestRemoval:
    def test_removing_a_shipped_question_hides_it(self, bank):
        Q.delete("hardest-bug", bank)
        assert "hardest-bug" not in {q.id for q in Q.load_questions(bank)}

    def test_a_removed_question_is_tombstoned_not_erased(self, bank):
        Q.delete("hardest-bug", bank)
        tomb = Q.get_question("hardest-bug", bank)
        assert tomb is not None and tomb.enabled is False
        assert Q.CORE_BANK.read_text(encoding="utf-8") == CORE_TEXT

    def test_removing_an_edited_shipped_question_does_not_restore_it(self, bank):
        """Dropping the override would resurrect the shipped version, so a
        button labelled Remove would restore the original instead."""
        Q.upsert(Question(id="idempotency", text="My version"), bank)
        Q.delete("idempotency", bank)

        assert "idempotency" not in {q.id for q in Q.load_questions(bank)}
        assert Q.get_question("idempotency", bank).text == "My version"

    def test_removing_your_own_question_erases_it(self, bank):
        Q.upsert(Question(id="mine", text="Mine", source="custom"), bank)
        Q.delete("mine", bank)
        assert Q.get_question("mine", bank) is None

    def test_removing_something_unknown_reports_failure(self, bank):
        assert Q.delete("no-such-question", bank) is False

    def test_a_removed_question_is_never_asked(self, bank):
        """pick_question falls back to the whole bank when everything is used,
        so a disabled question must be excluded from that fallback too."""
        for question in Q.load_questions(bank):
            if question.id != "idempotency":
                Q.delete(question.id, bank)
        Q.delete("idempotency", bank)
        assert Q.pick_question(bank) is None


class TestSlugs:
    def test_derived_from_the_text(self):
        assert Q.slug("How did you implement idempotency?") == "how-did-you-implement-idempotency"

    def test_avoids_collisions(self):
        taken = {"how-did-you-implement-idempotency"}
        assert Q.slug("How did you implement idempotency?", taken).endswith("-2")

    def test_never_empty(self):
        assert Q.slug("???")


class TestJdGeneration:
    def test_a_stub_of_a_posting_is_rejected_before_spending_anything(self, bank,
                                                                      fake_llm):
        """Two lines of a job ad produce generic questions. Better to refuse."""
        client = fake_llm(data={})
        with pytest.raises(ValueError, match="too short"):
            jd.generate("Backend engineer wanted.", bank)
        assert client.calls == []

    def test_the_model_sees_the_posting_and_the_candidate(self, bank, fake_llm):
        """Questions have to sit in the overlap, which needs both halves."""
        client = fake_llm(data=GeneratedQuestions(role_summary="x").model_dump())
        jd.generate("Own our Celery worker fleet. " * 10, bank)

        payload = client.calls[0]["payload"]
        assert "Celery worker fleet" in payload
        assert "## The candidate" in payload

    def test_generated_ids_never_collide_with_the_existing_bank(self, bank,
                                                                fake_llm):
        """The model cannot see the bank, so a collision would silently
        overwrite a question you already had."""
        drafted = GeneratedQuestions(
            role_summary="x",
            questions=[Question(id="idempotency", text="A different question")],
        )
        fake_llm(data=drafted.model_dump())
        result, _ = jd.generate("Own our Celery worker fleet. " * 10, bank)

        assert result.questions[0].id != "idempotency"

    def test_generated_questions_are_marked_as_such(self, bank, fake_llm):
        drafted = GeneratedQuestions(
            role_summary="x",
            questions=[Question(id="q1", text="Something", source="core")],
        )
        fake_llm(data=drafted.model_dump())
        result, _ = jd.generate("Own our Celery worker fleet. " * 10, bank)
        assert result.questions[0].source == "jd"

    def test_nothing_is_saved_by_generating(self, bank, fake_llm):
        """Review is the point. A bank that fills itself is worse than a small
        one."""
        drafted = GeneratedQuestions(
            role_summary="x", questions=[Question(id="q1", text="Something")])
        fake_llm(data=drafted.model_dump())
        jd.generate("Own our Celery worker fleet. " * 10, bank)

        assert Q.load_user(bank) == []


class TestBulkAdd:
    def test_adds_only_what_was_chosen(self, bank):
        chosen = [Question(id="a", text="A", source="jd"),
                  Question(id="b", text="B", source="jd")]
        Q.upsert_many(chosen, bank)
        assert {q.id for q in Q.load_user(bank)} == {"a", "b"}

    def test_is_one_write_not_one_per_question(self, bank):
        Q.upsert_many([Question(id=f"q{i}", text=f"Q{i}") for i in range(5)], bank)
        assert len(Q.load_user(bank)) == 5

    def test_keeps_questions_already_in_your_layer(self, bank):
        Q.upsert(Question(id="existing", text="Existing", source="custom"), bank)
        Q.upsert_many([Question(id="new", text="New", source="jd")], bank)
        assert {q.id for q in Q.load_user(bank)} == {"existing", "new"}
