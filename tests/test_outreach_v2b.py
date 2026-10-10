"""Outreach: exact limits, caps and scoring (every number here is pinned so a changed constant fails a test)."""

from dataclasses import FrozenInstanceError
from datetime import date

import pytest
from test_grounding import faithful_standard

from careerforge import outreach as O
from careerforge.ats.report import analyze
from careerforge.models import DateRange, Experience, Profile
from careerforge.outreach import (
    Email,
    EmailCheck,
    Moment,
    attachment_name,
    best_achievement,
    build_emails,
    build_moment_emails,
    linkedin_boolean,
    linkedin_people_search,
    lint_email,
)

TODAY = date(2026, 10, 10)
P = faithful_standard()
SIGNED = "\n\nThanks,\nA B a@b.co"


def check(mail, kind, key):
    return {c.key: c for c in lint_email(mail, kind)}[key]


class TestPinnedLimits:
    def test_the_documented_numbers(self):
        assert O.SUBJECT_MAX == 60 and O.NOTE_LIMIT == 200
        assert O.BODY_WORDS_MAX == {"cold_email": 150, "follow_up_1": 100, "follow_up_2": 80, "referral_request": 150}
        assert O.DEFAULT_BODY_WORDS_MAX == 150

    @pytest.mark.parametrize(
        "kind,limit",
        [("cold_email", 150), ("follow_up_1", 100), ("follow_up_2", 80), ("referral_request", 150), ("decline", 150)],
    )
    def test_body_boundaries(self, kind, limit):
        def length(n):
            return check(Email("Hi", " ".join(["w"] * n)), kind, "length")

        assert length(limit).passed and not length(limit + 1).passed

    @pytest.mark.parametrize("n,ok", [(1, True), (60, True), (61, False)])
    def test_subject_boundaries(self, n, ok):
        assert check(Email("s" * n, "Hi" + SIGNED), "cold_email", "subject").passed is ok

    def test_up_to_two_request_phrases_pass_and_three_fail(self):
        two = Email("Hi", "Could you refer me. Please send news.")
        three = Email("Hi", "Could you refer me. Please send news. Can you reply.")
        assert check(two, "cold_email", "one_ask").passed and not check(three, "cold_email", "one_ask").passed
        assert "3 request-like" in check(three, "cold_email", "one_ask").detail

    def test_question_marks_count_as_requests_too(self):
        assert not check(Email("Hi", "Ready? Sure? Now?"), "cold_email", "one_ask").passed

    def test_every_request_phrase_is_recognised(self):
        for phrase in ("would you", "could you", "can you", "please let", "please send", "please share",
                       "please confirm", "I'd welcome", "I would value", "I'd appreciate", "would be glad", "would love"):  # fmt: skip
            assert O._ASK.search(phrase), phrase

    def test_a_signature_needs_the_contact_in_the_last_block(self):
        assert check(Email("Hi", "Hello\n\nBody\n\nThanks,\nA B\na@b.co"), "cold_email", "signature").passed
        assert not check(Email("Hi", "Contact me at a@b.co\n\nThanks,\nA B"), "cold_email", "signature").passed

    def test_results_are_immutable(self):
        with pytest.raises(FrozenInstanceError):
            lint_email(Email("a", "b"))[0].passed = False
        with pytest.raises(FrozenInstanceError):
            Email("a", "b").subject = "c"
        with pytest.raises(FrozenInstanceError):
            Moment().when = "x"
        assert EmailCheck("k", "l", True).detail == ""


class TestCaps:
    def test_company_and_role_are_cut_to_80_and_100_characters(self):
        for build in (
            lambda c, r: build_emails(P, c, r, today=TODAY)["cold_email"].body,
            lambda c, r: build_moment_emails(P, c, r, Moment())["decline"].body,
        ):
            body = build("C" * 120, "R" * 150)
            assert "C" * 80 in body and "C" * 81 not in body
            assert "R" * 100 in body and "R" * 101 not in body

    def test_search_terms_are_cut_to_80_and_60_characters(self):
        assert linkedin_boolean("z" * 300).count("z") == 80
        assert linkedin_boolean("acme", keywords="z" * 300).count("z") == 60
        (_, url), *_ = linkedin_people_search("z" * 300)
        assert url.count("z") == 80

    def test_attachment_stems_are_cut_to_50_characters(self):
        assert attachment_name(Profile(name="A" * 120)) == "A" * 50 + "_CV.pdf"

    def test_long_names_cannot_make_a_subject_longer_than_the_limit(self):
        mails = build_emails(Profile(name="N" * 120, contact=P.contact), "C" * 80, "R" * 100, today=TODAY)
        assert all(len(m.subject) <= 60 for m in mails.values())
        assert len(mails["linkedin_note"].body) <= O.NOTE_LIMIT

    def test_the_connection_note_is_cut_at_the_limit_not_beyond(self):
        long_title = Profile(name="Priya Nair", headline="H" * 200, contact=P.contact)
        note = build_emails(long_title, "Northwind", "R" * 100, today=TODAY)["linkedin_note"].body
        assert len(note) == O.NOTE_LIMIT
        assert len(build_moment_emails(long_title, "Northwind", "R" * 100)["linkedin_accepted"].body) <= O.NOTE_LIMIT


class TestBestAchievement:
    @staticmethod
    def profile(*bullets):
        return Profile(name="A B", experience=[Experience(title="Dev", company="Acme", bullets=list(bullets))])

    def test_a_number_and_a_verb_beat_either_alone(self):
        p = self.profile("Built tools carefully", "The team grew 3x", "Cut latency by 40%")
        assert best_achievement(p) == "Cut latency by 40%"

    def test_a_verb_alone_is_not_enough_but_a_number_alone_is(self):
        assert best_achievement(self.profile("Built tools carefully")) == ""
        assert best_achievement(self.profile("The team grew 3x")) == "The team grew 3x"

    def test_terms_from_the_posting_break_ties(self):
        p = self.profile("Cut costs by 40%", "Cut Kafka lag by 40%")
        report = analyze(p, "Dev\nRequirements: Kafka", today=TODAY)
        assert best_achievement(p, report) == "Cut Kafka lag by 40%"
        assert best_achievement(p) == "Cut costs by 40%"  # without a posting the first best one wins

    def test_only_the_first_sentence_is_used(self):
        assert best_achievement(self.profile("Cut costs by 40%. Then did other things.")) == "Cut costs by 40%"

    @pytest.mark.parametrize("length,truncated", [(159, False), (160, False), (161, True), (400, True)])
    def test_long_sentences_are_cut_at_160_characters(self, length, truncated):
        sentence = "Cut " + "x" * (length - 4)
        out = O._first_sentence(sentence)
        assert len(out) <= 160 and out.endswith("…") is truncated and (out == sentence) is (not truncated)


class TestDraftsFromTheCv:
    def test_at_most_four_skills_are_named(self):
        profile = Profile(name="A B", contact=P.contact, skills=["A1", "B2", "C3", "D4", "E5"])
        body = build_emails(profile, "Acme", "Dev", today=TODAY)["cold_email"].body
        assert "A1, B2, C3, D4" in body and "E5" not in body

    def test_skills_that_the_posting_asks_for_and_the_cv_applies_come_first(self):
        report = analyze(P, "Dev\nRequirements: Kafka, Redis, Docker, Kubernetes, PostgreSQL", today=TODAY)
        line = O._skills_line(P, report)
        assert len(line.split(", ")) <= 4 and "Kafka" in line

    @pytest.mark.parametrize(
        "start,end,words",
        [("2026-07", "2026-10", None), ("2025-10", "2026-10", "with 1 years"), ("2019-04", "2026-10", "with 8 years")],
    )
    def test_years_are_rounded_from_the_cv_dates_and_dropped_under_one(self, start, end, words):
        profile = Profile(
            name="A B", contact=P.contact, headline="Analyst",
            experience=[Experience(title="Analyst", company="Acme", dates=DateRange(start=start, end=end))],
        )  # fmt: skip
        body = build_emails(profile, "Acme", "Dev", today=TODAY)["cold_email"].body
        assert (words in body) if words else ("years of experience" not in body)

    def test_the_reply_subject_names_the_role_or_falls_back(self):
        assert build_moment_emails(P, "Acme", "Dev", Moment())["recruiter_reply"].subject == "Re: Dev - Priya Nair"
        assert (
            build_moment_emails(P, "Acme", "", Moment())["recruiter_reply"].subject == "Re: Your message - Priya Nair"
        )
