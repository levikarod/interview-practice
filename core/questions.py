"""Loading the question bank.

`questions/core.yaml` ships with the repo and works for anyone. Questions
generated from a CV are written to `<profile>/questions.yaml` and take
precedence on id collision, so a personalised question replaces the generic one
rather than appearing twice.
"""

from __future__ import annotations

import random
from pathlib import Path

import yaml

from core import profile_store
from core.schemas import Question

CORE_BANK = Path(__file__).resolve().parent.parent / "questions" / "core.yaml"


def _read(path: Path) -> list[Question]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [Question(**item) for item in raw]


def load_questions(directory: Path | None = None) -> list[Question]:
    """The core bank plus any generated for this profile."""
    by_id = {q.id: q for q in _read(CORE_BANK)}
    try:
        generated = (directory or profile_store.profile_dir()) / "questions.yaml"
        for question in _read(generated):
            by_id[question.id] = question
    except profile_store.ProfileNotSetUp:
        pass
    return list(by_id.values())


def get_question(question_id: str, directory: Path | None = None) -> Question | None:
    return next((q for q in load_questions(directory) if q.id == question_id), None)


def pick_question(directory: Path | None = None, exclude: set[str] | None = None,
                  rng: random.Random | None = None) -> Question | None:
    """A question to ask next, avoiding ones already asked this session.

    Falls back to the full bank once every question has been used, so a long
    session keeps working instead of running dry.
    """
    questions = load_questions(directory)
    if not questions:
        return None
    remaining = [q for q in questions if q.id not in (exclude or set())]
    return (rng or random).choice(remaining or questions)
