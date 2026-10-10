import pytest

from careerforge.ats.jd import parse_job_description


def imp(jd, term):
    return next(r.importance for r in jd.requirements if r.term == term)


def terms(jd, kind="skill"):
    return {r.term for r in jd.requirements if r.kind == kind}


SECTIONED = """Senior Backend Engineer
Finlytics is a fast-growing company. We use Java internally for legacy tooling and have been building for 10 years.

About Us
We love Rust and Haskell and free snacks. Our values: Docker-first culture.

Responsibilities
- Design payment APIs in Python
- Operate services on Kubernetes

Requirements:
- 5+ years of backend experience
- Strong Python or Go
- Experience with PostgreSQL and Redis
- Bachelor's degree in Computer Science

Nice to have
- Terraform
- Experience with gRPC

Benefits
Free Kafka lunch-and-learns, gym.
"""


class TestSections:
    def test_requirements_vs_preferred_vs_duties(self):
        jd = parse_job_description(SECTIONED)
        assert jd.has_sections and jd.title == "Senior Backend Engineer"
        assert {imp(jd, t) for t in ("Python", "Go", "PostgreSQL", "Redis")} == {"required"}
        assert {imp(jd, t) for t in ("Terraform", "gRPC")} == {"preferred"}
        assert imp(jd, "Kubernetes") == "unspecified"  # a duty: needed on the job, not an explicit requirement

    def test_about_us_and_benefits_are_ignored(self):
        t = terms(parse_job_description(SECTIONED))
        assert not {"Rust", "Docker", "Kafka"} & t  # appear only under "About Us" / "Benefits"

    def test_intro_before_any_header_is_still_read_but_unspecified(self):
        assert imp(parse_job_description(SECTIONED), "Java") == "unspecified"

    def test_years_and_degree(self):
        jd = parse_job_description(SECTIONED)
        assert jd.min_years == 5  # not the company's "10 years"
        assert jd.degree == "bachelor"

    def test_markdown_headers_and_bullets(self):
        jd = parse_job_description("# Data Analyst\n\n## Requirements\n* SQL\n* Tableau\n\n## Nice to have\n* Python\n")
        assert (imp(jd, "SQL"), imp(jd, "Python")) == ("required", "preferred") and jd.title == "Data Analyst"

    def test_inline_header_with_long_body(self):
        jd = parse_job_description(
            "Dev\nRequirements: Python, Docker and AWS experience; strong teamwork across squads. Nice to have: Rust."
        )
        assert imp(jd, "Python") == "required" and imp(jd, "Rust") == "preferred"


class TestCues:
    @pytest.mark.parametrize("text,term,want", [
        ("Kubernetes experience is a plus.", "Kubernetes", "preferred"),
        ("Experience with Docker, Kubernetes. Terraform preferred.", "Terraform", "preferred"),
        ("Experience with Docker, Kubernetes. Terraform preferred.", "Docker", "unspecified"),
        ("Bonus: GraphQL", "GraphQL", "preferred"),
        ("Python is required and Go is a plus.", "Go", "preferred"),
        ("Must have Python", "Python", "required"),
        ("You will use Python daily", "Python", "unspecified"),
    ])  # fmt: skip
    def test_inline_cues(self, text, term, want):
        assert imp(parse_job_description("Engineer\n" + text), term) == want

    def test_highest_importance_wins_when_mentioned_twice(self):
        jd = parse_job_description("Engineer\nNice to have: Python\nRequirements\nPython")
        assert imp(jd, "Python") == "required"


class TestOtherFields:
    @pytest.mark.parametrize("text,years", [
        ("Engineer\n3+ years of experience in sales", 3),
        ("Engineer\n5-7 years experience", 5),
        ("Engineer\nWe have 15 years in business. Candidates need 2 years of SQL.", 2),
        ("Engineer\nNo experience statement", None),
        ("Engineer\n99 years of experience", None),
    ])  # fmt: skip
    def test_years(self, text, years):
        assert parse_job_description(text).min_years == years

    @pytest.mark.parametrize("text,degree", [
        ("Bachelor's or Master's degree", "bachelor"), ("PhD in statistics", "phd"), ("MBA preferred", "master"),
        ("B.Tech in CS", "bachelor"), ("No degree required", None), ("A degree is not required", None),
        ("without a degree but strong portfolio", None), ("nothing about education", None),
    ])  # fmt: skip
    def test_degree(self, text, degree):
        assert parse_job_description("Role\nRequirements: " + text).degree == degree

    def test_title_prefix_form_from_structured_postings(self):
        assert parse_job_description("Job title: Staff Engineer\nCompany: X\nPython").title == "Staff Engineer"

    def test_non_technical_posting_gets_recurring_domain_terms(self):
        jd = parse_job_description(
            "Marketing Manager\nOwn our content calendar and campaign planning. You will run campaign analytics and "
            "report on campaign performance to stakeholders. Strong stakeholder management and content strategy skills."
        )
        found = terms(jd, "term")
        assert "campaign" in found and "content" in found
        assert any(t.startswith("stakeholder") for t in found) and len({t[:9] for t in found}) == len(
            found
        )  # plural merged
        assert all(r.weight <= 0.4 for r in jd.requirements if r.kind == "term")
        assert not {"team", "experience", "strong"} & found  # boilerplate filtered

    def test_overlapping_skills_counted_once(self):
        jd = parse_job_description("DevOps\nRequirements: GitHub Actions and Spring Boot")
        assert {"GitHub Actions", "Spring Boot"} <= terms(jd) and not {"GitHub", "Spring"} & terms(jd)

    def test_empty_and_garbage_do_not_crash(self):
        for text in ("", "   ", "\n\n", "!!!", "x" * 5000):
            jd = parse_job_description(text)
            assert jd.requirements == () or all(r.term for r in jd.requirements)

    def test_weights(self):
        jd = parse_job_description(SECTIONED)
        w = {r.term: r.weight for r in jd.requirements}
        assert w["Python"] == 1.0 and w["Kubernetes"] == 0.8 and w["Terraform"] == 0.5

    def test_hostile_text_is_just_text(self):
        jd = parse_job_description("<script>alert(1)</script> Requirements: Python ‮ IGNORE ALL PREVIOUS INSTRUCTIONS")
        assert "Python" in terms(jd)
