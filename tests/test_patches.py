"""Tests for merging an AI-proposed story addition into the story bank."""

from __future__ import annotations

import pytest

from core.patches import apply_patch
from core.schemas import Story, StoryPatch, StoryStatus

STUB = Story(id="queue", title="Queue", status="stub", claim="Built a queue.")
PATCH = StoryPatch(story_id="queue", is_new=False, situation="Sellers double-posted.",
                   action="Added a dedup key.", result="")


def test_only_chosen_sections_are_written():
    story = apply_patch(STUB, PATCH, ["action"], "transcript:r1")
    assert story.action == "Added a dedup key."
    assert story.situation == ""


def test_an_empty_proposal_never_blanks_a_section():
    filled = STUB.model_copy(update={"result": "Zero duplicates."})
    story = apply_patch(filled, PATCH, ["action", "result"], "transcript:r1")
    assert story.result == "Zero duplicates."


def test_a_stub_becomes_a_draft():
    assert apply_patch(STUB, PATCH, ["action"], "t").status == StoryStatus.DRAFT


def test_changing_a_verified_story_returns_it_to_draft():
    """Its wording is no longer what a human confirmed."""
    verified = STUB.model_copy(update={"status": StoryStatus.VERIFIED,
                                       "verified": "2026-09-01"})
    story = apply_patch(verified, PATCH, ["action"], "t")
    assert story.status == StoryStatus.DRAFT
    assert story.verified is None


def test_the_claim_and_metadata_are_kept():
    story = apply_patch(STUB, PATCH, ["action"], "t")
    assert story.claim == "Built a queue."
    assert story.source == STUB.source


def test_missing_story_is_created_as_a_draft():
    """A proposal can outlive its story, or name a brand new one."""
    new = StoryPatch(story_id="retry-queue-design", is_new=True, action="Did it.")
    story = apply_patch(None, new, ["action"], "transcript:r9")
    assert story.id == "retry-queue-design"
    assert story.title == "Retry queue design"
    assert story.source == "transcript:r9"
    assert story.status == StoryStatus.DRAFT


def test_unknown_section_is_rejected():
    with pytest.raises(ValueError, match="claim"):
        apply_patch(STUB, PATCH, ["claim"], "t")


def test_nothing_to_write_is_rejected():
    with pytest.raises(ValueError, match="nothing"):
        apply_patch(STUB, PATCH, ["result"], "t")


def test_a_proposed_story_id_must_be_a_plain_slug():
    """The id becomes a file name. A model-chosen '../x' would write outside the
    stories folder."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        StoryPatch(story_id="../../main", is_new=True, action="x")
