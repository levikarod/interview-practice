"""Delivery metrics, computed in code.

Pace and hesitation are arithmetic over word timings. Asking a model for them
would be slower, costlier and less reliable than counting, and it would put a
number in the feedback that nobody can reproduce. This module has no model call
and no I/O, which is also what makes it trivially testable.

FILLERS covers single words plus the two-word phrases people actually use. It is
deliberately conservative: "like" and "so" are only fillers some of the time, and
over-flagging normal speech makes the whole report easy to dismiss.

A pause is measured as the gap between the end of one word and the start of the
next, which is why word timestamps are requested during transcription.
"""

from __future__ import annotations

import re

from core.schemas import AnswerMetrics, Transcript

FILLERS: tuple[str, ...] = (
    "um", "uh", "erm", "er", "hmm", "mmm",
    "basically", "literally", "actually", "obviously",
    "you know", "i mean", "sort of", "kind of", "i guess",
)

MIN_PAUSE_S = 1.0


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z' ]+", " ", text.lower())


def count_fillers(text: str) -> dict[str, int]:
    """Count filler words and phrases. Longer phrases are matched first so
    "you know" is not also counted as two separate words."""
    haystack = f" {' '.join(_normalise(text).split())} "
    counts: dict[str, int] = {}
    for filler in sorted(FILLERS, key=len, reverse=True):
        hits = len(re.findall(rf"(?<= ){re.escape(filler)}(?= )", haystack))
        if hits:
            counts[filler] = hits
            haystack = re.sub(rf"(?<= ){re.escape(filler)}(?= )", " ", haystack)
    return counts


def longest_pause(transcript: Transcript) -> float:
    """The largest silence between consecutive words, in seconds."""
    gaps = [
        round(nxt.start - cur.end, 2)
        for cur, nxt in zip(transcript.words, transcript.words[1:])
    ]
    biggest = max(gaps, default=0.0)
    return biggest if biggest >= MIN_PAUSE_S else 0.0


def measure(transcript: Transcript, limit_s: int | None = None) -> AnswerMetrics:
    """Delivery metrics for one answer."""
    word_count = len(transcript.words) or len(transcript.text.split())
    duration = transcript.duration_s

    wpm = round(word_count / (duration / 60)) if duration >= 1 else 0
    fillers = count_fillers(transcript.text)

    return AnswerMetrics(
        duration_s=round(duration, 1),
        word_count=word_count,
        words_per_minute=wpm,
        filler_count=sum(fillers.values()),
        fillers=fillers,
        longest_pause_s=longest_pause(transcript),
        overran=bool(limit_s and duration > limit_s + 1),
    )
