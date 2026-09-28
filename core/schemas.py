"""The single source of truth for every structured shape in the app.

These models do double duty: `model_json_schema()` produces the schema handed to
`claude --json-schema`, and `model_validate()` checks what comes back. One
declaration, no drift between what we ask for and what we accept.

Constraints expressed here travel to the model inside the schema rather than
being requested politely in the prompt. Two kinds: the ones on `Question` and
the profile are enforced on the way back, and the ones on `Feedback` are asked
for and not enforced - see `brief` for why those differ.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


MAX_QUESTION_CHARS = 120
MAX_NOTE_CHARS = 180


class Strict(BaseModel):
    """Base for anything sent to the model. `extra='forbid'` makes Pydantic emit
    `additionalProperties: false`, which structured outputs require."""

    model_config = ConfigDict(extra="forbid")


def brief(limit: int, **field: Any) -> Any:
    """A length the model is asked for and not held to.

    The cap reaches the model inside the JSON Schema, which shortens what comes
    back far more reliably than a sentence in the prompt asking for brevity.

    It is deliberately not a Pydantic constraint. `runs.py` saves the run only
    once `analyse` has returned, so rejecting a reply that overran by one
    character would throw away the transcript and the delivery metrics along
    with the feedback, and the candidate would have to record the answer again.
    Ask strictly, accept leniently.
    """
    return Field(json_schema_extra={"maxLength": limit}, **field)


def at_most(limit: int, **field: Any) -> Any:
    """The same bargain applied to how many findings, not how long each runs."""
    return Field(default_factory=list, json_schema_extra={"maxItems": limit},
                 **field)



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

        The CV doubles as the ASR glossary, which costs nothing and fixes the
        words a technical answer turns on.

        Distinctive terms come first, because the prompt has a small budget and
        spending it on words the model already knows is wasted. A term counts as
        distinctive when it has an internal capital or a digit - ClickHouse,
        RabbitMQ, MercadoLibre, k6 - which is exactly the shape of name a general
        speech model mangles. "Python" and "REST APIs" need no help.
        """
        import re

        raw: list[str] = list(self.skills)
        for role in self.roles:
            raw.extend(role.tech)
            for b in role.bullets:
                raw.extend(b.skills)

        seen: dict[str, None] = {}
        for term in raw:
            for atom in re.split(r"[(),/]", term):
                atom = atom.strip()
                if atom and len(atom) < 32:
                    seen.setdefault(atom, None)

        def distinctive(term: str) -> bool:
            body = term[1:]
            return any(c.isupper() for c in body) or any(c.isdigit() for c in body)

        unique = list(seen)
        return ([t for t in unique if distinctive(t)]
                + [t for t in unique if not distinctive(t)])



class MissedPoint(Strict):
    point: str = brief(120,
                       description="Something in the candidate's own stories "
                                   "they had available and did not say. One "
                                   "sentence naming the concrete thing.")
    source_story_id: str


class RiskyClaim(Strict):
    quote: str = Field(description="What they actually said, verbatim.")
    why: str = brief(100,
                     description="Why it is risky: contradicts a guardrail, "
                                 "cites a stale figure, or cannot be defended.")
    say_instead: str = brief(100,
                             description="A defensible rewording in the "
                                         "candidate's own voice, one sentence.")


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

    story_id: str = Field(pattern="^[a-z0-9][a-z0-9-]*$",
                          description="Existing story id to enhance, or a new "
                                      "kebab-case id.")
    is_new: bool
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    reflection: str = ""


class Feedback(Strict):
    """What comes back from the one model call.

    Read in the gap between two attempts at the same question, which is why
    every free-text field here is capped: three short findings get acted on,
    six long ones get skimmed. `RiskyClaim.quote` is the one exception - it is
    the candidate's own words, and a cap would force a misquote.
    """

    headline: str = brief(
        110,
        description="The single most important change for next time. One "
                    "imperative sentence.",
    )
    fixed_since_last: list[Annotated[str, brief(100)]] = at_most(
        3,
        description="Only when a previous attempt is supplied: what that attempt "
                    "missed or got wrong that this one gets right.",
    )
    missed_points: list[MissedPoint] = at_most(
        3,
        description="The core output. Material from their stories they left on "
                    "the table.",
    )
    risky_claims: list[RiskyClaim] = at_most(3)
    star_coverage: StarCoverage
    strengths: list[Annotated[str, brief(80)]] = at_most(3)
    story_patch: StoryPatch | None = None



class Word(Strict):
    """One word with its timing, used to find pauses."""

    text: str
    start: float
    end: float


class Transcript(Strict):
    text: str = ""
    words: list[Word] = Field(default_factory=list)
    duration_s: float = 0.0
    language: str = ""


class AnswerMetrics(Strict):
    """Delivery measurements, computed in code rather than asked of a model.

    Pace and hesitation are arithmetic over word timings. Spending a model call
    on them would be slower, costlier and less reliable than counting.
    """

    duration_s: float = 0.0
    word_count: int = 0
    words_per_minute: int = 0
    filler_count: int = 0
    fillers: dict[str, int] = Field(default_factory=dict)
    longest_pause_s: float = 0.0
    overran: bool = False


class Question(Strict):
    id: str
    text: str = Field(
        max_length=MAX_QUESTION_CHARS,
        description="One short, open question as an interviewer would say it. "
                    "Never name the specifics the candidate should be recalling.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Retrieval keys. Matched against story tags and aliases, so "
                    "they should use the words a story would answer to.",
    )
    seconds: int = Field(default=120, ge=30, le=600)
    kind: Literal["technical", "behavioural", "system-design"] = "technical"
    targets_story_id: str | None = Field(
        default=None,
        description="A story this question is meant to pull out, when it was "
                    "written against a specific one.",
    )
    enabled: bool = True
    source: Literal["core", "custom", "jd"] = "core"
    note: str = Field(
        default="", max_length=MAX_NOTE_CHARS,
        description="One line on why this question is worth asking this "
                    "candidate. Shown when reviewing, not during practice.",
    )


class GeneratedQuestions(Strict):
    """Questions drafted from a job description, for review before they are kept."""

    role_summary: str = Field(
        description="One line: what this role actually screens for.",
    )
    questions: list[Question] = Field(default_factory=list, max_length=12)
