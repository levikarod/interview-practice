"""Tests for delivery metrics. Pure functions, no model, no I/O."""

from __future__ import annotations

import pytest

from core.metrics import count_fillers, longest_pause, measure
from core.schemas import Transcript, Word


def words(*spans: tuple[str, float, float]) -> list[Word]:
    return [Word(text=t, start=s, end=e) for t, s, e in spans]


class TestFillers:
    def test_counts_single_words(self):
        assert count_fillers("um so uh basically yes")["um"] == 1

    def test_a_phrase_is_not_also_counted_as_its_parts(self):
        """'you know' is one filler. Matching longest-first stops it being
        double counted, which would inflate the number people are judged on."""
        counts = count_fillers("you know, it was fine, you know")
        assert counts == {"you know": 2}

    def test_substrings_inside_real_words_are_not_matched(self):
        """'um' must not fire on 'number', or normal speech looks full of
        hesitation and the whole report becomes easy to dismiss."""
        assert count_fillers("the number of columns summed up") == {}

    def test_punctuation_and_case_do_not_hide_a_filler(self):
        assert count_fillers("Um, right. UH -- ok") == {"um": 1, "uh": 1}

    def test_clean_speech_scores_zero(self):
        assert count_fillers("I added a lock and a dedup key.") == {}


class TestPauses:
    def test_finds_the_largest_gap(self):
        t = Transcript(words=words(("a", 0, 1), ("b", 3.5, 4), ("c", 4.1, 5)))
        assert longest_pause(t) == 2.5

    def test_short_gaps_are_not_pauses(self):
        """Normal speech has sub-second gaps everywhere. Reporting them as
        pauses would be noise."""
        t = Transcript(words=words(("a", 0, 1), ("b", 1.2, 2)))
        assert longest_pause(t) == 0.0

    def test_no_words_is_not_an_error(self):
        assert longest_pause(Transcript()) == 0.0


class TestMeasure:
    def test_pace(self):
        t = Transcript(text="a b c d", words=words(*[(str(i), i, i + 1) for i in range(60)]),
                       duration_s=60.0)
        assert measure(t).words_per_minute == 60

    def test_a_very_short_clip_reports_no_pace(self):
        """Dividing by a fraction of a second produces a meaningless number."""
        t = Transcript(text="hi", words=words(("hi", 0, 0.3)), duration_s=0.3)
        assert measure(t).words_per_minute == 0

    @pytest.mark.parametrize("duration,limit,expected", [
        (100.0, 120, False),
        (120.5, 120, False),
        (125.0, 120, True),
    ])
    def test_overran_allows_a_second_of_slack(self, duration, limit, expected):
        """The recorder hard-stops at the limit, so landing a hair over is the
        timer, not the speaker."""
        t = Transcript(text="x", words=words(("x", 0, 1)), duration_s=duration)
        assert measure(t, limit).overran is expected

    def test_counts_words_without_timings(self):
        """Transcription can return text with no word timings; the word count
        should still be right."""
        assert measure(Transcript(text="one two three", duration_s=10)).word_count == 3
