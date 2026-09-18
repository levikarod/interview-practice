"""In-memory registry for in-flight answers, and the pipeline that processes one.

An answer takes tens of seconds: transcription is slow, and the analysis call
will be slower. Rather than block a request that long, POST /api/answer returns a
run id immediately and the browser watches stage changes over SSE.

Each run owns an asyncio.Queue. The pipeline pushes stage events onto it; the SSE
endpoint drains it. A queue rather than polling means the browser learns about a
stage change the moment it happens.

Every blocking step goes through asyncio.to_thread. faster-whisper and the
`claude` subprocess both block, and running either on the event loop would stall
the SSE stream until the work finished - which looks like a frontend bug and is
not one. This is the single async rule of the codebase.

State is deliberately in memory: one local user, and a practice run has no value
once its result is stored. Finished runs are kept briefly so a reconnecting
browser can still read the result, then evicted to bound memory.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from core import analyze as analyze_mod
from core import metrics as metrics_mod
from core import db, profile_store, questions, transcribe
from core.schemas import AnswerMetrics, Feedback, Transcript

MAX_FINISHED_RUNS = 20

STAGES = ("queued", "transcribing", "measuring", "analysing", "done", "error")


@dataclass
class Run:
    id: str
    question_id: str
    audio_path: Path
    stage: str = "queued"
    transcript: Transcript | None = None
    metrics: AnswerMetrics | None = None
    feedback: Feedback | None = None
    cost_usd: float = 0.0
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question_id": self.question_id,
            "stage": self.stage,
            "error": self.error,
            "transcript": self.transcript.model_dump() if self.transcript else None,
            "metrics": self.metrics.model_dump() if self.metrics else None,
            "feedback": self.feedback.model_dump() if self.feedback else None,
            "cost_usd": round(self.cost_usd, 4),
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1),
        }


_runs: dict[str, Run] = {}


def create_run(question_id: str, audio_path: Path) -> Run:
    run = Run(id=uuid.uuid4().hex[:12], question_id=question_id,
              audio_path=audio_path)
    _runs[run.id] = run
    _evict_old()
    return run


def get_run(run_id: str) -> Run | None:
    return _runs.get(run_id)


def _evict_old() -> None:
    finished = sorted(
        (r for r in _runs.values() if r.finished_at is not None),
        key=lambda r: r.finished_at or 0,
    )
    for run in finished[:-MAX_FINISHED_RUNS] if len(finished) > MAX_FINISHED_RUNS else []:
        _runs.pop(run.id, None)


async def _set_stage(run: Run, stage: str, **extra: Any) -> None:
    """Move the run to `stage` and publish it.

    Terminal stages carry the snapshot, taken after the stage is set. Passing a
    snapshot in from the caller silently captured the *previous* stage, because
    Python evaluates arguments before the call.
    """
    run.stage = stage
    if stage in ("done", "error"):
        run.finished_at = time.time()
        extra.setdefault("snapshot", run.snapshot())
    await run.queue.put({"stage": stage, **extra})


async def process(run: Run) -> None:
    """Transcribe, measure, publish. Runs as a background task."""
    try:
        question = questions.get_question(run.question_id)
        limit = question.seconds if question else None

        await _set_stage(run, "transcribing")
        profile = profile_store.load_profile()
        transcript = await asyncio.to_thread(
            transcribe.transcribe, run.audio_path, profile.tech_terms()
        )
        run.transcript = transcript

        if not transcript.text.strip():
            run.error = ("No speech was detected. Check the right microphone is "
                         "selected and try again.")
            await _set_stage(run, "error", error=run.error)
            return

        await _set_stage(run, "measuring")
        run.metrics = metrics_mod.measure(transcript, limit)

        if question is not None:
            await _set_stage(run, "analysing")
            feedback, completion = await asyncio.to_thread(
                analyze_mod.analyse, question, transcript
            )
            run.feedback = feedback
            run.cost_usd = completion.cost_usd

        db.save_run(run)
        await _set_stage(run, "done")
    except Exception as exc:
        run.error = str(exc)
        await _set_stage(run, "error", error=str(exc))


async def events(run_id: str) -> AsyncIterator[dict[str, Any]]:
    """Stage events for one run, for the SSE endpoint.

    Replays the current stage first so a browser that connects late, or
    reconnects, is never left waiting on an event that already fired.
    """
    run = get_run(run_id)
    if run is None:
        yield {"stage": "error", "error": "unknown run"}
        return

    yield {"stage": run.stage, "snapshot": run.snapshot()}
    if run.stage in ("done", "error"):
        return

    while True:
        event = await run.queue.get()
        yield event
        if event.get("stage") in ("done", "error"):
            return
