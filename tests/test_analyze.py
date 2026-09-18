"""Tests for the analysis call: what the model is shown, and what we accept back.

The model itself is faked. These cover the contract around it.
"""

from __future__ import annotations

import pytest

from core import analyze, profile_store, questions
from core.schemas import Feedback, StarCoverage, Story, Transcript

EXAMPLE = profile_store.EXAMPLE_DIR
QUESTION = questions.get_question("idempotency")
SAID = Transcript(text="I added an idempotency key header.", duration_s=30.0)

VALID = Feedback(
    missed_points=[], risky_claims=[], strengths=["s"], fixes=["f"],
    star_coverage=StarCoverage(situation=True, task=True, action=True,
                               result=True, reflection=True),
).model_dump()


@pytest.fixture
def payload():
    return analyze.build_payload(QUESTION, SAID,
                                 profile_store.load_stories(EXAMPLE), EXAMPLE)


class TestPayload:
    def test_contains_the_question_and_the_answer(self, payload):
        assert QUESTION.text in payload
        assert "idempotency key header" in payload

    def test_leads_with_the_most_relevant_story(self, payload):
        assert "vanta-idempotency-keys" in payload

    def test_includes_guardrails(self, payload):
        """Without these, risky_claims has nothing to check against."""
        assert "ledger schema" in payload

    def test_says_when_there_are_no_guardrails(self, tmp_path):
        """An empty guardrails file must not read as 'anything goes'."""
        (tmp_path / "cv.md").write_text("# X\n", encoding="utf-8")
        text = analyze.build_payload(QUESTION, SAID, [], tmp_path)
        assert "none set" in text.lower()

    def test_marks_stubs_so_detail_is_not_invented(self):
        """A stub carries only a claim. The model has to be told that, or it
        will confabulate STAR detail that was never there."""
        stub = Story(id="s", title="S", status="stub", tags=["idempotency"],
                     claim="Did a thing.")
        text = analyze.build_payload(QUESTION, SAID, [stub], EXAMPLE)
        assert "do not invent detail" in text.lower()

    def test_empty_transcript_is_stated_not_blank(self):
        text = analyze.build_payload(QUESTION, Transcript(text="  "), [], EXAMPLE)
        assert "nothing was transcribed" in text

    def test_stays_small(self, payload):
        """Our content is a few thousand tokens against tens of thousands of
        harness overhead. If this balloons, something is being dumped in."""
        assert len(payload) < 40_000


class TestCall:
    def test_sends_the_schema_and_the_system_prompt(self, fake_llm):
        client = fake_llm(data=VALID)
        analyze.analyse(QUESTION, SAID, [], directory=EXAMPLE)

        call = client.calls[0]
        assert call["schema"]["title"] == "Feedback"
        assert "missed_points" in call["schema"]["properties"]
        assert "had available and did not say" in call["system"].lower()

    def test_payload_goes_as_payload_not_instruction(self, fake_llm):
        """The real client puts payload on stdin. Keeping the transcript out of
        the instruction is what makes that work."""
        client = fake_llm(data=VALID)
        analyze.analyse(QUESTION, SAID, [], directory=EXAMPLE)
        assert "idempotency key header" in client.calls[0]["payload"]
        assert "idempotency key header" not in client.calls[0]["instruction"]

    def test_returns_validated_feedback_and_the_completion(self, fake_llm):
        fake_llm(data=VALID)
        feedback, completion = analyze.analyse(QUESTION, SAID, [],
                                               directory=EXAMPLE)
        assert isinstance(feedback, Feedback)
        assert completion.model == "fake"

    def test_missing_structured_output_is_an_error(self, fake_llm):
        """Prose instead of an object means the call did not do its job.
        Failing loudly beats storing empty feedback."""
        fake_llm(text="Sure! Here's some advice.", data=None)
        with pytest.raises(ValueError, match="structured output"):
            analyze.analyse(QUESTION, SAID, [], directory=EXAMPLE)

    def test_malformed_output_is_rejected(self, fake_llm):
        fake_llm(data={"missed_points": "not a list"})
        with pytest.raises(Exception):
            analyze.analyse(QUESTION, SAID, [], directory=EXAMPLE)


class TestSchemaConstraints:
    def test_limits_are_in_the_schema_not_the_prompt(self):
        """Asking politely for five bullets is not a constraint. These are."""
        schema = Feedback.model_json_schema()["properties"]
        assert schema["fixes"]["maxItems"] == 5
        assert schema["missed_points"]["maxItems"] == 6
        assert schema["strengths"]["maxItems"] == 3

    def test_story_patch_is_optional(self):
        """Most answers add nothing new, and a forced patch would invent one."""
        assert "story_patch" not in Feedback.model_json_schema().get("required", [])

    def test_a_missed_point_must_cite_a_story(self):
        """Untraceable advice is the generic coaching this tool exists to
        avoid."""
        defs = Feedback.model_json_schema()["$defs"]["MissedPoint"]
        assert set(defs["required"]) == {"point", "source_story_id"}
