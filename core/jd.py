"""Generating interview questions from a job description.

One model call. It sees the job description and a condensed view of the
candidate's material, because a question is only worth practising when it sits in
the overlap between what the role probes and what the candidate can speak to.

Generated questions are returned, never saved. Reviewing them is the point: the
model will write some that miss, and a bank silently filling with mediocre
questions is worse than one that stays small. Saving is a separate, explicit
step, and it keeps the posting too.

A kept posting is `jds/<id>.md` in the profile, readable on its own. Its
questions go into the ordinary bank carrying `jd_id`, so practising for one role
is a filter on the bank rather than a second bank with its own edit and remove
rules to keep in step.

The candidate summary deliberately carries story ids, tags and aliases rather
than full STAR text. The questions' `tags` are what later retrieval matches
against, so the model needs to see the vocabulary the stories already answer to -
and full bodies would cost tokens without improving the tags.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from core import llm, profile_store, questions as questions_mod
from core.llm import Completion, LLMClient
from core.schemas import GeneratedQuestions, JobDescription, Question

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


META_KEYS = ["id", "title", "role_summary", "created"]


def jds_dir(directory: Path | None = None) -> Path:
    return (directory or profile_store.profile_dir()) / "jds"


def save(title: str, text: str, chosen: list[Question], role_summary: str = "",
         directory: Path | None = None, today: date | None = None) -> JobDescription:
    """Keep a posting and the questions chosen from it.

    The id is derived from the title rather than taken from the request, so
    nothing a browser sends can name a path outside `jds/`.
    """
    folder = jds_dir(directory)
    taken = {path.stem for path in folder.glob("*.md")} if folder.exists() else set()
    posting = JobDescription(
        id=questions_mod.slug(title or "job description", taken),
        title=title.strip(),
        role_summary=role_summary.strip(),
        created=(today or date.today()).isoformat(),
        text=text.strip(),
    )

    folder.mkdir(parents=True, exist_ok=True)
    meta = {key: getattr(posting, key) for key in META_KEYS}
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True,
                           default_flow_style=False).strip()
    (folder / f"{posting.id}.md").write_text(f"---\n{front}\n---\n\n{posting.text}\n",
                                             encoding="utf-8")

    questions_mod.upsert_many(
        [q.model_copy(update={"jd_id": posting.id, "source": "jd"}) for q in chosen],
        directory,
    )
    return posting


def load_all(directory: Path | None = None) -> list[JobDescription]:
    """Every kept posting, sorted by id. A malformed file is skipped, not raised."""
    folder = jds_dir(directory)
    if not folder.exists():
        return []
    out: list[JobDescription] = []
    for path in sorted(folder.glob("*.md")):
        try:
            meta, body = profile_store.split_frontmatter(path.read_text(encoding="utf-8"))
            out.append(JobDescription(**meta, text=body.strip()))
        except (ValueError, TypeError) as exc:
            print(f"[jd] skipping {path.name}: {exc}")
    return out
