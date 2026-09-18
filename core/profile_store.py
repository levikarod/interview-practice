"""Reading and writing the Markdown profile.

`profile/` holds your real material and is gitignored. `profile.example/` is
fictional, committed, and used automatically when `profile/` is not set up — so
a fresh clone runs immediately instead of showing an empty screen.

Story files round-trip exactly: parse -> dump produces byte-identical output for
an unchanged story, so an AI-proposed patch shows up as a minimal git diff rather
than a reformatting of the whole file.

SECTIONS fixes both the body headings and the order they are written in;
META_KEYS does the same for frontmatter keys. Both orders are load-bearing:
a stable serialisation is what keeps those diffs small.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from core.schemas import Profile, Story, StoryStatus

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_DIR = REPO_ROOT / "profile"
EXAMPLE_DIR = REPO_ROOT / "profile.example"

SECTIONS: list[tuple[str, str]] = [
    ("Claim", "claim"),
    ("Situation", "situation"),
    ("Task", "task"),
    ("Action", "action"),
    ("Result", "result"),
    ("Reflection", "reflection"),
]

META_KEYS = ["id", "title", "status", "source", "role", "tags", "aliases",
             "metric", "verified"]

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.S)


class ProfileNotSetUp(Exception):
    """Neither a real profile nor the bundled example is usable."""


def profile_dir() -> Path:
    """The active profile directory.

    Prefers your real `profile/`. Falls back to `profile.example/` so the app is
    never dead on arrival for someone who just cloned it.
    """
    if (REAL_DIR / "cv.md").exists():
        return REAL_DIR
    if (EXAMPLE_DIR / "cv.md").exists():
        return EXAMPLE_DIR
    raise ProfileNotSetUp(
        f"No profile found. Expected {REAL_DIR / 'cv.md'} or "
        f"{EXAMPLE_DIR / 'cv.md'}. Upload a CV on the setup page."
    )


def is_example(directory: Path | None = None) -> bool:
    """True when running on the bundled sample rather than the user's own CV.
    The UI uses this to show a 'you're on sample data' banner."""
    return (directory or profile_dir()).resolve() == EXAMPLE_DIR.resolve()


def needs_ingest(directory: Path | None = None) -> bool:
    """True when a cv.md exists but nothing has been derived from it yet.

    This is a real state, distinct from "no profile": the user dropped in a CV
    and stopped, or edited cv.md and hasn't re-derived. Without this the UI shows
    an empty profile and looks broken rather than unfinished.
    """
    directory = directory or profile_dir()
    return (directory / "cv.md").exists() and not (directory / "cv.json").exists()



def parse_story(text: str) -> Story:
    """Parse one `stories/<id>.md` file.

    Line endings are normalised and a BOM stripped first, so a story saved by a
    Windows editor parses to the same Story as one saved by vim. .gitattributes
    keeps checkouts on LF; this covers everything else.

    Any `## ` heading closes the section in progress, and an unrecognised one
    then collects nothing - otherwise a note added under your own heading would
    be silently absorbed into Reflection.
    """
    text = text.lstrip("﻿").replace("\r\n", "\n")

    match = _FRONTMATTER.match(text)
    if not match:
        raise ValueError("story file has no YAML frontmatter block")

    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)

    heading_to_field = {h.lower(): f for h, f in SECTIONS}
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []

    for line in body.splitlines():
        if line.startswith("## "):
            if current:
                sections[current] = "\n".join(buf).strip()
            current = heading_to_field.get(line[3:].strip().lower())
            buf = []
        elif current:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf).strip()

    return Story(**{**meta, **sections})


def dump_story(story: Story) -> str:
    """Serialise a Story back to Markdown. Inverse of `parse_story`.

    Empty values are omitted, except tags and aliases which stay as empty lists
    so the frontmatter shape is predictable.
    """
    meta: dict[str, object] = {}
    for key in META_KEYS:
        value = getattr(story, key)
        if isinstance(value, StoryStatus):
            value = value.value
        if value in (None, [], "") and key not in ("tags", "aliases"):
            continue
        meta[key] = value

    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True,
                           default_flow_style=False).strip()
    parts = [f"---\n{front}\n---\n"]
    for heading, field in SECTIONS:
        parts.append(f"\n## {heading}\n\n{getattr(story, field).strip()}\n")
    return "".join(parts)


def stories_dir(directory: Path | None = None) -> Path:
    return (directory or profile_dir()) / "stories"


def load_stories(directory: Path | None = None) -> list[Story]:
    """Every story in the active profile, sorted by id for stable ordering.

    A malformed story is skipped with a warning rather than raised: one bad file
    must not cost you the whole practice session.
    """
    folder = stories_dir(directory)
    if not folder.exists():
        return []
    out: list[Story] = []
    for path in sorted(folder.glob("*.md")):
        try:
            out.append(parse_story(path.read_text(encoding="utf-8")))
        except (ValueError, TypeError) as exc:
            print(f"[profile] skipping {path.name}: {exc}")
    return out


def save_story(story: Story, directory: Path | None = None) -> Path:
    folder = stories_dir(directory)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{story.id}.md"
    path.write_text(dump_story(story), encoding="utf-8")
    return path



def load_profile(directory: Path | None = None) -> Profile:
    """Load the derived `cv.json`. Returns an empty Profile if not yet derived."""
    path = (directory or profile_dir()) / "cv.json"
    if not path.exists():
        return Profile()
    return Profile.model_validate(json.loads(path.read_text(encoding="utf-8")))


def save_profile(profile: Profile, directory: Path | None = None) -> Path:
    path = (directory or profile_dir()) / "cv.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(profile.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def load_cv_markdown(directory: Path | None = None) -> str:
    path = (directory or profile_dir()) / "cv.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load_guardrails(directory: Path | None = None) -> str:
    """Free-form Markdown: claims that cannot be defended, figures that are stale.

    Optional — an empty guardrails file simply means `risky_claims` stays quiet.
    """
    path = (directory or profile_dir()) / "guardrails.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""
