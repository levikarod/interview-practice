"""Tests for the answer pipeline.

Transcription is stubbed - these cover orchestration, not speech recognition,
and no test may load a Whisper model or make a model call.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from core import questions, runs
from core.schemas import Transcript, Word


@pytest.fixture(autouse=True)
def fake_analysis(monkeypatch):
    """Stub the analysis call. These tests cover orchestration, not the model."""
    from core.llm import Completion
    from core.schemas import Feedback, StarCoverage

    feedback = Feedback(
        headline="Tighten it.",
        missed_points=[], risky_claims=[], strengths=["clear"],
        star_coverage=StarCoverage(situation=True, task=False, action=True,
                                   result=True, reflection=False),
    )
    monkeypatch.setattr(
        runs.analyze_mod, "analyse",
        lambda *a, **k: (feedback, Completion(cost_usd=0.21, model="fake")),
    )
    return feedback


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    """Each test writes to its own database file, not runtime/app.db."""
    monkeypatch.setattr(runs.db, "DB_PATH", tmp_path / "test.db")


@pytest.fixture
def fake_transcribe(monkeypatch):
    """Replace transcription with a canned result."""
    def _install(text: str = "I added a per listing lock and a dedup key.",
                 duration: float = 30.0):
        def fake(audio_path, vocabulary=None, model_name=None):
            spans = [Word(text=w, start=i, end=i + 0.5)
                     for i, w in enumerate(text.split())]
            return Transcript(text=text, words=spans, duration_s=duration)
        monkeypatch.setattr(runs.transcribe, "transcribe", fake)
    return _install


async def drain(run) -> list[dict]:
    return [event async for event in runs.events(run.id)]


class TestPipeline:
    async def test_happy_path_stages(self, fake_transcribe, tmp_path):
        fake_transcribe()
        run = runs.create_run("idempotency", tmp_path / "a.webm")
        await runs.process(run)

        assert run.stage == "done"
        assert run.transcript.text.startswith("I added")
        assert run.metrics.word_count == 10
        assert run.feedback is not None
        assert run.cost_usd == 0.21

    async def test_a_retry_is_shown_the_previous_attempt(self, fake_transcribe,
                                                         tmp_path, monkeypatch,
                                                         fake_analysis):
        """Crediting what improved needs the last attempt in the same call."""
        from core.llm import Completion

        seen = []

        def capture(question, transcript, **kwargs):
            seen.append(kwargs.get("previous"))
            return fake_analysis, Completion(model="fake")

        monkeypatch.setattr(runs.analyze_mod, "analyse", capture)
        fake_transcribe()
        for _ in range(2):
            run = runs.create_run("idempotency", tmp_path / "a.webm")
            await runs.process(run)

        assert seen[0] is None
        assert seen[1]["headline"] == "Tighten it."

    async def test_a_run_records_which_profile_it_was_made_on(self, fake_transcribe,
                                                               tmp_path):
        fake_transcribe()
        run = runs.create_run("idempotency", tmp_path / "a.webm")
        await runs.process(run)
        assert run.profile in ("example", "own")
        assert run.profile == ("example" if runs.profile_store.is_example() else "own")

    async def test_done_event_reports_the_done_stage(self, fake_transcribe, tmp_path):
        """The snapshot used to be built before the stage was set, so the 'done'
        event carried stage 'measuring'. Anything trusting the embedded snapshot
        saw a run that never finished."""
        fake_transcribe()
        run = runs.create_run("idempotency", tmp_path / "a.webm")
        await runs.process(run)

        events = await drain(run)
        done = [e for e in events if e["stage"] == "done"]
        assert done, "no done event"
        assert done[-1]["snapshot"]["stage"] == "done"

    async def test_silence_is_reported_as_an_actionable_error(self, fake_transcribe,
                                                              tmp_path):
        """An empty transcript means a mic problem, not a broken app. The error
        has to say which."""
        fake_transcribe(text="   ")
        run = runs.create_run("idempotency", tmp_path / "a.webm")
        await runs.process(run)

        assert run.stage == "error"
        assert "microphone" in run.error.lower()

    async def test_the_error_snapshot_carries_the_error(self, fake_transcribe,
                                                        tmp_path):
        """run.error used to be assigned after the event was published, so the
        snapshot went out with error: null."""
        fake_transcribe(text="")
        run = runs.create_run("idempotency", tmp_path / "a.webm")
        await runs.process(run)

        events = await drain(run)
        assert events[-1]["snapshot"]["error"]

    async def test_a_transcription_failure_does_not_kill_the_server(self, monkeypatch,
                                                                    tmp_path):
        def explode(*_args, **_kwargs):
            raise RuntimeError("model file is corrupt")
        monkeypatch.setattr(runs.transcribe, "transcribe", explode)

        run = runs.create_run("idempotency", tmp_path / "a.webm")
        await runs.process(run)

        assert run.stage == "error"
        assert "corrupt" in run.error


class TestEvents:
    async def test_a_late_subscriber_still_gets_the_result(self, fake_transcribe,
                                                           tmp_path):
        """Processing can finish before the browser opens the stream. Replaying
        the current stage is what stops it hanging forever."""
        fake_transcribe()
        run = runs.create_run("idempotency", tmp_path / "a.webm")
        await runs.process(run)

        events = await drain(run)
        assert len(events) == 1
        assert events[0]["stage"] == "done"

    async def test_unknown_run_ends_the_stream(self):
        events = [e async for e in runs.events("nope")]
        assert events == [{"stage": "error", "error": "unknown run"}]


class TestQuestions:
    def test_core_bank_loads(self):
        bank = questions.load_questions()
        assert len(bank) >= 20
        assert all(q.tags for q in bank), "every question needs retrieval tags"

    def test_ids_are_unique(self):
        ids = [q.id for q in questions.load_questions()]
        assert len(ids) == len(set(ids))

    def test_pick_avoids_questions_already_asked(self):
        bank = questions.load_questions()
        asked = {q.id for q in bank[:-1]}
        picked = questions.pick_question(exclude=asked, rng=random.Random(0))
        assert picked.id == bank[-1].id

    def test_pick_recycles_once_everything_is_used(self):
        """A long session must keep working rather than running dry."""
        asked = {q.id for q in questions.load_questions()}
        assert questions.pick_question(exclude=asked) is not None
