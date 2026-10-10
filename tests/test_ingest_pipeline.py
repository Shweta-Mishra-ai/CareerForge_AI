"""ingest_upload() routing + review helpers. The AI is a scripted fake; documents are real generated files."""

import io
import json

import pytest
from docx import Document
from helpers import pdf_from_html, zip_bytes

from careerforge.ai.client import AIClient, Clock, RetryPolicy, Route
from careerforge.ai.errors import AIExhausted
from careerforge.ai.providers import Completion
from careerforge.ingest.errors import EmptyDocument, UnsupportedFormat
from careerforge.ingest.pipeline import heuristic_profile, ingest_upload, looks_like_linkedin_pdf, with_links
from careerforge.models import Experience, Profile, Project
from careerforge.review import confirm, confirm_all, discard

CV_HTML = """<div style="display:flex"><div style="width:30%"><h3>Contact</h3><p>priya@example.com<br>Bengaluru, India<br>
<a href="https://www.linkedin.com/in/priya-nair-demo">LinkedIn</a></p><h3>Skills</h3><p>Python, Go, Kafka</p></div>
<div style="width:70%"><h1>Priya Nair</h1><h3>Experience</h3><p><b>Backend Engineer, Finlytics</b> Mar 2021 - Present</p>
<ul><li>Cut API latency from 480ms to 190ms using Redis.</li></ul></div></div>"""

GOOD = {
    "name": "Priya Nair",
    "contact": {"email": "priya@example.com", "location": "Bengaluru, India", "linkedin": "https://www.linkedin.com/in/priya-nair-demo"},
    "skills": ["Python", "Go", "Kafka"],
    "experience": [{"title": "Backend Engineer", "company": "Finlytics", "start": "Mar 2021", "end": "Present",
                    "bullets": ["Cut API latency from 480ms to 190ms using Redis."]}],
}  # fmt: skip


class Fake:
    name = "fake"

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []

    def complete(self, model, req):
        self.requests.append(req)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return Completion(r if isinstance(r, str) else json.dumps(r), "fake", model)


def client(provider):
    return AIClient(
        [Route(provider, "m")],
        RetryPolicy(),
        Clock(sleep=lambda s: None, monotonic=lambda: 0.0, uniform=lambda a, b: 0.0),
    )


def docx_bytes(text):
    d = Document()
    for line in text.split("\n"):
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


class TestRouting:
    def test_pdf_goes_through_ai_and_grounding_and_hidden_links_are_usable(self):
        fake = Fake(GOOD)
        res = ingest_upload("cv.pdf", pdf_from_html(CV_HTML), client(fake))
        assert res.source == "pdf" and res.profile.name == "Priya Nair"
        sent = fake.requests[0].user
        assert "Links found in the document" in sent and "linkedin.com/in/priya-nair-demo" in sent
        assert res.profile.contact.linkedin.endswith("/in/priya-nair-demo")  # grounded thanks to the link annotation
        assert res.grounding is not None and res.grounding.findings == ()

    def test_pdf_columns_reach_the_model_in_reading_order(self):
        fake = Fake(GOOD)
        ingest_upload("cv.pdf", pdf_from_html(CV_HTML), client(fake))
        src = fake.requests[0].user
        assert src.index("Skills") < src.index("Priya Nair") < src.index("Finlytics")

    def test_docx_and_txt(self):
        text = "Priya Nair\npriya@example.com\nBackend Engineer at Finlytics, March 2021 to present. Python and Go."
        for name, data in (("cv.docx", docx_bytes(text)), ("cv.txt", text.encode())):
            res = ingest_upload(
                name, data, client(Fake({"name": "Priya Nair", "contact": {"email": "priya@example.com"}}))
            )
            assert res.profile.name == "Priya Nair" and res.source in ("docx", "txt")

    def test_profile_json_roundtrip_needs_no_ai(self):
        p = Profile(name="A B", experience=[Experience(title="Dev", company="Acme")])
        res = ingest_upload("me.json", p.to_json().encode(), None)
        assert res.profile == p and res.source == "profile_json"

    def test_linkedin_export_needs_no_ai(self):
        z = zip_bytes(
            {"Profile.csv": b"First Name,Last Name,Headline\nPriya,Nair,Engineer\n", "Skills.csv": b"Name\nPython\n"}
        )
        res = ingest_upload("export.zip", z, None)
        assert res.source == "linkedin_export" and res.profile.name == "Priya Nair" and res.profile.skills == ["Python"]

    def test_linkedin_pdf_gets_the_layout_hint_other_pdfs_do_not(self):
        li = pdf_from_html(
            "<h3>Contact</h3><p>www.linkedin.com/in/priya-nair-demo (LinkedIn)</p><h3>Top Skills</h3><p>Python</p>"
            "<h3>Experience</h3><p>Finlytics<br>Backend Engineer<br>March 2021 - Present</p>"
        )
        f1, f2 = Fake(GOOD), Fake(GOOD)
        ingest_upload("Profile.pdf", li, client(f1))
        ingest_upload("cv.pdf", pdf_from_html(CV_HTML), client(f2))
        assert (
            "LinkedIn profile exported" in f1.requests[0].user
            and "LinkedIn profile exported" not in f2.requests[0].user
        )

    def test_hostile_document_is_neutralised_end_to_end(self, fixture_text):
        fooled = {
            "name": "Candidate",
            "experience": [{"title": "Engineer", "company": "Google", "start": "2014", "end": "2024"}],
        }
        res = ingest_upload("cv.txt", fixture_text("cv_hostile.txt").encode(), client(Fake(fooled)))
        assert res.removed_instruction_lines and res.profile.exportable().experience == []

    def test_bad_inputs_raise_user_facing_errors(self):
        with pytest.raises(UnsupportedFormat):
            ingest_upload("cv.exe", b"MZ" + b"\x00" * 100, None)
        with pytest.raises(EmptyDocument):
            ingest_upload("cv.txt", b"hi", None)

    def test_ai_outage_is_loud_not_silently_replaced(self):
        from careerforge.ai.errors import AIUnavailable

        with pytest.raises(AIExhausted):
            ingest_upload(
                "cv.txt", b"x" * 100 + b" Python developer for many years", client(Fake(*[AIUnavailable("down")] * 3))
            )


class TestHeuristicFallback:
    def test_without_section_headings_only_contact_and_skills_are_read_nothing_guessed(self):
        text = "Priya Nair\nSenior Engineer at Finlytics\nEmail: priya@example.com | +91 98765 43210\nlinkedin.com/in/priya-nair-demo github.com/priya-demo/repo\nPython, Go, 2018 - 2021"
        p, warnings = heuristic_profile(text)
        assert p.experience == [] and p.education == []  # no headings: no job is made up from a stray line
        assert (p.contact.email, p.contact.phone) == ("priya@example.com", "+91 98765 43210")
        assert (
            p.contact.linkedin.endswith("/in/priya-nair-demo") and p.contact.github == "https://github.com/priya-demo"
        )
        assert {"Python", "Go"} <= set(p.skills)
        assert any("No standard section headings" in w for w in warnings) and "basic" in warnings[0]

    def test_year_ranges_are_not_phone_numbers(self):
        p, _ = heuristic_profile("Worked 2018 - 2021 and 2021 - 2024 at Acme Corp")
        assert p.contact.phone == ""

    def test_no_ai_client_uses_it_labels_the_source_and_grounds_the_result(self):
        res = ingest_upload(
            "cv.txt", b"Contact priya@example.com. Experienced in Python and Kubernetes for years.", None
        )
        assert res.source == "heuristic" and res.profile.contact.email == "priya@example.com"
        assert "basic" in res.warnings[0] and res.grounding is not None and res.grounding.findings == ()


def test_helpers():
    assert with_links("body", ()) == "body" and "- https://a.co" in with_links("body", ("https://a.co",))
    assert not looks_like_linkedin_pdf("just a cv with linkedin.com/in/x")


class TestReview:
    def draft(self):
        return Profile(name="A", experience=[Experience(title="Real"), Experience(title="Maybe", origin="suggested")],
                       projects=[Project(name="P", origin="suggested")])  # fmt: skip

    def test_confirm_makes_an_item_exportable_and_keeps_provenance(self):
        out = confirm(self.draft(), "experience", 1)
        assert [e.title for e in out.exportable().experience] == ["Real", "Maybe"] and out.experience[
            1
        ].origin == "suggested"

    def test_discard_removes_it(self):
        assert [e.title for e in discard(self.draft(), "experience", 1).experience] == ["Real"]

    def test_confirm_all(self):
        assert confirm_all(self.draft()).pending_items() == []

    def test_originals_untouched_and_bad_arguments_rejected(self):
        p = self.draft()
        confirm(p, "projects", 0)
        assert p.projects[0].confirmed is False
        for args in (("nope", 0), ("experience", 5), ("experience", -1)):
            with pytest.raises(ValueError):
                confirm(p, *args)
            with pytest.raises(ValueError):
                discard(p, *args)
