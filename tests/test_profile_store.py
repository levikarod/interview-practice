"""Tests for reading and writing the Markdown profile."""

from __future__ import annotations

import pytest

from core import profile_store as ps
from core.ingest import derive
from core.schemas import Story, StoryStatus

EXAMPLE_STORIES = sorted((ps.EXAMPLE_DIR / "stories").glob("*.md"))


class TestRoundTrip:
    @pytest.mark.parametrize("path", EXAMPLE_STORIES, ids=lambda p: p.stem)
    def test_parse_then_dump_is_byte_identical(self, path):
        """An AI-proposed patch should show up as a minimal git diff. If dumping
        reformats untouched fields, every patch rewrites the whole file and the
        review step becomes unreadable."""
        original = path.read_text(encoding="utf-8")
        assert ps.dump_story(ps.parse_story(original)) == original

    def test_missing_frontmatter_is_rejected(self):
        with pytest.raises(ValueError, match="frontmatter"):
            ps.parse_story("## Claim\n\nno frontmatter here\n")

    def test_unknown_headings_are_ignored_not_crashed_on(self):
        story = ps.parse_story(
            "---\nid: x\ntitle: X\n---\n\n## Claim\n\nkept\n\n"
            "## Notes To Self\n\ndropped\n"
        )
        assert story.claim == "kept"


class TestLoading:
    def test_loads_every_example_story(self):
        stories = ps.load_stories(ps.EXAMPLE_DIR)
        assert len(stories) == len(EXAMPLE_STORIES)

    def test_sorted_by_id_for_stable_ordering(self):
        ids = [s.id for s in ps.load_stories(ps.EXAMPLE_DIR)]
        assert ids == sorted(ids)

    def test_example_covers_every_status(self):
        """The example is also the UI's fixture set, so it has to exercise all
        three badge states."""
        statuses = {s.status for s in ps.load_stories(ps.EXAMPLE_DIR)}
        assert statuses == {StoryStatus.STUB, StoryStatus.DRAFT,
                            StoryStatus.VERIFIED}

    def test_is_empty_distinguishes_stubs_from_filled_stories(self):
        by_id = {s.id: s for s in ps.load_stories(ps.EXAMPLE_DIR)}
        assert by_id["vanta-ledger-partitioning"].is_empty()
        assert not by_id["vanta-idempotency-keys"].is_empty()

    def test_a_malformed_story_does_not_take_down_the_session(self, tmp_path):
        """One bad file must not cost you the whole practice session."""
        (tmp_path / "stories").mkdir()
        (tmp_path / "stories" / "good.md").write_text(
            ps.dump_story(Story(id="good", title="Good")), encoding="utf-8")
        (tmp_path / "stories" / "bad.md").write_text("garbage", encoding="utf-8")
        assert [s.id for s in ps.load_stories(tmp_path)] == ["good"]


class TestProfileSelection:
    def test_example_is_used_when_there_is_no_real_profile(self, tmp_path,
                                                           monkeypatch):
        monkeypatch.setattr(ps, "REAL_DIR", tmp_path / "absent")
        assert ps.profile_dir() == ps.EXAMPLE_DIR
        assert ps.is_example()

    def test_real_profile_wins_when_present(self, tmp_path, monkeypatch):
        (tmp_path / "cv.md").write_text("# Someone\n", encoding="utf-8")
        monkeypatch.setattr(ps, "REAL_DIR", tmp_path)
        assert ps.profile_dir() == tmp_path
        assert not ps.is_example(tmp_path)

    def test_needs_ingest_is_true_for_a_cv_with_nothing_derived(self, tmp_path):
        (tmp_path / "cv.md").write_text("# Someone\n", encoding="utf-8")
        assert ps.needs_ingest(tmp_path)

    def test_needs_ingest_is_false_once_derived(self):
        """The bundled example ships a derived cv.json, so the zero-setup path
        never nags about finishing setup."""
        assert not ps.needs_ingest(ps.EXAMPLE_DIR)


class TestDeriveIsNonDestructive:
    def test_rederiving_keeps_filled_in_stories(self, tmp_path):
        """Editing cv.md and re-deriving must not throw away STAR detail you
        earned by answering questions."""
        (tmp_path / "cv.md").write_text(
            "# A\n\n## Experience\n\n### Eng, Acme (Remote) (2020 - 2022)\n\n"
            "- Did a thing that mattered.\n\n"
            "<!--meta\nid: acme-thing\nskills: python\n-->\n",
            encoding="utf-8",
        )
        first = derive(tmp_path)
        assert first["stubs_created"] == ["acme-thing"]

        filled = ps.load_stories(tmp_path)[0]
        filled.situation = "hard-won detail"
        filled.status = StoryStatus.VERIFIED
        ps.save_story(filled, tmp_path)

        second = derive(tmp_path)
        assert second["stubs_created"] == []
        assert second["stories_kept"] == ["acme-thing"]

        after = ps.load_stories(tmp_path)[0]
        assert after.situation == "hard-won detail"
        assert after.status is StoryStatus.VERIFIED


class TestSaving:
    def test_a_story_cannot_be_saved_outside_its_folder(self, tmp_path):
        with pytest.raises(ValueError, match="outside"):
            ps.save_story(Story(id="../escaped", title="x"), tmp_path)
        assert not (tmp_path / "escaped.md").exists()
