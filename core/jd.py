"""Generating interview questions from a job description.

One model call. It sees the job description and a condensed view of the
candidate's material, because a question is only worth practising when it sits in
the overlap between what the role probes and what the candidate can speak to.

Generated questions are returned, never saved. Reviewing them is the point: the
model will write some that miss, and a bank silently filling with mediocre
questions is worse than one that stays small. Saving is a separate, explicit
step.

The candidate summary deliberately carries story ids, tags and aliases rather
than full STAR text. The questions' `tags` are what later retrieval matches
against, so the model needs to see the vocabulary the stories already answer to -
and full bodies would cost tokens without improving the tags.
"""

from __future__ import annotations

from pathlib import Path

from core import llm, profile_store, questions as questions_mod
from core.llm import Completion, LLMClient
from core.schemas import GeneratedQuestions, Question

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "jd_questions.md"

INSTRUCTION = ("Write interview questions for this candidate and this role. "
               "Return the structured object.")

MAX_JD_CHARS = 20_000


def candidate_summary(directory: Path | None = None) -> str:
    """What the model needs to know about the candidate, condensed."""
    profile = profile_store.load_profile(directory)
    stories = profile_store.load_stories(directory)

    lines = [f"# {profile.name or 'Candidate'} - {profile.headline}"]
    if profile.summary:
        lines += ["", profile.summary]

    lines += ["", "## Roles"]
    for role in profile.roles:
        lines.append(f"- {role.title} at {role.org} ({role.dates})")
        for bullet in role.bullets:
            metric = f"  [{bullet.metric}]" if bullet.metric else ""
            lines.append(f"    - {bullet.text}{metric}")

    lines += ["", "## Stories available to draw on",
              "(id | status | tags | aliases - use these words in question tags)"]
    for story in stories:
        lines.append(
            f"- {story.id} | {story.status.value} | "
            f"{', '.join(story.tags)} | {', '.join(story.aliases[:8])}"
        )

    if profile.skills:
        lines += ["", "## Skills", ", ".join(profile.skills)]

    return "\n".join(lines)


def generate(jd_text: str, directory: Path | None = None,
             client: LLMClient | None = None) -> tuple[GeneratedQuestions, Completion]:
    """Draft questions for a job description. Nothing is saved."""
    jd_text = (jd_text or "").strip()
    if len(jd_text) < 80:
        raise ValueError(
            "That job description is too short to work from. Paste the full "
            "posting - responsibilities and requirements are where the "
            "questions come from."
        )

    payload = "\n".join([
        "## Job description",
        jd_text[:MAX_JD_CHARS],
        "",
        "## The candidate",
        candidate_summary(directory),
    ])

    client = client or llm.get_client()
    completion = client.complete(
        instruction=INSTRUCTION,
        payload=payload,
        schema=GeneratedQuestions.model_json_schema(),
        system=PROMPT.read_text(encoding="utf-8"),
    )

    if completion.data is None:
        raise ValueError("the model returned no structured output")

    drafted = GeneratedQuestions.model_validate(completion.data)
    return _deduplicate(drafted, directory), completion


def _deduplicate(drafted: GeneratedQuestions,
                 directory: Path | None = None) -> GeneratedQuestions:
    """Give every drafted question a unique id.

    The model does not know what is already in the bank, so a collision would
    silently overwrite an existing question on save.
    """
    taken = {q.id for q in questions_mod.load_questions(directory,
                                                        include_disabled=True)}
    fixed: list[Question] = []
    for question in drafted.questions:
        if question.id in taken or not question.id:
            question = question.model_copy(
                update={"id": questions_mod.slug(question.text, taken)}
            )
        taken.add(question.id)
        fixed.append(question.model_copy(update={"source": "jd"}))
    return drafted.model_copy(update={"questions": fixed})
