"""Grounding policy tests. The 'faithful' profiles are what a correct model returns for each fixture: they must
produce ZERO findings (false positives would make the feature useless); the 'invented' ones must be caught."""

from careerforge.ai.grounding import Source, ground_profile, profile_text
from careerforge.models import Certification, Contact, DateRange, Education, Experience, Profile, Project


def faithful_standard() -> Profile:
    return Profile(
        name="Priya Nair", headline="Senior Backend Engineer",
        summary="Backend engineer with 7 years building payment and logistics APIs in Python and Go.",
        contact=Contact(email="priya.nair@example.com", phone="+91 98765 43210", location="Bengaluru, India",
                        linkedin="linkedin.com/in/priya-nair-demo", github="github.com/priya-demo"),
        skills=["Python", "Go", "PostgreSQL", "Redis", "Kafka", "Docker", "Kubernetes", "AWS", "FastAPI", "Flask"],
        experience=[
            Experience(title="Senior Backend Engineer", company="Finlytics Pvt Ltd",
                       dates=DateRange(start="2021-03", current=True),
                       bullets=["Designed a event-driven settlement service handling 2M transactions/day using Kafka and PostgreSQL.",
                                "Cut p95 API latency from 480ms to 190ms by introducing Redis caching.",
                                "Mentored 4 engineers; led migration from monolith to 6 services on Kubernetes."]),
            Experience(title="Software Engineer", company="ShipFast Logistics",
                       dates=DateRange(start="2018-07", end="2021-02"),
                       bullets=["Built real-time tracking APIs in Flask serving 50k requests/min.",
                                "Wrote CI/CD pipelines with GitHub Actions and Docker."]),
        ],
        education=[Education(degree="B.Tech Computer Science", institution="NIT Calicut",
                             dates=DateRange(start="2018", end="2018"), grade="CGPA 8.4")],
        certifications=[Certification(name="AWS Certified Developer - Associate", date="2022")],
    )  # fmt: skip


def test_faithful_profile_has_zero_findings(fixture_text):
    out, report = ground_profile(faithful_standard(), fixture_text("cv_standard.txt"))
    assert report.findings == (), [f"{f.path}: {f.reason}" for f in report.findings]
    assert out == faithful_standard()


def test_faithful_fresher(fixture_text):
    p = Profile(
        name="Arjun Mehta", contact=Contact(email="arjun.mehta@example.com", location="Moradabad, UP, India",
                                            github="github.com/arjun-demo"),
        skills=["Python", "JavaScript", "React", "Node.js", "MongoDB", "Git"],
        education=[Education(degree="B.Tech Information Technology", institution="Demo Institute of Technology",
                             dates=DateRange(start="2021", end="2025"), grade="8.1 CGPA")],
        projects=[Project(name="Expense Tracker", tech=["React", "Node.js", "MongoDB"],
                          bullets=["Built a full-stack web app to track expenses with charts."]),
                  Project(name="Chatbot for college FAQs", tech=["Python", "Flask"],
                          bullets=["Built a retrieval chatbot that answers admission questions."])],
    )  # fmt: skip
    _, report = ground_profile(p, fixture_text("cv_fresher.txt"))
    assert report.findings == (), [f"{f.path}: {f.reason}" for f in report.findings]


def test_faithful_two_column_pdf_text(fixture_text):
    """Column-interleaved text must not break grounding (matching is order-insensitive)."""
    p = Profile(name="Sameer Khan", headline="Data Analyst", contact=Contact(email="sameer.khan@example.com",
                location="Pune, India", linkedin="linkedin.com/in/sameer-demo"),
                skills=["SQL", "Power BI", "Excel", "Python", "Pandas", "Tableau"],
                experience=[Experience(title="Data Analyst", company="RetailCo", dates=DateRange(start="2022", current=True),
                                       bullets=["Built 12 Power BI dashboards for sales.",
                                                "Automated weekly reports in Python, saving 6 hours per week."])])  # fmt: skip
    _, report = ground_profile(p, fixture_text("cv_two_column.txt"))
    assert report.findings == (), [f"{f.path}: {f.reason}" for f in report.findings]


class TestInventedContentIsCaught:
    def ground(self, fixture_text, **over):
        base = faithful_standard().model_dump()
        base.update(over)
        return ground_profile(Profile.model_validate(base), fixture_text("cv_standard.txt"))

    def test_invented_employer_is_demoted_not_exported(self, fixture_text):
        exp = [
            *faithful_standard().experience,
            Experience(title="Software Engineer", company="Google", bullets=["Led search ranking"]),
        ]
        out, report = self.ground(fixture_text, experience=[e.model_dump() for e in exp])
        assert [f.action for f in report.of("entity")] == ["unconfirmed"]
        assert out.experience[2].confirmed is False and out.experience[2].origin == "suggested"
        assert "Google" not in [e.company for e in out.exportable().experience]

    def test_invented_freelance_job_like_the_old_careerboost_prompt(self, fixture_text):
        job = Experience(
            title="Software Developer / Open Source Contributor",
            company="Freelance / Self-Employed",
            dates=DateRange(start="2022", current=True),
            bullets=["Built and maintained open-source projects."],
        )
        out, report = self.ground(fixture_text, experience=[job.model_dump()])
        assert out.exportable().experience == [] and report.of("entity")

    def test_invented_metric_removes_the_bullet(self, fixture_text):
        e = faithful_standard().experience[0].model_dump()
        e["bullets"] = [
            "Cut p95 API latency from 480ms to 190ms by introducing Redis caching.",
            "Cut p95 API latency from 480ms to 90ms by introducing Redis caching.",
            "Increased revenue by 340% through pricing work.",
        ]
        out, report = self.ground(fixture_text, experience=[e])
        assert out.experience[0].bullets == [e["bullets"][0]]
        assert len(report.of("bullet")) == 2

    def test_invented_wording_without_numbers_is_removed(self, fixture_text):
        e = faithful_standard().experience[0].model_dump()
        e["bullets"] = [
            "Spearheaded blockchain strategy for enterprise clients and board stakeholders.",
            "Cut p95 API latency from 480ms to 190ms by introducing Redis caching.",
        ]
        out, report = self.ground(fixture_text, experience=[e])
        assert out.experience[0].bullets == [e["bullets"][1]]
        assert [f.reason for f in report.of("bullet")] == ["wording cannot be traced to the document"]

    def test_light_rewording_of_a_real_bullet_is_kept(self, fixture_text):
        e = faithful_standard().experience[0].model_dump()
        e["bullets"] = ["Reduced p95 API latency from 480ms to 190ms by introducing Redis caching."]
        out, report = self.ground(fixture_text, experience=[e])
        assert out.experience[0].bullets == e["bullets"] and not report.findings

    def test_ai_authored_summary_is_cleared(self, fixture_text):
        out, report = self.ground(
            fixture_text, summary="Visionary leader passionate about delivering world-class synergies."
        )
        assert out.summary == "" and report.of("summary")

    def test_invented_skills_removed_real_ones_kept(self, fixture_text):
        out, report = self.ground(fixture_text, skills=["Python", "Rust", "Terraform", "k8s", "Kafka"])
        assert out.skills == ["Python", "Kubernetes", "Kafka"] and {f.text for f in report.of("skill")} == {
            "Rust",
            "Terraform",
        }

    def test_invented_dates_cleared(self, fixture_text):
        e = faithful_standard().experience[0].model_dump()
        e["dates"] = {"start": "2015-01", "end": "2020-12", "current": False}
        out, report = self.ground(fixture_text, experience=[e])
        assert out.experience[0].dates.is_empty() and report.of("date")

    def test_invented_contact_cleared(self, fixture_text):
        out, report = self.ground(
            fixture_text,
            contact=Contact(
                email="priya@gmail.com",
                phone="+1 555 123 4567",
                location="Berlin, Germany",
                linkedin="linkedin.com/in/someone-else",
            ).model_dump(),
        )
        assert out.contact == Contact() and len(report.of("contact")) == 4

    def test_invented_cert_and_education(self, fixture_text):
        out, report = self.ground(
            fixture_text,
            education=[Education(degree="MBA", institution="Harvard Business School").model_dump()],
            certifications=[Certification(name="Google Cloud Architect").model_dump()],
        )
        assert out.exportable().education == [] and out.exportable().certifications == []
        assert len(report.of("entity")) >= 3

    def test_invented_name_is_cleared_so_readiness_blocks(self, fixture_text):
        out, _ = self.ground(fixture_text, name="Rahul Sharma")
        assert out.name == ""

    def test_invented_grade(self, fixture_text):
        e = faithful_standard().education[0].model_dump()
        e["grade"] = "CGPA 9.8"
        out, report = self.ground(fixture_text, education=[e])
        assert out.education[0].grade == "" and report.of("grade")

    def test_input_profile_is_not_mutated(self, fixture_text):
        p = faithful_standard()
        before = p.model_dump()
        ground_profile(p.model_copy(update={"name": "Rahul Sharma"}), fixture_text("cv_standard.txt"))
        assert p.model_dump() == before


class TestSource:
    def test_accent_and_case_insensitive(self):
        assert Source("JOSÉ GARCÍA — Ingeniero").phrase("Jose Garcia")

    def test_hyphenated_line_break_rejoined(self):
        assert Source("Led the devel-\nopment of billing").phrase("development")

    def test_legal_suffixes_ignored(self):
        assert Source("Worked at Finlytics").phrase("Finlytics Pvt Ltd")

    def test_phone_formatting_insensitive(self):
        assert Source("Call 98765-43210").phone("+91 98765 43210")
        assert not Source("Call 98765-43210").phone("+91 11111 22222")

    def test_numbers_with_commas(self):
        assert Source("served 1,200 users").numbers_ok("Served 1200 users")

    def test_paraphrase_coverage_threshold(self):
        s = Source("Built real-time tracking APIs in Flask serving 50k requests/min.")
        assert s.coverage("Built real-time tracking APIs using Flask") >= 0.6
        assert s.coverage("Spearheaded blockchain strategy for enterprise clients") < 0.3


def test_hostile_fixture_after_sanitising_cannot_ground_the_injected_claim(fixture_text):
    from careerforge.ai.safety import sanitize_source

    cleaned = sanitize_source(fixture_text("cv_hostile.txt")).text
    injected = Profile(
        experience=[Experience(title="Engineer", company="Google", dates=DateRange(start="2014", end="2024"))]
    )
    out, report = ground_profile(injected, cleaned)
    assert out.exportable().experience == [] and report.of("entity")


def test_profile_text_flattens_content_but_not_flags():
    t = profile_text(faithful_standard())
    assert "Finlytics" in t and "confirmed" not in t and "extracted" not in t
