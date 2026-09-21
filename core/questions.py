"""The question bank: the shipped one, and yours.

Two layers. `questions/core.yaml` is committed and works for anyone. Your own
questions - edited, hand-written, or generated from a job description - live in
`<profile>/questions.yaml`, which is gitignored.

Your layer wins on id collision, so editing a shipped question writes an override
rather than modifying the committed file. The repo's bank stays pristine, your
bank stays yours, and `git pull` never fights your edits.

Deleting a shipped question is the same mechanism: it is saved into your layer
with `enabled: false`, because the committed file is not ours to edit. Deleting
one of your own removes it outright.
"""

from __future__ import annotations

import random
import re
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


def user_bank_path(directory: Path | None = None) -> Path:
    return (directory or profile_store.profile_dir()) / "questions.yaml"


def load_core() -> list[Question]:
    return _read(CORE_BANK)


def load_user(directory: Path | None = None) -> list[Question]:
    try:
        return _read(user_bank_path(directory))
    except profile_store.ProfileNotSetUp:
        return []


def load_questions(directory: Path | None = None,
                   include_disabled: bool = False) -> list[Question]:
    """The merged bank. Your layer overrides core by id."""
    by_id = {q.id: q for q in load_core()}
    for question in load_user(directory):
        by_id[question.id] = question
    merged = list(by_id.values())
    if include_disabled:
        return merged
    return [q for q in merged if q.enabled]


def get_question(question_id: str, directory: Path | None = None) -> Question | None:
    return next((q for q in load_questions(directory, include_disabled=True)
                 if q.id == question_id), None)


def save_user(questions: list[Question], directory: Path | None = None) -> Path:
    path = user_bank_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [q.model_dump(mode="json") for q in questions]
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True,
                       default_flow_style=False),
        encoding="utf-8",
    )
    return path


def upsert(question: Question, directory: Path | None = None) -> Question:
    """Add or replace a question in your layer."""
    bank = [q for q in load_user(directory) if q.id != question.id]
    bank.append(question)
    save_user(bank, directory)
    return question


def upsert_many(new: list[Question], directory: Path | None = None) -> list[Question]:
    """Add several at once, so accepting a batch of generated questions is one
    write rather than one per question."""
    incoming = {q.id: q for q in new}
    bank = [q for q in load_user(directory) if q.id not in incoming]
    bank.extend(incoming.values())
    save_user(bank, directory)
    return list(incoming.values())


def delete(question_id: str, directory: Path | None = None) -> bool:
    """Remove a question from practice.

    A shipped question is tombstoned as disabled in your layer, whether or not
    you had already edited it. Simply dropping your override would resurrect the
    shipped version, so a button labelled Remove would restore the original -
    which is the opposite of what it says.

    One of your own is removed outright, since nothing underneath would come back.
    """
    bank = load_user(directory)
    shipped = next((q for q in load_core() if q.id == question_id), None)

    if shipped is not None:
        override = next((q for q in bank if q.id == question_id), shipped)
        bank = [q for q in bank if q.id != question_id]
        bank.append(override.model_copy(update={"enabled": False}))
        save_user(bank, directory)
        return True

    if any(q.id == question_id for q in bank):
        save_user([q for q in bank if q.id != question_id], directory)
        return True
    return False


def slug(text: str, taken: set[str] | None = None) -> str:
    """A stable, readable id from question text, unique against `taken`."""
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower())][:5]
    base = "-".join(words) or "question"
    candidate, n = base, 2
    while taken and candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def pick_question(directory: Path | None = None, exclude: set[str] | None = None,
                  rng: random.Random | None = None) -> Question | None:
    """A question to ask next, avoiding ones already asked this session.

    Falls back to the full bank once every question has been used, so a long
    session keeps working instead of running dry.
    """
    bank = load_questions(directory)
    if not bank:
        return None
    remaining = [q for q in bank if q.id not in (exclude or set())]
    return (rng or random).choice(remaining or bank)
