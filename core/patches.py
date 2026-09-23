"""Merging an AI-proposed story addition into a story.

The analysis call proposes STAR detail it heard in an answer. Nothing reaches the
story bank until a person picks which sections to keep, so this is a pure
function: story, proposal, and chosen sections in, the updated story out. The
caller does the writing.

Any accepted change lands as `draft`. A verified story that changes goes back to
draft too, because its wording is no longer what a human confirmed. The claim
and metadata are never touched: the claim comes from the CV, not a transcript.
"""

from __future__ import annotations

from core.schemas import Story, StoryPatch, StoryStatus

PATCH_SECTIONS = ("situation", "task", "action", "result", "reflection")


def _title(story_id: str) -> str:
    return story_id.replace("-", " ").strip().capitalize() or story_id


def apply_patch(story: Story | None, patch: StoryPatch, sections: list[str],
                source: str) -> Story:
    unknown = sorted(set(sections) - set(PATCH_SECTIONS))
    if unknown:
        raise ValueError(f"Cannot apply sections {', '.join(unknown)}.")

    updates = {name: getattr(patch, name).strip() for name in sections
               if getattr(patch, name).strip()}
    if not updates:
        raise ValueError("The chosen sections have nothing to add.")

    base = story or Story(id=patch.story_id, title=_title(patch.story_id),
                          source=source)
    return base.model_copy(update={**updates, "status": StoryStatus.DRAFT,
                                   "verified": None})
