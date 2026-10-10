from datetime import date

import pytest

from careerforge.models import Contact, DateRange, Education, Experience, Profile, Project
from careerforge.readiness import NotReady, check, require_ready

TODAY = date(2026, 6, 1)


def good(**over) -> Profile:
    base = dict(
        name="Priya Nair",
        headline="Senior Backend Engineer",
        summary="Backend engineer with 7 years building payment APIs in Python and Go.",
        contact=Contact(email="priya@gmail.com", phone="+91 98765 43210", location="Bengaluru, India"),
        skills=["Python", "Go", "Kafka"],
        experience=[
            Experience(
                title="Senior Engineer",
                company="Finlytics",
                dates=DateRange(start="2021-03", current=True),
                bullets=[
                    "Cut p95 latency from 480ms to 190ms using Redis caching",
                    "Led migration of 6 services to Kubernetes, improving deploys 3x",
                ],
            ),
            Experience(
                title="Engineer",
                company="ShipFast",
                dates=DateRange(start="2018-07", end="2021-02"),
                bullets=["Built real-time tracking APIs serving 50k requests/min"],
            ),
        ],
    )
    base.update(over)
    return Profile(**base)


def codes(r, sev=None):
    return {i.code for i in (r.of(sev) if sev else r.issues)}


def test_good_profile_is_ready_with_no_blockers():
    r = check(good(), today=TODAY)
    assert r.ready and not r.blockers


@pytest.mark.parametrize(
    "over,code",
    [
        (dict(name=""), "R001"),
        (dict(name="Candidate"), "R001"),
        (dict(name="Your Name"), "R001"),
        (dict(contact=Contact(phone="+91 98765 43210")), "R002"),
        (dict(contact=Contact(email="a@example.com")), "R007"),
        (dict(experience=[], projects=[], education=[]), "R004"),
    ],
)
def test_blockers(over, code):
    r = check(good(**over), today=TODAY)
    assert code in codes(r, "blocker") and not r.ready


@pytest.mark.parametrize(
    "text",
    [
        "Built [mention a specific relevant achievement] at scale",
        "Interview thank you about [specific topic from interview]",
        "Welcome {name} to {company}",
        "Improved C++ <b>perf by 30%",
        "Lorem ipsum dolor sit amet",
        "TODO fill this in",
        "Contact your_email here",
    ],
)
def test_leftover_placeholders_block_export(text):
    p = good(summary=text)
    r = check(p, today=TODAY)
    assert "R005" in codes(r, "blocker")


@pytest.mark.parametrize(
    "text", ["Python [3.11] services", "Reduced cost by $5k & more", "Built a<b logic", "R&D team"]
)
def test_normal_text_is_not_flagged_as_placeholder(text):
    assert "R005" not in codes(check(good(summary=text), today=TODAY))


def test_unfilled_bracket_that_is_not_obviously_a_placeholder_only_warns():
    r = check(good(summary="Certified [ISO 27001] security lead"), today=TODAY)
    assert r.ready and "R005" in codes(r, "warning")


def test_missing_phone_and_summary_and_skills_warn():
    r = check(good(contact=Contact(email="a@gmail.com"), summary="", skills=[]), today=TODAY)
    assert {"R003", "R014", "R016"} <= codes(r, "warning") and r.ready


def test_experience_without_dates_or_bullets_warns():
    r = check(good(experience=[Experience(title="Dev", company="Acme")]), today=TODAY)
    assert {"R018", "R009"} <= codes(r, "warning")


def test_first_person_and_duplicates_and_long_bullets_warn():
    long = "Delivered " + "very " * 70 + "large results"
    e = Experience(
        title="Dev",
        company="Acme",
        dates=DateRange(start="2020"),
        bullets=[
            "I built the API for my team",
            "Shipped feature X to 10k users",
            "shipped feature x to 10k users",
            long,
        ],
    )
    r = check(good(experience=[e]), today=TODAY)
    assert {"R012", "R013", "R010"} <= codes(r, "warning")


def test_weak_verbs_and_no_numbers_are_tips():
    e = Experience(
        title="Dev",
        company="Acme",
        dates=DateRange(start="2020"),
        bullets=[
            "Responsible for maintaining the website",
            "Worked on several backend tasks",
            "Helped with the deployment process",
        ],
    )
    r = check(good(experience=[e]), today=TODAY)
    assert {"R019", "R011"} <= codes(r, "tip")


def test_employment_gap_detected():
    p = good(
        experience=[
            Experience(title="A", company="X", dates=DateRange(start="2015", end="2016")),
            Experience(title="B", company="Y", dates=DateRange(start="2019-01", end="2020")),
        ]
    )
    gap = [i for i in check(p, today=TODAY).issues if i.code == "R015"]
    assert gap and "gap" in gap[0].message


def test_no_gap_flag_for_adjacent_or_current_roles():
    assert "R015" not in codes(check(good(), today=TODAY))


def test_future_start_warns():
    p = good(experience=[Experience(title="A", company="X", dates=DateRange(start="2030"), bullets=["Did a thing 2x"])])
    assert "R008" in codes(check(p, today=TODAY))


def test_unconfirmed_suggestions_are_reported_and_do_not_count_as_content():
    p = good(experience=[], projects=[Project(name="Freelance gig", origin="suggested")])
    r = check(p, today=TODAY)
    assert "R006" in codes(r) and "R004" in codes(r, "blocker")  # suggestion cannot satisfy "has content"


def test_placeholder_inside_unconfirmed_item_is_ignored_because_it_will_not_be_exported():
    p = good(projects=[Project(name="x", description="[fill this in later]", origin="suggested")])
    assert "R005" not in codes(check(p, today=TODAY))


def test_require_ready_returns_exportable_view_and_raises_otherwise():
    p = good(projects=[Project(name="Suggested", origin="suggested")])
    out = require_ready(p)
    assert out.projects == []
    with pytest.raises(NotReady, match="name"):
        require_ready(good(name=""))


def test_issues_sorted_blockers_first():
    r = check(good(name="", contact=Contact(), summary=""), today=TODAY)
    sev = [i.severity for i in r.issues]
    assert sev == sorted(sev, key=["blocker", "warning", "tip"].index)


def test_hostile_fixture_shaped_profile_is_not_ready():
    p = Profile(
        name="<script>alert('xss-name')</script>",
        contact=Contact(email="evil@example.com"),
        education=[Education(degree="B.Tech")],
    )
    r = check(p, today=TODAY)
    assert not r.ready and {"R005", "R007"} <= codes(r, "blocker")


class TestYearsClaim:
    def codes(self, summary, headline="Backend Engineer", **over):
        return [
            (i.severity, i.code)
            for i in check(good(summary=summary, headline=headline, **over), today=TODAY).issues
            if i.code == "R020"
        ]

    # good(): Mar 2021 -> now (5 y 2 m) plus an earlier role, see the fixture for the exact span

    def test_overclaim_is_a_warning(self):
        assert self.codes("Engineer with 15 years of experience in Python.") == [("warning", "R020")]

    def test_underclaim_is_only_a_tip(self):
        assert self.codes("Engineer with 1 year of experience in Python.") == [("tip", "R020")]

    def test_claim_within_a_year_of_the_dates_is_fine(self):
        computed = __import__("careerforge.ats.match", fromlist=["x"]).experience_months(good(), TODAY) // 12
        assert self.codes(f"Engineer with {computed} years of experience.") == []
        assert self.codes(f"Engineer with {computed + 1}+ years of experience.") == []

    def test_headline_claims_are_checked_too(self):
        assert self.codes("Engineer.", headline="Engineer, 20 years experience") == [("warning", "R020")]

    def test_other_uses_of_years_are_not_claims(self):
        assert self.codes("Led a 12 year migration of legacy systems to the cloud.") == []
        assert self.codes("Shipped the product 9 years ago.") == []

    def test_no_dated_roles_means_nothing_to_compare(self):
        undated = [Experience(title="Engineer", company="X", bullets=["Built the thing end to end for customers"])]
        assert self.codes("Engineer with 15 years of experience.", experience=undated) == []

    def test_no_experience_at_all_is_not_flagged_here(self):
        assert self.codes("Student with 3 years of experience in Python.", experience=[]) == []
