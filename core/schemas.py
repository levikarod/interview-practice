"""The single source of truth for every structured shape in the app.

These models do double duty: `model_json_schema()` produces the schema handed to
`claude --json-schema`, and `model_validate()` checks what comes back. One
declaration, no drift between what we ask for and what we accept.

Constraints expressed here (list lengths, string lengths) are enforced by the
schema rather than requested politely in the prompt.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    """Base for anything sent to the model. `extra='forbid'` makes Pydantic emit
    `additionalProperties: false`, which structured outputs require."""

    model_config = ConfigDict(extra="forbid")



class StoryStatus(str, Enum):
    """A story's lifecycle. The whole product is moving stories rightwards.

    stub     - claim only, derived from a CV bullet. No STAR detail yet.
    draft    - STAR detail proposed by the AI from a transcript, unreviewed.
    verified - a human confirmed the wording and the facts.
    """

    STUB = "stub"
    DRAFT = "draft"
    VERIFIED = "verified"


class Story(Strict):
    """One interview story.

    The claim comes from a CV bullet. The STAR+R fields below it are empty on a
    stub and fill in as you answer questions about it.
    """

    id: str
    title: str
    status: StoryStatus = StoryStatus.STUB
    source: str = Field(
        default="cv",
        description="Where this came from: 'cv', 'transcript:<session-id>', "
                    "or 'import'.",
    )
    role: str | None = None
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(
        default_factory=list,
        description="Words a job description might use that should route here. "
                    "This is what makes tag retrieval survive vocabulary drift.",
    )
    metric: str | None = None
    verified: str | None = Field(
        default=None,
        description="ISO date on which a human confirmed the wording and facts.",
    )

    claim: str = ""
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    reflection: str = ""

    def is_empty(self) -> bool:
        """True when only the claim is populated - i.e. still a bare stub."""
        return not any([self.situation, self.task, self.action,
                        self.result, self.reflection])



class CvBullet(Strict):
    id: str
    text: str
    skills: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    metric: str | None = None
    metric_sourced: bool = Field(
        default=False,
        description="False when the bullet states a figure with no evidence "
                    "behind it. Those seed guardrails.md as numbers to defend.",
    )


class CvRole(Strict):
    id: str
    title: str
    org: str
    dates: str = ""
    scope: str = ""
    bullets: list[CvBullet] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)


class Profile(Strict):
    """Derived from cv.md. cv.md is the source of truth; this is a cache."""

    name: str = ""
    headline: str = ""
    summary: str = ""
    roles: list[CvRole] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)

    def tech_terms(self) -> list[str]:
        """Vocabulary hint for faster-whisper's `initial_prompt`.

        The CV doubles as the ASR glossary, which costs nothing and fixes exactly
        the words that matter most in a technical answer.
        """
        terms: list[str] = list(self.skills)
        for role in self.roles:
            terms.extend(role.tech)
            for b in role.bullets:
                terms.extend(b.skills)
        seen: dict[str, None] = {}
        for t in terms:
            seen.setdefault(t.strip(), None)
        return [t for t in seen if t]



class MissedPoint(Strict):
    point: str = Field(description="Something in the candidate's own stories "
                                   "they had available and did not say.")
    source_story_id: str


class RiskyClaim(Strict):
    quote: str = Field(description="What they actually said, verbatim.")
    why: str = Field(description="Why it is risky: contradicts a guardrail, "
                                 "cites a stale figure, or cannot be defended.")


class StarCoverage(Strict):
    situation: bool
    task: bool
    action: bool
    result: bool
    reflection: bool


class StoryPatch(Strict):
    """A proposed addition to the story bank, drawn from what they just said.

    Never written to disk without review. Everything here is in the candidate's
    own words from the transcript - the model is extracting, not inventing.
    """

    story_id: str = Field(description="Existing story id to enhance, or a new "
                                      "kebab-case id.")
    is_new: bool
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    reflection: str = ""


class Feedback(Strict):
    missed_points: list[MissedPoint] = Field(
        default_factory=list, max_length=6,
        description="The core output. Material from their stories they left on "
                    "the table.",
    )
    risky_claims: list[RiskyClaim] = Field(default_factory=list, max_length=6)
    star_coverage: StarCoverage
    strengths: list[str] = Field(default_factory=list, max_length=3)
    fixes: list[str] = Field(
        default_factory=list, max_length=5,
        description="Imperative, specific, under 20 words each.",
    )
    story_patch: StoryPatch | None = None



class Question(Strict):
    id: str
    text: str
    tags: list[str] = Field(default_factory=list)
    seconds: int = 120
    kind: Literal["technical", "behavioural", "system-design"] = "technical"
    targets_story_id: str | None = None


class QuestionSet(Strict):
    questions: list[Question] = Field(default_factory=list, max_length=20)
