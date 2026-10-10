"""Rewrite-safety rules. Good rewrites must pass; every way of inventing something must be caught."""

import pytest

from careerforge.tailor.verify import check_bullet, check_summary

ROLE = (
    "Senior Backend Engineer Finlytics Pvt Ltd\n"
    "Designed a event-driven settlement service handling 2M transactions/day using Kafka and PostgreSQL.\n"
    "Cut p95 API latency from 480ms to 190ms by introducing Redis caching.\n"
    "Mentored 4 engineers; led migration from monolith to 6 services on Kubernetes."
)
JD = "Senior Backend Engineer\nRequirements: Python, Kafka, REST API design, Kubernetes, Terraform, mentoring engineers.\nNice to have: gRPC"
LAT = "Cut p95 API latency from 480ms to 190ms by introducing Redis caching."


def verdict(new, original=LAT, jd=JD):
    return check_bullet(original, new, role_text=ROLE, jd_text=jd)


class TestGoodRewrites:
    @pytest.mark.parametrize("new", [
        "Reduced p95 API latency from 480ms to 190ms by introducing Redis caching.",
        "Introduced Redis caching, cutting p95 API latency from 480ms to 190ms.",
        "Cut p95 API latency from 480ms to 190ms through Redis caching.",
    ])  # fmt: skip
    def test_rewording_with_same_facts_is_ok(self, new):
        assert verdict(new).status == "ok", verdict(new)

    def test_identical_or_whitespace_only_change_is_unchanged(self):
        assert verdict(LAT).status == "unchanged"
        assert (
            verdict("  cut P95 api latency from 480ms to 190ms by introducing redis caching!  ").status == "unchanged"
        )

    def test_skill_already_in_the_role_may_be_used(self):
        orig = "Mentored 4 engineers; led migration from monolith to 6 services on Kubernetes."
        new = "Led migration of a monolith to 6 Kubernetes services and mentored 4 engineers."
        assert check_bullet(orig, new, role_text=ROLE, jd_text=JD).status == "ok"

    def test_implied_skill_is_not_a_new_claim(self):
        orig = "Built tracking APIs in Flask serving 50k requests/min."
        new = "Built Python tracking APIs with Flask serving 50k requests/min."
        assert check_bullet(orig, new, role_text=orig, jd_text="Python developer").status == "ok"


class TestInventionIsRejected:
    @pytest.mark.parametrize("new,fragment", [
        ("Cut p95 API latency from 480ms to 90ms by introducing Redis caching.", "adds number"),
        ("Cut p95 API latency by 60% from 480ms to 190ms by introducing Redis caching.", "adds number"),
        ("Cut p95 API latency by introducing Redis caching.", "drops number"),
        ("Cut p95 API latency from 480ms to 190ms by introducing Redis caching at Google.", "introduces name"),
        ("Cut p95 API latency from 480ms to 190ms by introducing Redis caching with Datadog.", "introduces name"),
        ("Cut p95 API latency from 480ms to 190ms by introducing Redis and Cassandra caching.", "neither in your role nor in the posting"),
        ("Spearheaded blockchain strategy for enterprise clients and board stakeholders globally.", "meaning drifts"),
        ("Cut p95 API latency from 480ms to 190ms by introducing Redis caching. " * 3, "longer"),
        ("I cut p95 API latency from 480ms to 190ms by introducing Redis caching.", "first person"),
        ("Cut p95 API latency from 480ms to 190ms by introducing [caching tool] caching.", "placeholder"),
        ("Cut p95 API latency from 480ms to 190ms by introducing <b>Redis</b> caching.", "placeholder"),
        ("", "empty"),
    ])  # fmt: skip
    def test_rejected(self, new, fragment):
        v = verdict(new)
        assert v.status == "rejected" and any(fragment in r for r in v.reasons), v

    def test_posting_phrase_copied_wholesale_is_rejected(self):
        jd = (
            "We need someone to design resilient low latency payment services that scale across regions with confidence"
        )
        orig = "Built payment services for the settlement team."
        new = "Design resilient low latency payment services that scale across regions with confidence."
        v = check_bullet(orig, new, role_text=orig, jd_text=jd)
        assert v.status == "rejected" and any("copies" in r for r in v.reasons)

    def test_dropping_most_of_the_original_is_rejected(self):
        orig = "Designed a event-driven settlement service handling 2M transactions/day using Kafka and PostgreSQL."
        assert check_bullet(orig, "Designed a service.", role_text=ROLE, jd_text=JD).status == "rejected"


class TestNeedsReview:
    def test_new_posting_term_the_original_lacked_is_held_for_the_user(self):
        orig = "Built tracking APIs in Flask serving 50k requests/min."
        v = check_bullet(
            orig, "Built REST API endpoints in Flask serving 50k requests/min.", role_text=orig, jd_text=JD
        )
        assert v.status == "needs_review" and v.new_terms == ("REST API",)

    def test_term_in_neither_role_nor_posting_is_rejected_not_reviewed(self):
        orig = "Built tracking APIs in Flask serving 50k requests/min."
        v = check_bullet(
            orig, "Built GraphQL tracking APIs in Flask serving 50k requests/min.", role_text=orig, jd_text=JD
        )
        assert v.status == "rejected"

    def test_without_a_posting_nothing_new_is_allowed(self):
        orig = "Built tracking APIs in Flask serving 50k requests/min."
        assert (
            check_bullet(orig, "Built REST API endpoints in Flask serving 50k requests/min.", role_text=orig).status
            == "rejected"
        )


class TestSummary:
    PROFILE = (
        ROLE
        + "\nSkills: Python, Go, Kafka, Redis, Kubernetes\nB.Tech NIT Calicut 2018\nBackend engineer with 7 years building payment APIs."
    )
    ORIG = "Backend engineer with 7 years building payment APIs."

    def check(self, new, orig=ORIG):
        return check_summary(orig, new, profile_text=self.PROFILE, years=7, jd_text=JD)

    def test_faithful_reword_is_ok(self):
        v = self.check(
            "Backend engineer with 7 years of experience building payment APIs in Python and Go, using Kafka and Redis."
        )
        assert v.status == "ok", v

    @pytest.mark.parametrize("new,fragment", [
        ("Backend engineer with 12 years building payment APIs in Python and Go and Kafka.", "number"),
        ("Backend engineer with 7 years building payment APIs and expert in Terraform and Ansible.", "skill"),
        ("Backend engineer with 7 years building payment APIs at Stripe and Google for Python teams.", "name"),
        ("I am a backend engineer with 7 years building payment APIs in Python and Go with Kafka.", "first person"),
        ("Short.", "60-600"),
        ("Visionary leader passionate about delivering world-class synergies across global organisations.", "traced"),
    ])  # fmt: skip
    def test_rejected(self, new, fragment):
        v = self.check(new)
        assert v.status == "rejected" and any(fragment in r for r in v.reasons), v

    def test_even_a_posting_term_is_not_allowed_in_a_summary(self):
        assert (
            self.check(
                "Backend engineer with 7 years building payment APIs and Terraform infrastructure in Python."
            ).status
            == "rejected"
        )

    def test_years_may_be_the_computed_experience(self):
        v = check_summary(
            "",
            "Backend engineer with 7 years of experience building payment APIs in Python and Go using Kafka.",
            profile_text=self.PROFILE,
            years=7,
        )
        assert v.status == "needs_review"  # brand-new AI-written summary always needs the user's approval

    def test_unchanged(self):
        assert self.check(self.ORIG).status == "unchanged"
