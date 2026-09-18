"""Tests for getting a CV in: file reading and the extraction call.

Uses FakeLLMClient throughout - no test may make a real model call.
"""

from __future__ import annotations

import pytest

from core.ingest import CvAlreadyExists, _strip_fences, ingest_file, read_source
from core.llm import FakeLLMClient
from core.profile_store import EXAMPLE_DIR

FORMATTED_CV = (EXAMPLE_DIR / "cv.md").read_text(encoding="utf-8")


class TestReadSource:
    def test_markdown_passes_through(self, tmp_path):
        path = tmp_path / "cv.md"
        path.write_text("# Someone\n", encoding="utf-8")
        assert read_source(path) == "# Someone\n"

    def test_plain_text(self, tmp_path):
        path = tmp_path / "cv.txt"
        path.write_text("Someone\nEngineer\n", encoding="utf-8")
        assert "Engineer" in read_source(path)

    def test_unsupported_format_is_rejected_by_name(self, tmp_path):
        path = tmp_path / "cv.docx"
        path.write_bytes(b"PK\x03\x04")
        with pytest.raises(ValueError, match="Unsupported CV format"):
            read_source(path)


class TestIngestFile:
    def test_a_formatted_markdown_cv_skips_the_model(self, tmp_path):
        """A .md that already has meta blocks is in the target format. Paying for
        a conversion would be waste, so no call should be made at all."""
        source = tmp_path / "cv.md"
        source.write_text(FORMATTED_CV, encoding="utf-8")
        client = FakeLLMClient(text="SHOULD NOT BE USED")

        written = ingest_file(source, tmp_path / "out", client)

        assert client.calls == []
        assert written == FORMATTED_CV
        assert (tmp_path / "out" / "cv.md").read_text(encoding="utf-8") == FORMATTED_CV

    def test_unformatted_text_goes_through_the_model(self, tmp_path):
        source = tmp_path / "cv.txt"
        source.write_text("LEVI\nEngineer at Acme\n" * 20, encoding="utf-8")
        client = FakeLLMClient(text="# Converted\n")

        written = ingest_file(source, tmp_path / "out", client)

        assert len(client.calls) == 1
        assert written == "# Converted\n"

    def test_the_example_cv_is_the_prompt_s_worked_example(self, tmp_path):
        """The prompt carries profile.example/cv.md rather than a prose
        description of the format, so the target cannot drift from the file our
        own parser tests exercise."""
        source = tmp_path / "cv.txt"
        source.write_text("plain text cv\n" * 30, encoding="utf-8")
        client = FakeLLMClient(text="# X\n")

        ingest_file(source, tmp_path / "out", client)

        system = client.calls[0]["system"]
        assert "Mara Okonjo" in system
        assert "<!--meta" in system

    def test_the_cv_text_is_sent_as_payload_not_instruction(self, tmp_path):
        """Payload goes on stdin in the real client. Keeping it out of the
        instruction is what makes that possible."""
        source = tmp_path / "cv.txt"
        source.write_text("DISTINCTIVE MARKER\n" * 30, encoding="utf-8")
        client = FakeLLMClient(text="# X\n")

        ingest_file(source, tmp_path / "out", client)

        assert "DISTINCTIVE MARKER" in client.calls[0]["payload"]
        assert "DISTINCTIVE MARKER" not in client.calls[0]["instruction"]


class TestOverwriteGuard:
    def test_refuses_to_clobber_an_existing_cv(self, tmp_path):
        """cv.md is the source of truth and is meant to be hand-edited. Re-running
        ingestion for a new PDF must not silently eat last time's corrections."""
        out = tmp_path / "out"
        out.mkdir()
        (out / "cv.md").write_text("# Hand-edited, precious\n", encoding="utf-8")
        source = tmp_path / "new.txt"
        source.write_text("a new cv\n" * 30, encoding="utf-8")
        client = FakeLLMClient(text="# Replacement\n")

        with pytest.raises(CvAlreadyExists):
            ingest_file(source, out, client)

        assert (out / "cv.md").read_text(encoding="utf-8") == "# Hand-edited, precious\n"

    def test_refuses_before_spending_anything(self, tmp_path):
        """The guard runs ahead of the model call, so a refused run is free."""
        out = tmp_path / "out"
        out.mkdir()
        (out / "cv.md").write_text("# Precious\n", encoding="utf-8")
        source = tmp_path / "new.txt"
        source.write_text("a new cv\n" * 30, encoding="utf-8")
        client = FakeLLMClient(text="# Replacement\n")

        with pytest.raises(CvAlreadyExists):
            ingest_file(source, out, client)

        assert client.calls == []

    def test_force_overwrites(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "cv.md").write_text("# Old\n", encoding="utf-8")
        source = tmp_path / "new.txt"
        source.write_text("a new cv\n" * 30, encoding="utf-8")

        ingest_file(source, out, FakeLLMClient(text="# New\n"), overwrite=True)

        assert (out / "cv.md").read_text(encoding="utf-8") == "# New\n"


class TestStripFences:
    def test_removes_a_markdown_fence_the_model_added_anyway(self):
        assert _strip_fences("```markdown\n# Hi\n```") == "# Hi\n"

    def test_leaves_unfenced_text_alone(self):
        assert _strip_fences("# Hi\n") == "# Hi\n"

    def test_leaves_an_unterminated_fence_alone(self):
        """Better to keep text we do not understand than to eat a line of it."""
        assert _strip_fences("```\n# Hi").startswith("```")
