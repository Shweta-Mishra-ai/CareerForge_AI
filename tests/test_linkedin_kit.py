"""CV -> LinkedIn text: only the user's words, within LinkedIn's field sizes."""

import re

from test_render_cv import experienced, fresher

from careerforge.ai.grounding import profile_text
from careerforge.linkedin_kit import (
    ABOUT_LIMIT,
    DESCRIPTION_LIMIT,
    HEADLINE_LIMIT,
    SKILLS_LIMIT,
    build_linkedin_kit,
)
from careerforge.models import DateRange, Experience, Profile

WORD = re.compile(r"[A-Za-z0-9+#.]{3,}")


def words(text: str) -> set[str]:
    return {w.lower().rstrip(".") for w in WORD.findall(text)}


class TestContent:
    def test_headline_is_the_headline_plus_top_skills(self):
        kit = build_linkedin_kit(experienced())
        assert kit.headline == "Senior Backend Engineer | Python | Go | PostgreSQL"
        assert kit.top_skills == ("Python", "Go", "PostgreSQL")

    def test_about_is_summary_skills_and_the_users_own_measurable_bullets(self):
        about = build_linkedin_kit(experienced()).about
        assert about.startswith("Backend engineer with 7 years building payment and logistics APIs in Python and Go.")
        assert (
            "What I work with: Python, Go, PostgreSQL, Redis, Kafka, Docker, Kubernetes, AWS, FastAPI, Flask." in about
        )
        highlights = about.split("Highlights:\n")[1].splitlines()
        assert len(highlights) == 3 and all(h.startswith("• ") and re.search(r"\d", h) for h in highlights)
        all_bullets = {b for e in experienced().experience for b in e.bullets}
        assert all(h[2:] in all_bullets for h in highlights)  # verbatim, never reworded

    def test_experience_descriptions_are_bullets_in_order_with_the_right_metadata(self):
        kit = build_linkedin_kit(experienced())
        first = kit.experience[0]
        assert (first.title, first.company, first.dates) == (
            "Senior Backend Engineer",
            "Finlytics Pvt Ltd",
            "Mar 2021 – Present",
        )
        assert (
            first.description.splitlines()[1]
            == "• Cut p95 API latency from 480ms to 190ms by introducing Redis caching."
        )

    def test_education_projects_and_certifications_map_over(self):
        p = fresher()
        kit = build_linkedin_kit(p)
        assert kit.education[0].school == "Demo Institute of Technology" and kit.education[0].degree.startswith(
            "B.Tech"
        )
        assert kit.projects[0].name == "Expense Tracker" and kit.projects[0].skills == ("React", "Node.js", "MongoDB")
        assert kit.projects[0].url == "https://github.com/arjun-demo/expense-tracker"
        assert [c.name for c in build_linkedin_kit(experienced()).certifications] == [
            "AWS Certified Developer - Associate"
        ]

    def test_nothing_is_invented_every_word_comes_from_the_profile(self):
        for p in (experienced(), fresher()):
            source = words(profile_text(p))
            kit = build_linkedin_kit(p)
            produced = " ".join([kit.headline, kit.about, *[e.description for e in kit.experience], *kit.skills])
            # the only words we add are the fixed labels
            added = words(produced) - source - {"what", "work", "with", "highlights"}
            assert added == set(), added


class TestLimits:
    def test_headline_never_exceeds_the_limit_and_never_cuts_a_skill_in_half(self):
        p = experienced().model_copy(
            update={
                "headline": "Senior Backend and Platform Engineering Lead " * 4,
                "skills": ["Python", "Go", "Kafka"],
            }
        )
        kit = build_linkedin_kit(p)
        assert len(kit.headline) <= HEADLINE_LIMIT and kit.headline.startswith("Senior Backend")
        assert not kit.headline.endswith(" |") and "Kafka" not in kit.headline[: len("Senior")]

    def test_about_drops_optional_parts_before_cutting_the_summary(self):
        p = experienced().model_copy(update={"summary": "Backend engineer who ships. " * 90})  # 2,520 characters
        kit = build_linkedin_kit(p)
        assert len(kit.about) <= ABOUT_LIMIT and kit.about.startswith("Backend engineer who ships.")
        assert "Highlights" not in kit.about and any("shortened" in n for n in kit.notes)

    def test_a_summary_longer_than_linkedin_allows_is_cut_at_a_word_with_a_note(self):
        p = experienced().model_copy(update={"summary": ("word " * 700).strip()})  # models cap summaries at 1,500
        # model_copy skips validation, which is how a too-long summary reaches the safety net here
        kit = build_linkedin_kit(p)
        assert (
            len(kit.about) <= ABOUT_LIMIT
            and kit.about.endswith("…")
            and any("longer than LinkedIn" in n for n in kit.notes)
        )

    def test_long_experience_descriptions_drop_whole_bullets_not_halves(self):
        bullets = [f"Delivered result number {i} with a long explanation " + "x" * 150 for i in range(25)]
        p = Profile(
            name="A B",
            experience=[Experience(title="Dev", company="Co", dates=DateRange(start="2020"), bullets=bullets)],
        )
        d = build_linkedin_kit(p).experience[0].description
        assert len(d) <= DESCRIPTION_LIMIT and all(
            line.startswith("• Delivered") and line.endswith("x" * 150) for line in d.splitlines()
        )
        assert any("left out to fit" in n for n in build_linkedin_kit(p).notes)

    def test_skills_are_capped_at_the_linkedin_maximum(self):
        p = experienced().model_copy(update={"skills": [f"Skill{i}" for i in range(80)]})
        kit = build_linkedin_kit(p)
        assert len(kit.skills) == SKILLS_LIMIT and any("accepts 50 skills" in n for n in kit.notes)


class TestHonesty:
    def test_unconfirmed_ai_suggestions_are_left_out(self):
        ghost = Experience(title="Wizard", company="FakeCo", origin="suggested", bullets=["Conjured revenue 10x"])
        kit = build_linkedin_kit(experienced().model_copy(update={"experience": [ghost, *experienced().experience]}))
        assert "FakeCo" not in repr(kit) and "Conjured" not in repr(kit)

    def test_a_sparse_profile_gets_notes_not_filler(self):
        kit = build_linkedin_kit(Profile(name="Sam Rivera", skills=["Python"]))
        assert kit.headline == "" and kit.about == "What I work with: Python."
        assert any("no headline" in n for n in kit.notes) and any("no summary" in n for n in kit.notes)

    def test_an_empty_profile_yields_empty_text(self):
        kit = build_linkedin_kit(Profile())
        assert (kit.headline, kit.about, kit.experience, kit.skills) == ("", "", (), ())

    def test_the_input_profile_is_not_modified(self):
        p = experienced()
        before = p.model_dump()
        build_linkedin_kit(p)
        assert p.model_dump() == before
