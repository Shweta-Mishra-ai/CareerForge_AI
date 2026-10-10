import re
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from test_grounding import faithful_standard

from careerforge.ats.report import analyze
from careerforge.models import Contact, Experience, Profile
from careerforge.outreach import NOTE_LIMIT, best_achievement, build_emails, linkedin_people_search
from careerforge.roadmap import build_roadmap

TODAY = date(2026, 10, 10)
JD = open(__file__.replace("test_outreach_roadmap.py", "fixtures/jd_backend.txt")).read()
P = faithful_standard()
REPORT = analyze(P, JD, today=TODAY)


class TestSearchLinks:
    def test_urls_are_encoded_and_point_to_linkedin(self):
        links = linkedin_people_search("AT&T Labs #1")
        assert len(links) == 4
        for label, url in links:
            q = urlparse(url)
            assert q.netloc == "www.linkedin.com" and q.path == "/search/results/people/"
            assert parse_qs(q.query)["keywords"] == [f"{label} AT&T Labs #1"]  # round-trips: nothing got injected
            assert "&T Labs" not in url.split("keywords=")[1].split("&origin")[0]

    @pytest.mark.parametrize("company", ["", "   ", None])
    def test_blank_company_gives_nothing(self, company):
        assert linkedin_people_search(company) == []

    def test_hostile_company_cannot_add_parameters_or_break_out(self):
        (_, url), *_ = linkedin_people_search('x&redirect=https://evil.com"><script>')
        assert parse_qs(urlparse(url).query).keys() == {"keywords", "origin"} and "<" not in url and '"' not in url

    def test_no_guessed_email_addresses_anywhere(self):
        emails = build_emails(P, "Northwind", "Engineer", today=TODAY)
        blob = " ".join(e.body for e in emails.values())
        assert not re.search(r"\b(?:hr|careers|jobs|talent|recruiting|hiring)@", blob)


class TestEmails:
    E = build_emails(P, "Northwind Payments", "Senior Backend Engineer", report=REPORT, recipient="Ms. Rao",
                     hook="I admire Northwind's focus on reliable settlement.", interview_topic="your event-driven design", today=TODAY)  # fmt: skip

    def test_all_five_drafts_exist_and_have_no_placeholders(self):
        assert set(self.E) == {"cold_email", "follow_up_1", "follow_up_2", "thank_you", "linkedin_note"}
        for key, mail in self.E.items():
            assert not re.search(r"\[[^\]]*\]|\{[^}]*\}|<[^>]+>|TODO|XXX", mail.subject + mail.body), key
            assert len(mail.subject) <= 70

    def test_uses_only_real_cv_facts(self):
        body = self.E["cold_email"].body
        assert "Priya Nair" in body and "Northwind Payments" in body and "priya.nair@example.com" in body
        assert "For example, I designed a event-driven settlement service" in body  # the user's own words, verbatim
        assert "8 years" in body  # computed from dates, not invented
        from careerforge.ai.grounding import profile_text
        from careerforge.writing.claims import unsupported_claims

        assert (
            unsupported_claims(
                body, profile_text=profile_text(P), years=8, posting_text=JD, extra_known="Northwind Payments Rao"
            )
            == []
        )

    def test_optional_details_vanish_cleanly_when_not_given(self):
        bare = build_emails(P, "Northwind", "", today=TODAY)
        text = " ".join(e.body for e in bare.values())
        assert "None" not in text and "discussion of" not in text and "\n\n\n" not in text
        assert bare["cold_email"].body.startswith("Hello,") and "opportunities at Northwind" in bare["cold_email"].body

    def test_interview_topic_appears_only_in_thank_you(self):
        assert "your event-driven design" in self.E["thank_you"].body
        assert not any("your event-driven design" in e.body for k, e in self.E.items() if k != "thank_you")

    def test_linkedin_note_fits_the_limit_even_with_a_long_company(self):
        note = build_emails(P, "N" * 80, "R" * 100, today=TODAY)["linkedin_note"].body
        assert len(note) <= NOTE_LIMIT

    def test_linkedin_note_is_really_cut_when_the_text_would_overflow(self):
        long_head = P.model_copy(update={"headline": "Senior Backend and Platform Engineering Lead " * 4})  # ~180 chars
        raw_length = len(
            f"Hello, I'm {P.name}, a {long_head.headline}. I'm exploring the {'R' * 100} role at {'N' * 80} and would value connecting."
        )
        assert raw_length > NOTE_LIMIT  # guard: this input genuinely overflows
        assert len(build_emails(long_head, "N" * 80, "R" * 100, today=TODAY)["linkedin_note"].body) == NOTE_LIMIT

    def test_unconfirmed_ai_items_are_not_used(self):
        p = P.model_copy(
            update={
                "experience": [
                    Experience(
                        title="Wizard", company="FakeCo", origin="suggested", bullets=["Cut costs by 99% at FakeCo"]
                    ),
                    *P.experience,
                ]
            }
        )
        assert "FakeCo" not in " ".join(e.body for e in build_emails(p, "X", "Y", today=TODAY).values())

    def test_profile_without_achievements_or_skills_still_produces_clean_drafts(self):
        p = Profile(name="Maria Gonzalez", contact=Contact(email="maria.g@gmail.com"))
        mail = build_emails(p, "Acme", "Marketing Manager", today=TODAY)["cold_email"].body
        assert (
            "I work mainly with" not in mail
            and "For example" not in mail
            and "Maria Gonzalez" in mail
            and "\n\n\n" not in mail
        )


class TestBestAchievement:
    def test_prefers_measurable_relevant_bullets_and_returns_one_sentence(self):
        got = best_achievement(P, REPORT)
        assert re.search(r"\d", got) and got in " ".join(b for e in P.experience for b in e.bullets)

    def test_none_when_nothing_measurable(self):
        p = Profile(name="A", experience=[Experience(title="T", bullets=["Worked on things for the team"])])
        assert best_achievement(p) == ""


class TestRoadmap:
    ITEMS = build_roadmap(REPORT, P)

    def test_covers_missing_required_skills_in_priority_order(self):
        skills = [i.skill for i in self.ITEMS]
        assert {"REST API", "Terraform", "gRPC"} <= set(skills)
        assert skills.index("REST API") < skills.index("Terraform")  # required before nice-to-have
        assert all(i.priority in ("required", "unspecified", "preferred") for i in self.ITEMS)
        assert [i.priority for i in self.ITEMS] == sorted(
            [i.priority for i in self.ITEMS], key={"required": 0, "unspecified": 1, "preferred": 2}.get
        )

    def test_no_urls_are_invented(self):
        text = " ".join(" ".join(i.steps) + i.project for i in self.ITEMS)
        assert "http" not in text and "www." not in text

    def test_steps_end_with_the_honesty_rule(self):
        for item in self.ITEMS:
            assert "Only after you have really used" in item.steps[-1]

    def test_effort_is_a_sane_range_and_shorter_when_you_have_a_related_skill(self):
        for item in self.ITEMS:
            assert 1 <= item.weeks[0] <= item.weeks[1] <= 16
        no_python = Profile(name="A", skills=["Excel"])
        with_python = Profile(name="A", skills=["Python"])
        rep = analyze(no_python, "Dev\nRequirements: Django", today=TODAY)
        slow = build_roadmap(rep, no_python)[0]
        fast = build_roadmap(analyze(with_python, "Dev\nRequirements: Django", today=TODAY), with_python)[0]
        assert fast.builds_on == "Python" and fast.weeks[1] < slow.weeks[1]

    def test_nothing_missing_means_empty_roadmap(self):
        assert build_roadmap(analyze(P, "Dev\nRequirements: Python", today=TODAY), P) == []

    def test_limit(self):
        assert len(build_roadmap(REPORT, P, limit=1)) == 1
