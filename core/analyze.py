"""The one model call: transcript plus their own material, in; Feedback, out.

Everything else in the answer path is deterministic. Transcription is local,
delivery metrics are arithmetic, retrieval is tag overlap. The model is reserved
for the single step that needs judgment, which keeps the cost per answer to one
call and keeps every other part of the system measurable against ground truth.

The payload is assembled as Markdown rather than JSON. It is read by a model, not
parsed by one, and the structure that matters - which story an observation came
from - is carried by the ids, which the schema then requires back.

`Feedback.model_json_schema()` is handed to the CLI as --json-schema and the same
class validates the reply, so there is no drift between what we ask for and what
we accept. Length limits on `missed_points` and `strengths` are schema constraints,
not requests in the prompt.
"""

from __future__ import annotations

from pathlib import Path

from core import llm, profile_store, retrieve
from core.llm import Completion, LLMClient
from core.schemas import Feedback, Question, Story, Transcript

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "analyze.md"

INSTRUCTION = ("Review the answer below against the candidate's own material. "
               "Return the structured object.")


def _render_story(scored: retrieve.Scored) -> str:
    story = scored.story
    lines = [f"### {story.id}  [{story.status.value}]",
             f"title: {story.title}"]
    if story.metric:
        lines.append(f"metric: {story.metric}")
    if story.claim:
        lines.append(f"claim: {story.claim}")

    for label, value in [("Situation", story.situation), ("Task", story.task),
                         ("Action", story.action), ("Result", story.result),
                         ("Reflection", story.reflection)]:
        if value.strip():
            lines.append(f"{label}: {value.strip()}")

    if story.is_empty():
        lines.append("(stub - the claim is all there is. Do not invent detail.)")
    return "\n".join(lines)


def _render_previous(previous: dict) -> str:
    lines = []
    if previous.get("headline"):
        lines.append(f"The one thing they were told: {previous['headline']}")
    lines += [f"- fix: {fix}" for fix in previous.get("fixes") or []]
    lines += [f"- missed: {p.get('point', '')} [{p.get('source_story_id', '')}]"
              for p in previous.get("missed_points") or []]
    lines += [f'- risky: "{r.get("quote", "")}"'
              for r in previous.get("risky_claims") or []]
    return "\n".join(lines) or "(no findings were recorded)"


def build_payload(question: Question, transcript: Transcript,
                  stories: list[Story], directory: Path | None = None,
                  previous: dict | None = None) -> str:
    """Assemble everything the model sees, apart from the system prompt."""
    profile = profile_store.load_profile(directory)
    guardrails = profile_store.load_guardrails(directory).strip()

    picked = retrieve.pick_stories(question, stories)
    bullets = retrieve.pick_bullets(question, profile)

    parts = [
        "## Question",
        question.text,
        "",
        "## What they said (automatic transcript)",
        transcript.text.strip() or "(nothing was transcribed)",
        "",
        "## Their stories, most relevant first",
        "\n\n".join(_render_story(s) for s in picked) or "(none yet)",
        "",
        "## Their CV claims on this topic",
        "\n".join(f"- [{b.id}] {b.text}" for b in bullets) or "(none)",
    ]

    if guardrails:
        parts += ["", "## Guardrails - claims to flag if they made them", guardrails]
    else:
        parts += ["", "## Guardrails", "(none set. Flag only overclaiming that "
                  "contradicts the stories above.)"]

    if previous:
        parts += ["", "## Their previous attempt at this question",
                  _render_previous(previous)]

    return "\n".join(parts)


def analyse(question: Question, transcript: Transcript,
            stories: list[Story] | None = None,
            client: LLMClient | None = None,
            directory: Path | None = None,
            previous: dict | None = None) -> tuple[Feedback, Completion]:
    """Review one answer. Returns the feedback and the raw completion.

    The completion is returned alongside so the caller can record what the call
    cost without this module needing to know about storage. `previous` is the
    last stored feedback for this question, so the model can credit what
    improved.
    """
    stories = profile_store.load_stories(directory) if stories is None else stories
    payload = build_payload(question, transcript, stories, directory, previous)

    client = client or llm.get_client()
    completion = client.complete(
        instruction=INSTRUCTION,
        payload=payload,
        schema=Feedback.model_json_schema(),
        system=PROMPT.read_text(encoding="utf-8"),
    )

    if completion.data is None:
        raise ValueError("the model returned no structured output")

    return Feedback.model_validate(completion.data), completion
