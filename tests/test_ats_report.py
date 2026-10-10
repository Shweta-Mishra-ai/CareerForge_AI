"""ATS v2 behaviour. These tests encode what a *sensible* score must do, not specific magic numbers."""

import random
from datetime import date

import pytest
from helpers import pdf_from_html
from test_grounding import faithful_standard

from careerforge.ats import match as mt
from careerforge.ats.report import WEIGHTS, analyze, compare
from careerforge.models import Contact, DateRange, Education, Experience, Profile

TODAY = date(2026, 10, 10)


@pytest.fixture
def backend_jd(fixture_text):
    return fixture_text("jd_backend.txt")


@pytest.fixture
def data_jd(fixture_text):
    return fixture_text("jd_data.txt")


@pytest.fixture
def devops_jd(fixture_text):
    return fixture_text("jd_devops.txt")


def kw(report):
    return report.component("keywords").score


def profile(skills=(), bullets=(), title="Engineer", headline="", summary="", **kwargs):
    return Profile(
        name="Test Person", headline=headline, summary=summary, skills=list(skills),
        contact=Contact(email="t@gmail.com", phone="+91 98765 43210", location="Pune", github="github.com/t"),
        experience=[Experience(title=title, company="Acme", dates=DateRange(start="2020", current=True), bullets=list(bullets))],
        **kwargs,
    )  # fmt: skip


class TestRelevance:
    def test_matching_posting_beats_mismatched_ones(self, backend_jd, data_jd, devops_jd):
        p = faithful_standard()
        scores = {
            n: analyze(p, t, today=TODAY).overall
            for n, t in (("backend", backend_jd), ("data", data_jd), ("devops", devops_jd))
        }
        assert scores["backend"] > scores["devops"] > scores["data"]
        assert scores["backend"] >= 75 and scores["data"] < 55

    def test_compare_ranks_best_first(self, backend_jd, data_jd, devops_jd):
        ranked = compare(
            faithful_standard(), {"data": data_jd, "backend": backend_jd, "devops": devops_jd}, today=TODAY
        )
        assert [n for n, _ in ranked] == ["backend", "devops", "data"]

    def test_deterministic(self, backend_jd):
        a, b = (
            analyze(faithful_standard(), backend_jd, today=TODAY),
            analyze(faithful_standard(), backend_jd, today=TODAY),
        )
        assert a == b


class TestEvidenceBeatsStuffing:
    JD = "Backend Engineer\nRequirements: Kafka, Redis, Docker and Kubernetes experience."

    def test_showing_skills_in_bullets_beats_just_listing_them(self):
        listed = profile(
            skills=["Kafka", "Redis", "Docker", "Kubernetes"], bullets=["Maintained internal tools for the team."]
        )
        shown = profile(skills=["Kafka", "Redis", "Docker", "Kubernetes"],
                        bullets=["Built Kafka consumers handling 2M events/day.", "Cached hot paths in Redis, cutting latency 40%.",
                                 "Shipped Docker images to Kubernetes clusters."])  # fmt: skip
        assert kw(analyze(shown, self.JD, today=TODAY)) == 100
        assert kw(analyze(listed, self.JD, today=TODAY)) == 70
        assert all(m.quality == mt.QUALITY_SKILLS_ONLY for m in analyze(listed, self.JD, today=TODAY).matches)

    def test_a_very_long_skills_list_is_worth_less_per_skill(self):
        filler = [f"Filler Skill {i}" for i in range(30)]
        normal = profile(skills=["Kafka", "Redis", "Docker", "Kubernetes"])
        stuffed = profile(skills=["Kafka", "Redis", "Docker", "Kubernetes", *filler])
        assert kw(analyze(stuffed, self.JD, today=TODAY)) < kw(analyze(normal, self.JD, today=TODAY))

    def test_summary_only_mention_is_weakest_evidence(self):
        p = profile(summary="Engineer who works with Kafka daily.")
        m = analyze(p, "Engineer\nRequirements: Kafka", today=TODAY).matches[0]
        assert m.where == ("summary",) and m.quality == mt.QUALITY_SUMMARY_ONLY

    def test_missing_skills_lower_the_score_monotonically(self):
        scores = []
        for n in range(5):
            have = ["Kafka", "Redis", "Docker", "Kubernetes"][:n]
            scores.append(
                kw(
                    analyze(
                        profile(bullets=[f"Used {h} in production systems daily." for h in have]), self.JD, today=TODAY
                    )
                )
                or 0
            )
        assert scores == sorted(scores) and scores[0] == 0 and scores[-1] == 100


class TestImplication:
    def test_framework_implies_language_but_not_the_reverse(self):
        flask = profile(bullets=["Built Flask services serving 50k requests/min."])
        r = analyze(flask, "Dev\nRequirements: Python", today=TODAY)
        assert r.matches[0].implied_by == "Flask"
        assert r.matches[0].quality == pytest.approx(
            0.85
        )  # literal on purpose: a constant compared to itself proves nothing
        explicit = analyze(
            profile(bullets=["Built Python services serving 50k requests/min."]),
            "Dev\nRequirements: Python",
            today=TODAY,
        )
        assert kw(r) == 85 and kw(explicit) == 100
        python = profile(bullets=["Wrote Python scripts for data cleanup tasks."])
        assert analyze(python, "Dev\nRequirements: Flask", today=TODAY).missing[0].term == "Flask"

    def test_explicit_beats_implied(self):
        both = profile(bullets=["Built Flask services and Python tooling for 3 teams."])
        assert analyze(both, "Dev\nRequirements: Python", today=TODAY).matches[0].implied_by is None

    def test_database_implies_sql(self):
        r = analyze(profile(skills=["PostgreSQL"]), "Analyst\nRequirements: SQL", today=TODAY)
        assert r.matches[0].implied_by == "PostgreSQL" and r.missing == ()


class TestExperienceYears:
    def months(self, *roles):
        exps = [
            Experience(title="T", dates=DateRange(start=s, end=e, current=(e == "now")))
            if e != "now"
            else Experience(title="T", dates=DateRange(start=s, current=True))
            for s, e in roles
        ]
        return mt.experience_months(Profile(experience=exps), TODAY)

    def test_overlapping_roles_counted_once(self):
        assert self.months(("2020-01", "2021-12"), ("2021-01", "2022-12")) == 36

    def test_current_role_runs_to_today(self):
        assert self.months(("2025-10", "now")) == 13

    def test_year_only_dates_span_the_year(self):
        assert self.months(("2019", "2020")) == 24

    def test_undated_roles_contribute_nothing_and_future_is_clamped(self):
        assert mt.experience_months(Profile(experience=[Experience(title="T")]), TODAY) == 0
        assert self.months(("2030-01", "2031-12")) == 0

    def test_score_scales_with_requirement_and_caps_at_100(self):
        p = profile()  # 2020 -> today
        assert analyze(p, "Dev\nRequirements: 3+ years of Python", today=TODAY).component("experience").score == 100
        short = analyze(p, "Dev\nRequirements: 12+ years of Python", today=TODAY).component("experience")
        assert 40 <= short.score <= 60 and any(
            "12+ years" in f.message and "inflate" in f.message
            for f in analyze(p, "Dev\nRequirements: 12+ years of Python", today=TODAY).fixes
        )


class TestRoleAlignment:
    @pytest.mark.parametrize("headline,title,jd_title,expected", [
        ("Backend Engineer", "Backend Engineer", "Senior Backend Engineer - Payments", 100),
        ("", "Back-end Developer", "Backend Engineer", 50),
        ("Data Analyst", "Analyst", "Backend Engineer", 0),
    ])  # fmt: skip
    def test_alignment(self, headline, title, jd_title, expected):
        r = analyze(profile(headline=headline, title=title), f"{jd_title}\nRequirements: Python", today=TODAY)
        got = r.component("role").score
        assert got is not None and abs(got - expected) <= 34

    def test_seniority_words_ignored(self):
        r = analyze(profile(title="Backend Engineer"), "Staff Backend Engineer\nPython", today=TODAY)
        assert r.component("role").score == 100


class TestNoPostingAndWeirdPostings:
    def test_without_a_posting_it_is_a_quality_score_not_a_fake_match(self):
        r = analyze(faithful_standard(), None, today=TODAY)
        assert r.kind == "quality" and r.component("keywords") is None and r.missing == () and r.job_title == ""

    @pytest.mark.parametrize("text", ["", "   ", None])
    def test_blank_posting_is_treated_as_no_posting(self, text):
        assert analyze(faithful_standard(), text, today=TODAY).kind == "quality"

    def test_posting_with_no_extractable_requirements_is_reported_not_faked(self):
        r = analyze(faithful_standard(), "Welcome\nWe are a lovely company with snacks.", today=TODAY)
        assert (
            r.kind == "match"
            and r.component("keywords").score is None
            and any("No skills or requirements" in n for n in r.notes)
        )
        assert 0 <= r.overall <= 100

    def test_weights_renormalise_over_available_components(self, backend_jd):
        r = analyze(faithful_standard(), backend_jd, today=TODAY)
        scored = [c for c in r.components if c.score is not None]
        assert r.component("parse").score is None
        expected = round(sum(c.score * c.weight for c in scored) / sum(c.weight for c in scored))
        assert r.overall == expected and sum(WEIGHTS.values()) == 100

    def test_unconfirmed_ai_items_do_not_count_and_are_mentioned(self, backend_jd):
        base = faithful_standard()
        padded = base.model_copy(update={"experience": [*base.experience, Experience(title="Principal Kafka Wizard", company="Fake", origin="suggested",
                                          bullets=["Built Terraform and gRPC platforms 10x"])]})  # fmt: skip
        a, b = analyze(base, backend_jd, today=TODAY), analyze(padded, backend_jd, today=TODAY)
        assert (
            a.overall == b.overall
            and "Terraform" in {m.term for m in b.missing}
            and any("unconfirmed" in n for n in b.notes)
        )


class TestFixes:
    def test_missing_required_skill_fix_is_honest_and_ranked_first(self, backend_jd):
        r = analyze(faithful_standard(), backend_jd, today=TODAY)
        fix = next(f for f in r.fixes if f.path == "REST API")
        assert (
            fix.severity == "high" and "If you have real experience" in fix.message and "do not claim it" in fix.message
        )
        assert r.fixes[0].severity == "high"

    def test_no_fix_ever_tells_the_user_to_unconditionally_add_a_skill(self, backend_jd, data_jd, devops_jd):
        for jd in (backend_jd, data_jd, devops_jd):
            for f in analyze(faithful_standard(), jd, today=TODAY).fixes:
                if f.area == "keywords" and f.path and f.severity != "medium" or "asks for" in f.message:
                    assert (
                        "if you" in f.message.lower()
                        or "only if" in f.message.lower()
                        or "genuinely" in f.message.lower()
                    )

    def test_preferred_gaps_are_low_severity(self, backend_jd):
        r = analyze(faithful_standard(), backend_jd, today=TODAY)
        assert {f.severity for f in r.fixes if f.path in ("Terraform", "gRPC")} == {"low"}

    def test_structure_problems_become_fixes(self):
        p = profile().model_copy(update={"contact": Contact()})
        msgs = [f.message for f in analyze(p, None, today=TODAY).fixes if f.area == "structure"]
        assert any("Email" in m for m in msgs) and any("Full name" not in m for m in msgs)

    def test_skills_only_matches_get_a_show_it_in_a_bullet_fix(self):
        r = analyze(
            profile(skills=["Kafka"], bullets=["Maintained internal tools for the team."]),
            "Dev\nRequirements: Kafka",
            today=TODAY,
        )
        assert any("only listed under Skills" in f.message and f.path == "Kafka" for f in r.fixes)

    def test_bullets_without_numbers_are_flagged_with_their_path(self):
        r = analyze(profile(bullets=["Worked on the backend services of the company."]), None, today=TODAY)
        assert any(f.area == "quality" and f.path == "experience[0].bullets[0]" for f in r.fixes)

    def test_degree_requirement_without_education_is_flagged(self):
        r = analyze(profile(), "Dev\nRequirements: Bachelor's degree and Python", today=TODAY)
        assert any(f.path == "education" for f in r.fixes)
        assert not any(
            f.path == "education"
            for f in analyze(
                profile(education=[Education(degree="B.Tech")]), "Dev\nRequirements: Bachelor's degree", today=TODAY
            ).fixes
        )


def test_overall_is_always_between_0_and_100_for_random_inputs():
    rng = random.Random(7)
    words = [
        "Python",
        "Kafka",
        "Docker",
        "led",
        "built",
        "12%",
        "team",
        "SQL",
        "Excel",
        "and",
        ",",
        "Requirements:",
        "\n",
        "5+ years",
        "Nice to have",
        "<b>",
        "é",
    ]
    for _ in range(150):
        jd = " ".join(rng.choice(words) for _ in range(rng.randint(0, 60)))
        bullets = [" ".join(rng.choice(words) for _ in range(rng.randint(1, 12))) for _ in range(rng.randint(0, 5))]
        p = profile(
            skills=rng.sample(["Python", "Kafka", "SQL", "Excel", "Docker"], rng.randint(0, 5)), bullets=bullets
        )
        r = analyze(p, jd, today=TODAY)
        assert 0 <= r.overall <= 100 and all(c.score is None or 0 <= c.score <= 100 for c in r.components)


def test_hostile_profile_and_posting_do_not_crash(fixture_text):
    p = Profile(
        name="<script>alert(1)</script>",
        skills=["<img src=x>"],
        experience=[Experience(title="'; DROP TABLE", bullets=["{jd} {cv} \u202e"])],
    )
    assert 0 <= analyze(p, fixture_text("cv_hostile.txt"), today=TODAY).overall <= 100


# ── PDF readability: checks run on REAL generated PDFs ───────────────────────


def good_html():
    return (
        """<h1>Priya Nair</h1><p>priya.nair@example.com | +91 98765 43210 | Bengaluru, India</p>
    <h2>Experience</h2><p><b>Senior Backend Engineer</b>, Finlytics Pvt Ltd (Mar 2021 - Present)</p>
    <ul><li>Cut p95 API latency from 480ms to 190ms by introducing Redis caching.</li></ul>
    <p><b>Software Engineer</b>, ShipFast Logistics (Jul 2018 - Feb 2021)</p><ul><li>Built real-time tracking APIs in Flask.</li></ul>
    <h2>Education</h2><p>B.Tech Computer Science, NIT Calicut, 2018</p><h2>Skills</h2><p>Python, Go, Kafka, Redis</p>"""
        + " " * 300
    )


def columns_html():
    return """<div style="display:flex"><div style="width:30%;padding:8px"><h2>Contact</h2><p>priya.nair@example.com<br>+91 98765 43210</p>
    <h2>Skills</h2><p>Python, Go, Kafka, Redis</p><h2>Education</h2><p>B.Tech Computer Science, NIT Calicut, 2018</p></div>
    <div style="width:70%;padding:8px"><h1>Priya Nair</h1><h2>Experience</h2><p><b>Senior Backend Engineer</b>, Finlytics Pvt Ltd (Mar 2021 - Present)</p>
    <ul><li>Cut p95 API latency from 480ms to 190ms by introducing Redis caching.</li></ul>
    <p><b>Software Engineer</b>, ShipFast Logistics (Jul 2018 - Feb 2021)</p><ul><li>Built real-time tracking APIs in Flask.</li></ul></div></div>"""


class TestPdfReadability:
    def parse(self, html):
        r = analyze(faithful_standard(), None, pdf=pdf_from_html(html), today=TODAY)
        return r.component("parse"), r

    def test_clean_single_column_cv_reads_well(self):
        comp, r = self.parse(good_html())
        assert comp.score >= 90, [(c.label, c.detail) for c in comp.checks if not c.passed]
        assert not [f for f in r.fixes if f.area == "parse"]

    def test_sidebar_layout_is_flagged_as_column_risk(self):
        comp, r = self.parse(columns_html())
        assert any("Side-by-side columns" in f.message for f in r.fixes if f.area == "parse")
        assert comp.score < self.parse(good_html())[0].score

    def test_image_only_pdf_scores_zero(self):
        png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        comp, r = self.parse(f'<img src="data:image/png;base64,{png}" width="400" height="400">')
        assert comp.score == 0 and any("image" in f.message for f in r.fixes)

    def test_ruled_tables_are_detected_in_a_real_pdf(self):
        from helpers import pdf_with_ruled_table

        pdf = pdf_with_ruled_table(
            [
                "Priya Nair",
                "priya.nair@example.com",
                "+91 98765 43210",
                "Experience",
                "Education",
                "Skills",
                "Backend engineer with seven years of experience building payment and logistics APIs in Python and Go.",
                "Mentored four engineers and led the migration from a monolith to six services on Kubernetes.",
            ],
            [
                ["Senior Backend Engineer, Finlytics Pvt Ltd", "2021 - Present"],
                ["Software Engineer, ShipFast Logistics", "2018 - 2021"],
            ],
        )
        r = analyze(faithful_standard(), None, pdf=pdf, today=TODAY)
        table_check = next(c for c in r.component("parse").checks if c.label == "No bordered tables")
        assert not table_check.passed and any("Tables" in f.message for f in r.fixes if f.area == "parse")

    def test_missing_standard_headings_are_reported(self):
        html = (
            "<h1>Priya Nair</h1><p>priya.nair@example.com</p><h2>My Journey</h2><p>Senior Backend Engineer, Finlytics Pvt Ltd</p>"
            + "<p>filler text</p>" * 30
        )
        _, r = self.parse(html)
        assert "standard headings" in " ".join(f.message for f in r.fixes if f.area == "parse")

    def test_corrupt_pdf_is_reported_not_raised(self):
        r = analyze(faithful_standard(), None, pdf=b"%PDF-1.4 broken", today=TODAY)
        assert r.component("parse").score == 0 and any("could not be read" in f.message for f in r.fixes)

    def test_parse_component_changes_the_overall_only_when_a_pdf_is_given(self):
        base = analyze(faithful_standard(), None, today=TODAY)
        with_pdf = analyze(faithful_standard(), None, pdf=pdf_from_html(columns_html()), today=TODAY)
        assert base.component("parse").score is None and with_pdf.component("parse").score is not None
        assert with_pdf.overall != base.overall

    def test_missing_company_in_text_is_detected(self):
        html = good_html().replace("Finlytics Pvt Ltd", "").replace("ShipFast Logistics", "")
        _, r = self.parse(html)
        assert any("could not be found in the extracted text" in f.message for f in r.fixes)


def test_ats_only_mode_end_to_end_upload_a_pdf_and_score_that_same_file(backend_jd):
    """Old CV (PDF) -> ingest (AI scripted) -> review -> score against a posting AND check the uploaded file itself."""
    import json

    from careerforge.ai.client import AIClient, Clock, RetryPolicy, Route
    from careerforge.ai.providers import Completion
    from careerforge.ingest.pipeline import ingest_upload
    from careerforge.review import confirm_all

    reply = {
        "name": "Priya Nair", "contact": {"email": "priya.nair@example.com", "phone": "+91 98765 43210", "location": "Bengaluru, India"},
        "skills": ["Python", "Go", "Kafka", "Redis"],
        "experience": [
            {"title": "Senior Backend Engineer", "company": "Finlytics Pvt Ltd", "start": "Mar 2021", "end": "Present",
             "bullets": ["Cut p95 API latency from 480ms to 190ms by introducing Redis caching."]},
            {"title": "Software Engineer", "company": "ShipFast Logistics", "start": "Jul 2018", "end": "Feb 2021",
             "bullets": ["Built real-time tracking APIs in Flask."]},
        ],
        "education": [{"degree": "B.Tech Computer Science", "institution": "NIT Calicut", "start": "2018", "end": "2018"}],
    }  # fmt: skip

    class Fake:
        name = "fake"

        def complete(self, model, req):
            return Completion(json.dumps(reply), "fake", model)

    ai = AIClient(
        [Route(Fake(), "m")],
        RetryPolicy(),
        Clock(sleep=lambda s: None, monotonic=lambda: 0.0, uniform=lambda a, b: 0.0),
    )
    upload = pdf_from_html(good_html())
    ingested = ingest_upload("my_cv.pdf", upload, ai)
    assert ingested.grounding.findings == ()  # every claim traced back to the uploaded file
    report = analyze(confirm_all(ingested.profile), backend_jd, pdf=upload, today=TODAY)
    assert report.kind == "match" and report.component("parse").score >= 90 and 60 <= report.overall <= 100
    assert {m.requirement.term for m in report.matches} >= {"Python", "Go", "Kafka", "Redis"}
