"""Turning a CV into a profile.

Two front doors, one output:

    cv.pdf  --> text --> [one LLM call] --> cv.md --> [parse] --> cv.json
    cv.md   ------------------------------------------> [parse] --> cv.json

`cv.md` is the source of truth. `cv.json` is a derived cache, re-derived whenever
cv.md changes. That ordering is deliberate: PDF extraction gets things wrong, and
correcting Markdown is pleasant where correcting JSON is not.

The Markdown parser below is deterministic - no model, no cost. A CV that already
carries `<!--meta -->` blocks (because we generated it, or because you write yours
that way) skips the model entirely.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from core.schemas import CvBullet, CvRole, Profile, Story, StoryStatus

# A bullet's metadata block, emitted by the extractor and editable by hand.
_META = re.compile(r"<!--meta\s*\r?\n(.*?)-->", re.S)
# Trailing "(...)" groups on a role heading: location and/or dates.
_PARENS = re.compile(r"\(([^()]*)\)\s*$")

# Sections whose bullets are not achievements. Everything else that sits under a
# "### " heading counts - so "Selected Projects" contributes bullets just like
# "Experience" does, which matters when the best material lives in a side project.
_NON_ROLE = {"skills", "certifications", "education", "languages", "summary"}


def _slug(text: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or fallback


def _split_role_heading(heading: str) -> tuple[str, str, str]:
    """Split a role heading into (title, org, dates).

        Senior Engineer, Payments team, Vanta Pay (Remote) (2022 - Present)
          -> ("Senior Engineer", "Vanta Pay", "2022 - Present")
        Software Engineer & Founder, Droppo, Colombia (April 2020 - Present)
          -> ("Software Engineer & Founder", "Droppo", "April 2020 - Present")

    Those two disagree about what the last comma-part means - org in the first,
    location in the second - so the parenthetical decides it. If a non-date
    parenthetical is present the location is already accounted for, and the last
    comma-part is the org. If only dates are in parens, the trailing comma-part
    is probably the location, so the org is the second part instead.

    Genuinely ambiguous headings are why the setup screen lets you edit cv.md.
    """
    rest, dates, had_location = heading.strip(), "", False
    for _ in range(2):
        match = _PARENS.search(rest)
        if not match:
            break
        inner = match.group(1).strip()
        rest = rest[: match.start()].strip()
        if not dates and any(ch.isdigit() for ch in inner):
            dates = inner
        else:
            had_location = True

    parts = [p.strip() for p in rest.split(",") if p.strip()]
    if not parts:
        return heading.strip(), "", dates
    if len(parts) == 1:
        return parts[0], "", dates
    if had_location or len(parts) == 2:
        return parts[0], parts[-1], dates
    return parts[0], parts[1], dates


def parse_cv_markdown(text: str) -> Profile:
    """Parse a CV in our Markdown format into a Profile. Deterministic."""
    profile = Profile()
    lines = text.splitlines()

    role: CvRole | None = None
    section = ""          # current "## " section, lowercased
    pending_bullet: CvBullet | None = None
    summary: list[str] = []
    i = 0

    def close_bullet() -> None:
        nonlocal pending_bullet
        if pending_bullet and role is not None:
            role.bullets.append(pending_bullet)
        pending_bullet = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # A meta block attaches to the bullet immediately above it.
        if stripped.startswith("<!--meta"):
            block = _META.search("\n".join(lines[i:]))
            if block and pending_bullet:
                meta = yaml.safe_load(block.group(1)) or {}
                pending_bullet.id = str(meta.get("id") or pending_bullet.id)
                for field in ("skills", "aliases"):
                    value = meta.get(field)
                    if isinstance(value, str):
                        value = [v.strip() for v in value.split(",") if v.strip()]
                    if value:
                        setattr(pending_bullet, field, list(value))
                metric = meta.get("metric")
                if metric and str(metric).lower() != "none":
                    pending_bullet.metric = str(metric)
                pending_bullet.metric_sourced = bool(meta.get("metric_sourced", False))
            # Skip past the block.
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue

        # Ordinary HTML comments are notes for humans; ignore them wholesale.
        if stripped.startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue

        if stripped.startswith("# "):
            profile.name = stripped[2:].strip()
        elif stripped.startswith("## "):
            close_bullet()
            section = stripped[3:].strip().lower()
        elif stripped.startswith("### "):
            close_bullet()
            title, org, dates = _split_role_heading(stripped[4:])
            role = CvRole(id=_slug(f"{org}-{title}", "role"), title=title,
                          org=org, dates=dates)
            profile.roles.append(role)
        elif stripped.startswith("**Tech stack:**") and role is not None:
            close_bullet()
            tech = stripped.split("**Tech stack:**", 1)[1]
            role.tech = [t.strip(" .") for t in tech.split(",") if t.strip(" .")]
        elif stripped.startswith("- ") and role is not None and section not in _NON_ROLE:
            close_bullet()
            body = stripped[2:].strip()
            pending_bullet = CvBullet(id=_slug(f"{role.org}-{body[:40]}", "bullet"),
                                      text=body)
        elif stripped.startswith("- ") and section == "skills":
            # "- **Backend:** Python, Go, REST APIs"
            body = re.sub(r"^\*\*(.+?):\*\*", "", stripped[2:]).strip()
            profile.skills.extend(
                s.strip() for s in body.split(",") if s.strip() and len(s.strip()) < 40
            )
        elif section == "summary" and stripped and not stripped.startswith("#"):
            summary.append(stripped)
        elif pending_bullet and stripped and not stripped.startswith(("-", "#", "*")):
            # Continuation of a wrapped bullet.
            pending_bullet.text += " " + stripped

        i += 1

    close_bullet()
    profile.summary = " ".join(summary).strip()

    # Headline: the first bold line before any section heading.
    for line in lines[:12]:
        s = line.strip()
        if s.startswith("**") and s.endswith("**") and len(s) > 4:
            profile.headline = s.strip("*").strip()
            break

    return profile


def stubs_from_profile(profile: Profile) -> list[Story]:
    """One stub per CV bullet.

    This is why the story bank is never empty on day one. A stub carries the
    claim and nothing else, which is already enough for feedback to say "your CV
    says 20+ repositories and you didn't mention the number."
    """
    stories: list[Story] = []
    for role in profile.roles:
        for bullet in role.bullets:
            stories.append(
                Story(
                    id=bullet.id,
                    title=_title_from(bullet.text),
                    status=StoryStatus.STUB,
                    source="cv",
                    role=role.org or role.title,
                    tags=[_slug(s) for s in bullet.skills][:6],
                    aliases=bullet.aliases,
                    metric=bullet.metric,
                    claim=bullet.text,
                )
            )
    return stories


def unsourced_metrics(profile: Profile) -> list[tuple[str, str]]:
    """(metric, bullet text) for every figure with nothing behind it.

    Seeds guardrails.md with "numbers you will be asked to defend" - the generic
    half of guardrails, useful to anyone, free because it rides the same parse.
    """
    return [
        (b.metric, b.text)
        for role in profile.roles
        for b in role.bullets
        if b.metric and not b.metric_sourced
    ]


def _title_from(text: str, words: int = 6) -> str:
    """A short human label from a bullet: first few words, trimmed."""
    clean = re.sub(r"\*\*|`", "", text).strip().rstrip(".")
    parts = clean.split()
    title = " ".join(parts[:words])
    return title + ("…" if len(parts) > words else "")


def read_source(path: Path) -> str:
    """Pull plain text out of a CV file. PDF, Markdown or plain text.

    We never parse the PDF structurally - no column detection, no heading
    heuristics. Text goes to the model, which normalises it into our Markdown
    format. Layout is exactly the kind of thing a model handles and a regex
    parser does not.
    """
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt", ""):
        return path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        from pypdf import PdfReader

        pages = [page.extract_text() or "" for page in PdfReader(str(path)).pages]
        text = "\n\n".join(pages).strip()
        if len(text) < 200:
            raise ValueError(
                f"Only {len(text)} characters of text came out of {path.name}. "
                "It is probably a scanned image rather than a text PDF - paste "
                "the text in instead."
            )
        return text
    raise ValueError(f"Unsupported CV format {suffix!r}. Use .pdf, .md or .txt.")


def extract_cv_markdown(text: str, client: "LLMClient | None" = None) -> str:
    """Any CV's text -> our Markdown format. One model call.

    The prompt carries profile.example/cv.md as its worked example, so the
    format the model targets is a real file that is parsed by our own tests
    rather than a description that can quietly drift.
    """
    from core.llm import get_client

    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "cv_extract.md"
    example_path = Path(__file__).resolve().parent.parent / "profile.example" / "cv.md"
    system = (prompt_path.read_text(encoding="utf-8")
              + "\n\n" + example_path.read_text(encoding="utf-8"))

    client = client or get_client()
    result = client.complete(
        instruction="Convert the CV below into the target Markdown format.",
        payload=text,
        system=system,
    )
    return _strip_fences(result.text)


def _strip_fences(text: str) -> str:
    """Drop a ```markdown wrapper if the model added one despite being told not to."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
            return "\n".join(lines).strip() + "\n"
    return stripped + "\n"


class CvAlreadyExists(Exception):
    """Refusing to overwrite a cv.md that is already there."""


def ingest_file(source: Path, directory: Path, client: "LLMClient | None" = None,
                overwrite: bool = False) -> str:
    """CV file -> <directory>/cv.md. Returns the Markdown that was written.

    A .md source that already carries <!--meta --> blocks is copied straight
    through with no model call: it is already in the target format, so paying
    for a conversion would be pure waste.

    Refuses to clobber an existing cv.md unless `overwrite`. That file is the
    source of truth and is meant to be hand-edited - someone who re-runs
    ingestion to pick up a new PDF should not silently lose the corrections they
    made to the last one.
    """
    text = read_source(source)
    already_formatted = source.suffix.lower() == ".md" and "<!--meta" in text

    target = directory / "cv.md"
    if target.exists() and not overwrite and target.resolve() != source.resolve():
        raise CvAlreadyExists(
            f"{target} already exists and would be overwritten. Move it aside, or "
            f"pass overwrite=True (--force on the CLI) if that is what you want."
        )

    markdown = text if already_formatted else extract_cv_markdown(text, client)

    directory.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return markdown


def derive(directory: Path | None = None, create_stubs: bool = True) -> dict:
    """cv.md -> cv.json (+ stubs for bullets that don't have a story yet).

    Safe to re-run. Existing story files are never overwritten: once you have
    answered a question and filled a story in, re-deriving after a cv.md edit
    must not throw that away. New bullets get new stubs; everything else is left
    exactly as it is.
    """
    from core import profile_store  # local import: avoids a circular import

    directory = directory or profile_store.profile_dir()
    markdown = (directory / "cv.md").read_text(encoding="utf-8")

    profile = parse_cv_markdown(markdown)
    profile_store.save_profile(profile, directory)

    created, kept = [], []
    if create_stubs:
        existing = {s.id for s in profile_store.load_stories(directory)}
        for stub in stubs_from_profile(profile):
            if stub.id in existing:
                kept.append(stub.id)
            else:
                profile_store.save_story(stub, directory)
                created.append(stub.id)

    return {
        "profile": profile,
        "roles": len(profile.roles),
        "bullets": sum(len(r.bullets) for r in profile.roles),
        "stubs_created": created,
        "stories_kept": kept,
        "unsourced_metrics": unsourced_metrics(profile),
    }


def _main() -> None:
    """CLI, same code path the setup screen uses - no second implementation.

        uv run python -m core.ingest                 re-derive the active profile
        uv run python -m core.ingest ~/cv.pdf        ingest a CV, then derive
        uv run python -m core.ingest profile.example re-derive a specific folder
    """
    import io
    import sys

    from core import profile_store

    # Windows consoles default to cp1252 and raise on an em-dash. The data is
    # fine; the terminal is not.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")

    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    arg = Path(args[0]) if args else None

    if arg is not None and arg.is_file():
        target = profile_store.REAL_DIR
        print(f"reading {arg.name} …")
        try:
            ingest_file(arg, target, overwrite=force)
        except CvAlreadyExists as exc:
            print(f"\n{exc}")
            return
        print(f"wrote {target / 'cv.md'}")
    else:
        target = arg

    result = derive(target)
    profile = result["profile"]

    if not result["roles"]:
        # A silent empty profile looks like a bug. Say what actually happened.
        print("\nNo roles were found in cv.md.")
        print("Expected '### Title, Employer (Location) (Dates)' headings under")
        print("'## Experience'. Open cv.md and compare it against")
        print("profile.example/cv.md, then re-run this command.")
        return

    print(f"{profile.name or '(no name found)'} — {profile.headline}")
    print(f"  roles   : {result['roles']}")
    print(f"  bullets : {result['bullets']}")
    print(f"  stubs   : {len(result['stubs_created'])} created, "
          f"{len(result['stories_kept'])} existing kept")
    if result["unsourced_metrics"]:
        print(f"  numbers to defend ({len(result['unsourced_metrics'])}):")
        for metric, _ in result["unsourced_metrics"][:8]:
            print(f"    - {metric}")


if __name__ == "__main__":
    _main()
