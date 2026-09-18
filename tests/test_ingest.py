"""Tests for CV parsing.

Fixtures come from profile.example/ only. Never from profile/ - that holds real
personal data and must not leak into a committed test.
"""

from __future__ import annotations

import pytest

from core.ingest import (
    _split_role_heading,
    parse_cv_markdown,
    stubs_from_profile,
    unsourced_metrics,
)
from core.profile_store import EXAMPLE_DIR


@pytest.fixture(scope="module")
def profile():
    return parse_cv_markdown((EXAMPLE_DIR / "cv.md").read_text(encoding="utf-8"))


class TestRoleHeading:
    """The trailing comma-part means different things in different CVs, and the
    parenthetical is what disambiguates. These cases come from two real CVs that
    disagreed with each other.

    With a location in parens, the last comma-part is the ORG. Without one, the
    trailing comma-part is the LOCATION and the org is the middle part - the
    case that used to parse Droppo's org as "Colombia".
    """

    @pytest.mark.parametrize(
        "heading,title,org,dates",
        [
            ("Senior Backend Engineer, Payments Platform team, Vanta Pay "
             "(Remote) (2022 - Present)",
             "Senior Backend Engineer", "Vanta Pay", "2022 - Present"),
            ("Software Engineer, Data Platform team, Qrvey (Remote) "
             "(March 2025 - August 2026)",
             "Software Engineer", "Qrvey", "March 2025 - August 2026"),
            ("Full Stack Developer, Smartrader (Bogota) (March 2022 - December 2022)",
             "Full Stack Developer", "Smartrader", "March 2022 - December 2022"),
            ("Software Engineer & Founder, Droppo, Colombia (April 2020 - Present)",
             "Software Engineer & Founder", "Droppo", "April 2020 - Present"),
            ("Mobiliarisimo.com", "Mobiliarisimo.com", "", ""),
        ],
    )
    def test_splits(self, heading, title, org, dates):
        assert _split_role_heading(heading) == (title, org, dates)


class TestParseCv:
    def test_identity(self, profile):
        assert profile.name == "Mara Okonjo"
        assert profile.headline == "Backend Engineer"
        assert profile.summary.startswith("Backend engineer, 7 years")

    def test_roles_and_bullets(self, profile):
        assert [r.org for r in profile.roles] == ["Vanta Pay", "Rota Logistics"]
        assert [len(r.bullets) for r in profile.roles] == [4, 2]

    def test_meta_blocks_attach_to_the_bullet_above(self, profile):
        bullet = profile.roles[0].bullets[0]
        assert bullet.id == "vanta-idempotency-keys"
        assert "idempotency" in bullet.skills
        assert "exactly-once" in bullet.aliases

    def test_metric_none_is_not_a_metric(self, profile):
        """`metric: none` in the meta block means absent, not the string 'none'."""
        assert profile.roles[0].bullets[0].metric is None
        assert profile.roles[0].bullets[1].metric == "1,400 customers"

    def test_html_comments_are_ignored(self, profile):
        """The example CV opens with a long explanatory comment block. None of it
        should end up in the summary."""
        assert "SAMPLE DATA" not in profile.summary
        assert "gitignored" not in profile.summary

    def test_tech_terms_feed_the_asr_glossary(self, profile):
        terms = profile.tech_terms()
        assert "PostgreSQL" in terms and "Kafka" in terms
        assert len(terms) == len(set(terms)), "tech_terms must be deduplicated"


class TestStubs:
    def test_one_stub_per_bullet(self, profile):
        stubs = stubs_from_profile(profile)
        assert len(stubs) == 6
        assert all(s.status.value == "stub" for s in stubs)

    def test_a_stub_carries_the_claim_and_nothing_else(self, profile):
        """This is the day-one-usefulness property: a stub knows what you claim
        even though it has no STAR detail yet."""
        stub = stubs_from_profile(profile)[0]
        assert stub.claim
        assert stub.is_empty()

    def test_stub_ids_match_the_cv_bullet_ids(self, profile):
        """Ids must line up, or re-deriving would create duplicate stories
        alongside the ones you have already filled in."""
        stub_ids = {s.id for s in stubs_from_profile(profile)}
        bullet_ids = {b.id for r in profile.roles for b in r.bullets}
        assert stub_ids == bullet_ids


class TestUnsourcedMetrics:
    def test_finds_only_the_unsourced_ones(self, profile):
        found = {m for m, _ in unsourced_metrics(profile)}
        assert found == {"200ms p99, 400M rows", "hours to under ten minutes"}

    def test_a_sourced_metric_is_not_flagged(self, profile):
        """1,400 customers came from an incident report, so it is marked
        sourced and must not be listed as a number to defend."""
        assert "1,400 customers" not in {m for m, _ in unsourced_metrics(profile)}
