"""Outreach v2: more moments of a job search, an email lint, attachment names and Boolean people-search strings."""

import re
from datetime import date

import pytest
from test_grounding import faithful_standard

from careerforge.ai.grounding import profile_text
from careerforge.ats.report import analyze
from careerforge.models import Contact, Profile
from careerforge.outreach import (
    BODY_WORDS_MAX,
    SUBJECT_MAX,
    Email,
    Moment,
    attachment_name,
    build_emails,
    build_moment_emails,
    linkedin_boolean,
    lint_email,
)
from careerforge.writing.claims import unsupported_claims

TODAY = date(2026, 10, 10)
JD = open(__file__.replace("test_outreach_v2.py", "fixtures/jd_backend.txt")).read()
P = faithful_standard()
FULL = Moment(
    contact="Ms. Rao",
    how_known="We worked together on the payments team",
    when="Tuesday 14 October, 3 pm IST",
    availability="I can speak any weekday after 4 pm",
    deadline="Friday 17 October",
    notice="My notice period is 30 days",
    reason="I accepted another offer",
)
KINDS = {
    "referral_request", "recruiter_reply", "interview_confirmation", "offer_acknowledgement", "decline",
    "after_rejection", "linkedin_accepted",
}  # fmt: skip


def moments(moment=FULL, **kw):
    return build_moment_emails(P, "Northwind Payments", "Backend Engineer", moment, **kw)


class TestMoments:
    def test_every_moment_is_drafted(self):
        assert set(moments()) == KINDS

    def test_each_draft_uses_the_users_facts_and_nothing_else(self):
        m = moments()
        assert "payments team" in m["referral_request"].body and "Ms. Rao" in m["referral_request"].body
        assert "Tuesday 14 October, 3 pm IST" in m["interview_confirmation"].body
        assert "any weekday after 4 pm" in m["recruiter_reply"].body and "30 days" in m["recruiter_reply"].body
        assert "Friday 17 October" in m["offer_acknowledgement"].body
        assert "accepted another offer" in m["decline"].body

    def test_missing_details_are_left_out_without_leaving_gaps_or_placeholders(self):
        for mail in moments(Moment()).values():
            assert not re.search(r"\[|\]|\{|\}|None|\bon \.|\bby \.|  | \.", mail.body + mail.subject)
            assert "\n\n\n" not in mail.body
        assert "Hello," in moments(Moment())["referral_request"].body

    def test_nothing_is_invented_the_claims_checker_finds_no_new_facts(self):
        known = " ".join(f"{k} {v}" for k, v in FULL.__dict__.items()) + " Northwind Payments Rao"
        for key, mail in moments().items():
            issues = unsupported_claims(
                mail.body, profile_text=profile_text(P), years=8, posting_text=JD, extra_known=known
            )
            assert issues == [], (key, issues)

    def test_unconfirmed_ai_content_never_reaches_a_draft(self):
        ghost = P.model_copy(update={"summary": "x"})
        assert moments() == build_moment_emails(ghost, "Northwind Payments", "Backend Engineer", FULL)

    def test_subjects_respect_the_limit_and_the_linkedin_note_has_none(self):
        long = build_moment_emails(P, "C" * 80, "R" * 100, FULL)
        for key, mail in long.items():
            assert len(mail.subject) <= SUBJECT_MAX, key
        assert long["linkedin_accepted"].subject == "" and len(long["linkedin_accepted"].body) <= 300

    def test_without_a_role_the_wording_stays_grammatical(self):
        m = build_moment_emails(P, "Northwind Payments", "", FULL)
        assert "a role at Northwind Payments" in m["decline"].body and "the  role" not in m["decline"].body

    def test_hostile_input_is_cleaned_not_executed(self):
        m = build_moment_emails(P, "Co\x00\n<b>", "R", Moment(contact="<script>x</script>\x07"))
        assert all("\x00" not in x.body and "\x07" not in x.body for x in m.values())


class TestLint:
    def good(self):
        return build_emails(P, "Northwind Payments", "Backend Engineer", report=analyze(P, JD, today=TODAY))[
            "cold_email"
        ]

    def test_the_generated_cold_email_passes_its_own_lint(self):
        assert [c.label for c in lint_email(self.good()) if not c.passed] == []

    def test_every_generated_draft_passes_its_own_lint(self):
        mails = {**build_emails(P, "Northwind Payments", "Backend Engineer"), **moments()}
        for key, mail in mails.items():
            failed = [c.label for c in lint_email(mail, key) if not c.passed]
            assert failed == [], (key, failed)

    @pytest.mark.parametrize(
        "n,ok", [(SUBJECT_MAX - 1, True), (SUBJECT_MAX, True), (SUBJECT_MAX + 1, False), (0, False)]
    )
    def test_subject_boundary(self, n, ok):
        c = {x.key: x for x in lint_email(Email("s" * n, "Hello.\n\nBest\nA B a@b.co"))}["subject"]
        assert c.passed is ok

    @pytest.mark.parametrize("kind", sorted(BODY_WORDS_MAX))
    def test_body_length_boundary_is_per_kind(self, kind):
        limit = BODY_WORDS_MAX[kind]

        def length(n):
            return {x.key: x for x in lint_email(Email("Hi", " ".join(["word"] * n)), kind)}["length"]

        assert length(limit).passed and not length(limit + 1).passed

    def test_unknown_kinds_use_the_default_limit(self):
        c = {x.key: x for x in lint_email(Email("Hi", " ".join(["w"] * 151)), "something_else")}["length"]
        assert not c.passed

    def test_requests_are_counted_and_more_than_two_fail(self):
        many = Email("Hi", "Could you refer me? Would you call me? Can you reply? Please send news.")
        one = Email("Hi", "Would you be open to a call?")
        assert not {x.key: x for x in lint_email(many)}["one_ask"].passed
        assert {x.key: x for x in lint_email(one)}["one_ask"].passed

    def test_placeholders_and_a_missing_signature_are_flagged(self):
        c = {x.key: x for x in lint_email(Email("Hi [Name]", "Dear {x},\n\nThanks\nA B"))}
        assert not c["no_placeholders"].passed and not c["signature"].passed

    @pytest.mark.parametrize("sig,ok", [("A B\na@b.co", True), ("A B\n+91 98765 43210", True), ("A B", False)])
    def test_signature_needs_an_email_or_phone(self, sig, ok):
        c = {x.key: x for x in lint_email(Email("Hi", f"Hello,\n\nBody.\n\nThanks,\n{sig}"))}["signature"]
        assert c.passed is ok

    @pytest.mark.parametrize("kind", ["linkedin_note", "linkedin_accepted"])
    def test_linkedin_notes_have_no_subject_or_signature_checks(self, kind):
        keys = {x.key for x in lint_email(Email("", "Hello, I'm A B."), kind)}
        assert keys == {"length", "one_ask", "no_placeholders"}


class TestAttachmentName:
    @pytest.mark.parametrize(
        "name,kind,ext,expected",
        [
            ("Priya Nair", "CV", "pdf", "Priya_Nair_CV.pdf"),
            ("  Dr. Ana-María O'Neil  ", "Cover letter", "docx", "Dr_Ana_Mar_a_O_Neil_Cover_letter.docx"),
            ("李雷", "CV", "pdf", "CV.pdf"),
            ("", "CV", "pdf", "CV.pdf"),
            ("A/../B", "CV", "PDF", "A_B_CV.pdf"),
            ("A B", "!!!", "..", "A_B_CV.pdf"),
        ],
    )
    def test_names_are_safe_and_readable(self, name, kind, ext, expected):
        assert (
            attachment_name(Profile(name=name or "x", contact=Contact()).model_copy(update={"name": name}), kind, ext)
            == expected
        )

    def test_a_very_long_name_is_cut(self):
        assert len(attachment_name(Profile(name="A" * 120))) <= 60


class TestBoolean:
    def test_shape(self):
        s = linkedin_boolean("Northwind Payments")
        assert (
            s
            == '("Technical Recruiter" OR "Talent Acquisition" OR "Hiring Manager" OR "Engineering Manager") AND "Northwind Payments"'
        )

    def test_extra_keywords_and_hostile_quotes(self):
        s = linkedin_boolean('Acme "Corp"', ("Recruiter",), keywords='Pune" OR 1=1')
        assert s == '("Recruiter") AND "Acme Corp" AND "Pune OR 1=1"'
        assert s.count('"') % 2 == 0

    @pytest.mark.parametrize("company", ["", "   ", '""'])
    def test_blank_company_gives_nothing(self, company):
        assert linkedin_boolean(company) == ""

    def test_length_is_bounded(self):
        assert len(linkedin_boolean("c" * 500, keywords="k" * 500)) < 400
