"""Tests for retrieval: which stories the model gets to see."""

from __future__ import annotations

from core import profile_store, questions, retrieve
from core.schemas import Question, Story

EXAMPLE = profile_store.EXAMPLE_DIR
STORIES = profile_store.load_stories(EXAMPLE)


def q(text: str, *tags: str) -> Question:
    return Question(id="t", text=text, tags=list(tags))


class TestRanking:
    def test_the_obviously_right_story_wins(self):
        question = questions.get_question("idempotency")
        top = retrieve.pick_stories(question, STORIES)[0]
        assert top.story.id == "vanta-idempotency-keys"

    def test_each_seeded_question_finds_its_story(self):
        """The example profile and the core bank were written to line up. If
        this drifts, the demo stops demonstrating anything."""
        expected = {
            "idempotency": "vanta-idempotency-keys",
            "production-incident": "vanta-double-charge-incident",
            "queue-backpressure": "rota-queue-backpressure",
        }
        for qid, story_id in expected.items():
            top = retrieve.pick_stories(questions.get_question(qid), STORIES)[0]
            assert top.story.id == story_id, f"{qid} retrieved {top.story.id}"

    def test_an_exact_tag_beats_loose_word_overlap(self):
        tagged = Story(id="tagged", title="Tagged", tags=["idempotency"])
        wordy = Story(id="wordy", title="Retry and key and lock and publish",
                      claim="retry key lock publish duplicate charge")
        ranked = retrieve.pick_stories(q("idempotency?", "idempotency"),
                                       [wordy, tagged])
        assert ranked[0].story.id == "tagged"

    def test_aliases_rescue_a_question_that_uses_other_words(self):
        """The whole point of aliases: a question says "exactly-once" and a
        story tagged only "idempotency" still has to answer to it."""
        story = Story(id="s", title="S", tags=["idempotency"],
                      aliases=["exactly-once"])
        scored = retrieve.score_story(q("How do you get exactly-once?",
                                        "exactly-once"), story)
        assert scored.score >= retrieve.ALIAS_HIT
        assert "exactly-once" in scored.matched

    def test_matched_terms_are_reported(self):
        """Being able to see why a story was chosen is what keeps this
        debuggable without a vector store to inspect."""
        question = questions.get_question("idempotency")
        assert retrieve.pick_stories(question, STORIES)[0].matched


class TestCoverage:
    def test_stubs_compete_with_filled_stories(self):
        """A stub still knows what you claim, which is enough to notice you
        never said the number on your own CV."""
        ranked = retrieve.pick_stories(
            q("How do you scale a large table?", "partitioning"), STORIES)
        assert ranked[0].story.status.value == "stub"
        assert ranked[0].story.id == "vanta-ledger-partitioning"

    def test_a_question_matching_nothing_still_gets_material(self):
        """Returning nothing guarantees empty feedback, which is the one
        outcome that makes the tool pointless."""
        ranked = retrieve.pick_stories(q("Describe a llama.", "llama"), STORIES)
        assert len(ranked) >= min(retrieve.MIN_STORIES, len(STORIES))

    def test_never_returns_more_than_top_k(self):
        ranked = retrieve.pick_stories(questions.get_question("idempotency"),
                                       STORIES, top_k=2)
        assert len(ranked) == 2

    def test_empty_bank_does_not_crash(self):
        assert retrieve.pick_stories(q("anything", "x"), []) == []


class TestBullets:
    def test_picks_relevant_cv_claims(self):
        profile = profile_store.load_profile(EXAMPLE)
        bullets = retrieve.pick_bullets(questions.get_question("idempotency"),
                                        profile)
        assert bullets[0].id == "vanta-idempotency-keys"

    def test_capped(self):
        profile = profile_store.load_profile(EXAMPLE)
        assert len(retrieve.pick_bullets(questions.get_question("idempotency"),
                                         profile, top_k=2)) == 2


class TestTokens:
    def test_stopwords_and_short_words_are_dropped(self):
        assert retrieve.tokens("How did you do the a of it") == set()

    def test_keeps_technical_words(self):
        assert "idempotency" in retrieve.tokens("Explain idempotency to me")
