"""End-to-end extraction with a scripted provider: sanitise -> prompt -> parse -> map -> ground."""

import json

import pytest

from careerforge.ai.client import AIClient, Clock, RetryPolicy, Route
from careerforge.ai.errors import AIExhausted, AIOutputError, AIUnavailable
from careerforge.ai.extract import (
    EXTRACT_SYSTEM,
    NotEnoughText,
    extract_profile,
    profile_from_extraction,
)
from careerforge.ai.providers import Completion
from careerforge.readiness import check


class Scripted:
    name = "fake"

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []

    def complete(self, model, req):
        self.requests.append(req)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, Completion) else Completion(r if isinstance(r, str) else json.dumps(r), "fake", model)


def client_for(provider):
    clock = Clock(sleep=lambda s: None, monotonic=lambda: 0.0, uniform=lambda a, b: 0.0)
    return AIClient([Route(provider, "m")], RetryPolicy(), clock)


GOOD_STANDARD = {
    "name": "Priya Nair", "headline": "Senior Backend Engineer", "summary": "Backend engineer with 7 years building payment and logistics APIs in Python and Go.",
    "contact": {"email": "priya.nair@example.com", "phone": "+91 98765 43210", "location": "Bengaluru, India",
                "linkedin": "linkedin.com/in/priya-nair-demo", "github": "github.com/priya-demo", "website": ""},
    "skills": ["Python", "Go", "PostgreSQL", "Redis", "Kafka", "Docker", "Kubernetes", "AWS", "FastAPI", "Flask"],
    "languages": [],
    "experience": [
        {"title": "Senior Backend Engineer", "company": "Finlytics Pvt Ltd", "location": "", "start": "Mar 2021", "end": "Present",
         "bullets": ["Designed a event-driven settlement service handling 2M transactions/day using Kafka and PostgreSQL.",
                     "Cut p95 API latency from 480ms to 190ms by introducing Redis caching.",
                     "Mentored 4 engineers; led migration from monolith to 6 services on Kubernetes."]},
        {"title": "Software Engineer", "company": "ShipFast Logistics", "location": "", "start": "Jul 2018", "end": "Feb 2021",
         "bullets": ["Built real-time tracking APIs in Flask serving 50k requests/min.",
                     "Wrote CI/CD pipelines with GitHub Actions and Docker."]},
    ],
    "education": [{"degree": "B.Tech Computer Science", "institution": "NIT Calicut", "start": "2018", "end": "2018",
                   "grade": "CGPA 8.4", "details": []}],
    "projects": [],
    "certifications": [{"name": "AWS Certified Developer - Associate", "issuer": "", "date": "2022", "url": ""}],
}  # fmt: skip


def test_faithful_extraction_round_trip(fixture_text):
    p = Scripted(GOOD_STANDARD)
    res = extract_profile(client_for(p), fixture_text("cv_standard.txt"))
    assert res.grounding.findings == () and res.warnings == ()
    prof = res.profile
    assert (
        prof.name == "Priya Nair"
        and prof.experience[0].dates.current
        and prof.experience[1].dates.display() == "Jul 2018 – Feb 2021"
    )
    assert prof.skills[:3] == ["Python", "Go", "PostgreSQL"]
    # the gate is working on this fictional fixture: its only blocker is the sample example.com email
    assert [i.code for i in check(prof).blockers] == ["R007"]


def test_prompt_is_hardened_and_source_is_fenced(fixture_text):
    p = Scripted(GOOD_STANDARD)
    extract_profile(client_for(p), fixture_text("cv_standard.txt"))
    req = p.requests[0]
    assert req.temperature == 0.0 and req.json_mode
    assert "UNTRUSTED" in req.system and "Never invent" in req.system
    assert req.user.rstrip().endswith("</source>") and "<source>" in req.user
    # the instructions that made the old app invent content must be gone
    for banned in ("write one if not present", "Min 2 bullets", "STAR"):
        assert banned not in req.system and banned not in req.user and banned not in EXTRACT_SYSTEM


def test_injection_line_is_removed_before_the_model_sees_it_and_reported(fixture_text):
    p = Scripted({"name": "x", "experience": []})
    res = extract_profile(client_for(p), fixture_text("cv_hostile.txt"))
    assert "IGNORE ALL PREVIOUS" not in p.requests[0].user and "Google" not in p.requests[0].user
    assert len(res.removed_instruction_lines) == 1
    assert any("instructions to an AI" in w for w in res.warnings)


def test_model_that_obeys_the_injection_is_still_neutralised(fixture_text):
    """Defence in depth: even if the model is fooled, invented employer/score claims never reach an export."""
    fooled = {"name": "Candidate", "experience": [{"title": "Engineer", "company": "Google", "start": "2014", "end": "2024",
                                                   "bullets": ["Led search ranking for 10 years"]}],
              "old_ats_score": "100%"}  # fmt: skip
    res = extract_profile(client_for(Scripted(fooled)), fixture_text("cv_hostile.txt"))
    assert res.profile.exportable().experience == []
    assert res.profile.name == ""  # 'Candidate' is not in the document
    assert any("Grounding check" in w for w in res.warnings)


def test_invented_content_reported_not_silently_dropped(fixture_text):
    bad = json.loads(json.dumps(GOOD_STANDARD))
    bad["skills"] += ["Rust", "Terraform"]
    bad["experience"].append(
        {"title": "Staff Engineer", "company": "Stripe", "start": "2024", "end": "", "bullets": ["Built payments"]}
    )
    bad["experience"][0]["bullets"].append("Grew revenue by 340% across 12 markets.")
    res = extract_profile(client_for(Scripted(bad)), fixture_text("cv_standard.txt"))
    kinds = {f.kind for f in res.grounding.findings}
    assert {"skill", "entity", "bullet"} <= kinds
    assert [e.company for e in res.profile.exportable().experience] == ["Finlytics Pvt Ltd", "ShipFast Logistics"]
    assert "Rust" not in res.profile.skills and "340%" not in json.dumps(res.profile.model_dump())


def test_malformed_then_repaired(fixture_text):
    p = Scripted("sorry, here you go: {not json", GOOD_STANDARD)
    res = extract_profile(client_for(p), fixture_text("cv_standard.txt"))
    assert res.profile.name == "Priya Nair" and "rejected" in p.requests[1].user


def test_not_a_cv_object_triggers_repair_then_loud_failure(fixture_text):
    p = Scripted({"hello": "world"}, {"still": "wrong"})
    with pytest.raises(AIOutputError):
        extract_profile(client_for(p), fixture_text("cv_standard.txt"))


def test_truncated_output_retried_with_more_tokens(fixture_text):
    cut = Completion(json.dumps(GOOD_STANDARD)[:300], "fake", "m", truncated=True)
    p = Scripted(cut, GOOD_STANDARD)
    res = extract_profile(client_for(p), fixture_text("cv_standard.txt"), max_tokens=1000)
    assert res.profile.name == "Priya Nair" and p.requests[1].max_tokens == 2000


def test_provider_outage_is_loud(fixture_text):
    p = Scripted(*[AIUnavailable("down")] * 3)
    with pytest.raises(AIExhausted):
        extract_profile(client_for(p), fixture_text("cv_standard.txt"))


@pytest.mark.parametrize("text", ["", "   ", "Hi", "x" * 10])
def test_too_little_text_is_rejected_without_calling_the_model(text):
    p = Scripted()
    with pytest.raises(NotEnoughText):
        extract_profile(client_for(p), text)
    assert p.requests == []


def test_long_documents_are_clipped_visibly(fixture_text):
    long_doc = (
        fixture_text("cv_standard.txt") + "\n" + "\n".join(f"Filler line number {i} about nothing" for i in range(2000))
    )
    p = Scripted(GOOD_STANDARD)
    res = extract_profile(client_for(p), long_doc, max_chars=3000)
    assert res.clipped and any("only the first" in w for w in res.warnings) and len(p.requests[0].user) < 4500


def test_sparse_cv_stays_sparse_and_is_not_ready(fixture_text):
    sparse = {"name": "Maria Gonzalez", "headline": "Marketing", "contact": {"email": "maria.g@example.com"},
              "experience": [], "skills": []}  # fmt: skip
    res = extract_profile(
        client_for(Scripted(sparse)), fixture_text("cv_sparse.txt") + " padding text to pass the minimum length"
    )
    assert res.profile.experience == [] and not check(res.profile).ready


class TestTolerantMapping:
    def test_wrong_types_do_not_crash(self):
        p, w = profile_from_extraction({"name": ["x"], "skills": "Python, Go\nRust", "experience": [{"title": 5, "bullets": "one\n• two"}, "junk", None],
                                        "contact": "not a dict", "education": {"a": 1}})  # fmt: skip
        assert p.skills == ["Python, Go", "Rust"] or "Rust" in p.skills
        assert p.experience[0].bullets == ["one", "two"] and p.name == ""

    def test_bad_fields_dropped_with_warning_rest_kept(self):
        p, w = profile_from_extraction(
            {"name": "A", "contact": {"email": "nope", "phone": "+91 98765 43210", "github": "javascript:alert(1)"}}
        )
        assert p.contact.email == "" and p.contact.github == "" and p.contact.phone == "+91 98765 43210"
        assert any("contact.email" in x for x in w) and any("contact.github" in x for x in w)

    def test_overlong_field_dropped_not_truncated(self):
        p, w = profile_from_extraction(
            {"name": "A", "experience": [{"title": "T" * 500, "company": "Acme", "bullets": ["ok"]}]}
        )
        assert p.experience[0].title == "" and p.experience[0].company == "Acme" and any("title" in x for x in w)

    def test_unparseable_dates_dropped_with_warning(self):
        p, w = profile_from_extraction(
            {"name": "A", "experience": [{"title": "T", "start": "back then", "end": "Present"}]}
        )
        assert p.experience[0].dates.is_empty() and any("dates" in x for x in w)

    def test_end_before_start_is_a_warning_not_a_crash(self):
        p, w = profile_from_extraction({"name": "A", "experience": [{"title": "T", "start": "2022", "end": "2020"}]})
        assert p.experience[0].dates.is_empty() and w

    def test_flat_contact_fields_accepted(self):
        p, _ = profile_from_extraction({"name": "A", "email": "a@b.co"})
        assert p.contact.email == "a@b.co"

    @pytest.mark.parametrize("bad", [{}, {"hello": 1}, [], "x", None])
    def test_not_a_cv_raises_value_error(self, bad):
        with pytest.raises(ValueError):
            profile_from_extraction(bad)

    def test_empty_items_are_skipped(self):
        p, _ = profile_from_extraction(
            {"name": "A", "experience": [{"title": "", "company": ""}], "projects": [{"name": ""}]}
        )
        assert p.experience == [] and p.projects == []
