from datetime import date

from test_grounding import faithful_standard

from careerforge.analytics import keyword_heat, section_tips, skill_radar, timeline
from careerforge.ats.report import analyze
from careerforge.models import DateRange, Experience, Profile, Project

TODAY = date(2026, 10, 10)
JD = open(__file__.replace("test_analytics.py", "fixtures/jd_backend.txt")).read()
P = faithful_standard()


class TestRadar:
    def test_with_posting_counts_requirements_and_matches_per_category(self):
        axes = {a.category: a for a in skill_radar(P, JD)}
        assert axes["Languages"].required == 2 and axes["Languages"].matched == 2  # Python, Go
        assert axes["Databases"].required == 2 and axes["Databases"].matched == 2  # PostgreSQL, Redis
        assert (
            axes["Backend"].required >= 3 and axes["Backend"].matched < axes["Backend"].required
        )  # REST API, gRPC missing
        assert all(a.matched <= a.required for a in axes.values())

    def test_without_posting_only_listed_skills(self):
        axes = skill_radar(P, None)
        assert all(a.required == 0 and a.matched == 0 for a in axes) and sum(a.listed for a in axes) == len(P.skills)

    def test_unknown_skills_go_to_other_and_empty_profile_is_empty(self):
        assert [a.category for a in skill_radar(Profile(skills=["Underwater Basket Weaving"]), None)] == ["Other"]
        assert [a for a in skill_radar(Profile(), None)] == []

    def test_requirements_missing_entirely_still_appear_as_unmatched_axes(self):
        axes = {a.category: a for a in skill_radar(Profile(name="A"), JD)}
        assert axes["Languages"].required == 2 and axes["Languages"].matched == 0 and axes["Languages"].listed == 0


class TestTimeline:
    def test_spans_months_and_total(self):
        t = timeline(P, TODAY)
        assert [s.label for s in t.spans] == [
            "Software Engineer @ ShipFast Logistics",
            "Senior Backend Engineer @ Finlytics Pvt Ltd",
        ]
        assert t.spans[0].months == 32 and t.spans[1].end == "" and t.spans[1].months == 68 and t.total_months == 100
        assert t.gaps == ()

    def test_gaps_of_three_months_or_more_are_reported(self):
        p = Profile(experience=[
            Experience(title="A", company="X", dates=DateRange(start="2019-01", end="2019-12")),
            Experience(title="B", company="Y", dates=DateRange(start="2020-06", current=True)),
        ])  # fmt: skip
        assert timeline(p, TODAY).gaps == ("5 months between X and Y",)

    def test_adjacent_roles_have_no_gap_and_undated_roles_are_skipped(self):
        p = Profile(experience=[
            Experience(title="A", company="X", dates=DateRange(start="2019-01", end="2019-12")),
            Experience(title="B", company="Y", dates=DateRange(start="2020-01", end="2020-12")),
            Experience(title="C", company="Z"),
        ])  # fmt: skip
        t = timeline(p, TODAY)
        assert t.gaps == () and len(t.spans) == 2


class TestKeywordHeat:
    def test_counts_where_each_requirement_appears(self):
        rows = {r.term: r for r in keyword_heat(P, JD)}
        assert (rows["Kafka"].skills, rows["Kafka"].experience) == (1, 1)
        assert rows["Kubernetes"].experience == 1 and rows["Redis"].experience == 1
        assert (
            rows["Terraform"].skills,
            rows["Terraform"].experience,
            rows["Terraform"].summary,
            rows["Terraform"].projects,
        ) == (0, 0, 0, 0)
        assert rows["Terraform"].importance == "preferred" and rows["Python"].summary == 1

    def test_project_mentions_counted(self):
        p = Profile(projects=[Project(name="Tracker", bullets=["Built a Kafka consumer for audit events."])])
        assert {r.term: r for r in keyword_heat(p, "Dev\nRequirements: Kafka")}["Kafka"].projects == 1


class TestSectionTips:
    def test_includes_report_fixes_and_role_observations(self):
        thin = P.model_copy(
            update={
                "experience": [
                    P.experience[0].model_copy(update={"bullets": ["Cut latency 40% with Redis caching today."]}),
                    *P.experience[1:],
                ]
            }
        )
        tips = section_tips(thin, analyze(thin, JD, today=TODAY))
        msgs = [t.message for t in tips]
        assert any("add at least 2 bullets" in m and "Finlytics" in m for m in msgs)
        assert any("REST API" in m for m in msgs)
        assert [t.severity for t in tips] == sorted(
            [t.severity for t in tips], key={"high": 0, "medium": 1, "low": 2}.get
        )

    def test_long_bullets_and_long_summary_are_flagged_with_paths(self):
        long = "Built " + "very " * 50 + "large systems"
        p = P.model_copy(
            update={
                "summary": "x " * 320,
                "experience": [P.experience[0].model_copy(update={"bullets": [long, long]}), *P.experience[1:]],
            }
        )
        tips = {(t.section, t.message.split(":")[0]) for t in section_tips(p, analyze(p, None, today=TODAY))}
        assert ("experience[0].bullets[0]", "Finlytics Pvt Ltd") in tips and any(s == "summary" for s, _ in tips)

    def test_a_good_cv_has_few_tips(self):
        assert [t for t in section_tips(P, analyze(P, None, today=TODAY)) if t.severity == "high"] == []
