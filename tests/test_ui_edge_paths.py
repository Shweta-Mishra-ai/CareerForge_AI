"""The less common branches of the pages: failures, empty states and unusual data."""

import pytest
from helpers import scripted_client
from test_render_cv import experienced, fresher
from test_ui_features import page, set_job
from ui_helpers import button, find, new_app, open_page, profile_of, texts

from careerforge.ai.errors import AIQuotaExhausted, AIUnavailable
from careerforge.ingest.errors import UnsafeURL
from careerforge.models import Contact, DateRange, Experience, Profile, Project

pytestmark = pytest.mark.usefixtures("ui_env")


class TestFetchPostingFromLink:
    def fetch(self, url="https://jobs.example/p/1"):
        at = page("match")
        at.text_input(key="job-url").set_value(url)
        button(at, "Fetch").click()
        return at.run()

    def test_fetched_text_becomes_the_posting(self, monkeypatch):
        monkeypatch.setattr(
            "careerforge.ingest.web.fetch_job_text", lambda url, **k: "Fetched Role\nRequirements: Python"
        )
        at = self.fetch()
        assert not at.exception and at.session_state["job_text"].startswith("Fetched Role")
        assert at.text_area(key="job-input").value.startswith("Fetched Role")

    def test_a_refused_or_failed_fetch_is_a_sentence(self, monkeypatch):
        def refuse(url, **k):
            raise UnsafeURL("That address is not allowed: it points to a private network")

        monkeypatch.setattr("careerforge.ingest.web.fetch_job_text", refuse)
        at = self.fetch("http://10.0.0.1/admin")
        assert not at.exception and "private network" in at.error[0].value
        assert not (at.session_state["job_text"] if "job_text" in at.session_state else "")


class TestAtsEdges:
    def test_section_tips_for_a_cv_with_nothing_to_flag(self, monkeypatch):
        monkeypatch.setattr("careerforge.ui.pages.match.section_tips", lambda p, r: [], raising=False)
        import careerforge.analytics as analytics

        monkeypatch.setattr(analytics, "section_tips", lambda p, r: [])
        at = page("match")
        at.radio(key="ats-view").set_value("Section tips").run()
        assert not at.exception and any("nothing stood out" in s.value for s in at.success)

    def test_smart_matches_with_no_verifiable_match_says_so(self, ui_env):
        client, _ = scripted_client({"matches": []})
        ui_env.ai(client)
        at = page("match")
        set_job(at)
        at.radio(key="ats-view").set_value("Smart matches (AI)").run()
        button(at, "Find smart matches").click()
        at.run()
        assert "no additional matches" in texts(at)


class TestInsightsEdges:
    def go(self, profile, view, job=None):
        at = page("insights", profile)
        if job:
            set_job(at, job)
        at.radio(key="insights-view").set_value(view).run()
        return at

    def test_gaps_in_the_career_are_called_out(self):
        gappy = experienced().model_copy(
            update={
                "experience": [
                    Experience(title="A", company="X", dates=DateRange(start="2010", end="2011")),
                    Experience(title="B", company="Y", dates=DateRange(start="2016", end="2018")),
                ]
            }
        )
        at = page("insights", gappy)
        assert any("48 months between X and Y" in w.value for w in at.warning)

    def test_no_skills_means_no_chart(self):
        at = self.go(experienced().model_copy(update={"skills": []}), "Skill coverage")
        assert "add skills to see coverage" in texts(at)

    def test_a_posting_without_keywords(self):
        at = self.go(experienced(), "Keyword heat", job="We are a friendly company. Come and join us today.")
        assert not at.exception and "no keywords were found" in texts(at)

    def test_roadmap_when_everything_is_covered(self):
        at = self.go(experienced(), "Learning roadmap", job="Dev\nRequirements: Python")
        assert "already cover everything" in texts(at)

    def test_roadmap_needs_a_posting(self):
        assert "paste a job posting" in texts(self.go(experienced(), "Learning roadmap"))


class TestWriteEdges:
    def test_cover_letter_failure_is_a_sentence_and_no_letter_is_kept(self, ui_env):
        client, _ = scripted_client(*[AIUnavailable("down")] * 6)
        ui_env.ai(client)
        at = page("write")
        set_job(at)
        button(at, "Create my cover letter").click()
        at.run()
        assert "could not be reached" in at.error[0].value and "letter_draft" not in at.session_state

    def test_interview_failure_is_a_sentence(self, ui_env):
        client, _ = scripted_client(*[AIQuotaExhausted("daily")] * 3)
        ui_env.ai(client)
        at = page("write")
        set_job(at)
        at.radio(key="write-view").set_value("Interview prep").run()
        button(at, "Prepare my interview questions").click()
        at.run()
        assert "out of quota" in at.error[0].value and not at.exception

    def test_interview_needs_a_posting(self):
        at = page("write")
        at.radio(key="write-view").set_value("Interview prep").run()
        assert "paste a job posting above first" in texts(at)

    def test_questions_without_tips_or_evidence_render(self, ui_env):
        reply = {"questions": [{"category": "technical", "question": "Explain event-driven design.", "why_asked": "Core skill", "cv_evidence": "", "tips": ""}]}  # fmt: skip
        client, _ = scripted_client(reply)
        ui_env.ai(client)
        at = page("write")
        set_job(at)
        at.radio(key="write-view").set_value("Interview prep").run()
        button(at, "Prepare my interview questions").click()
        at.run()
        body = " ".join(m.value for m in at.markdown)
        assert "no direct example" in body and "**Tip:**" not in body


class TestExportEdges:
    def test_a_build_failure_is_explained_and_nothing_is_offered(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("WeasyPrint exploded with /some/path")

        monkeypatch.setattr("careerforge.render.cv.render_cv_pdf", boom)
        at = page("cv")
        button(at, "Build my files").click()
        at.run()
        assert not at.exception and "Something unexpected went wrong (RuntimeError)" in at.error[0].value
        assert "/some/path" not in at.error[0].value and "built_files" not in at.session_state

    def test_pdf_warnings_are_shown_for_a_long_cv(self):
        from test_render_cv import maximal

        at = page("cv", maximal())
        find(at.select_slider, "Density").set_value("Relaxed (more white space)").run()
        button(at, "Build my files").click()
        at.run()
        assert any("pages" in w.value for w in at.warning)

    def test_portfolio_blockers_are_listed_when_not_publishable(self):
        at = page("portfolio", Profile(name="Sam Rivera", contact=Contact(email="sam@gmail.com")))
        assert not at.exception and any("at least one experience, project or education" in e.value for e in at.error)

    def test_portfolio_warnings_are_shown(self):
        p = fresher().model_copy(update={"summary": ""})
        at = page("portfolio", p)
        assert any("About section is left out" in w.value for w in at.warning)


class TestSettingsEdges:
    def test_a_broken_configuration_is_reported_not_crashed(self, ui_env, monkeypatch):
        from careerforge.ui import state

        ui_env.site(GEMINI_API_KEY="k")

        def broken():
            raise RuntimeError("cannot build the client")

        monkeypatch.setattr(state, "_cached_client", lambda *a, **k: broken())
        at = open_page(new_app().run(), "settings")
        assert not at.exception and any("Something unexpected" in e.value for e in at.error)


class TestProfileOddities:
    def test_a_profile_with_only_projects_and_no_dates_works_on_every_page(self):
        p = Profile(name="Sam Rivera", contact=Contact(email="sam.rivera@gmail.com"), projects=[Project(name="Tool")])
        at = new_app(p).run()
        for name in ("review", "match", "insights", "cv", "portfolio", "write", "jobs", "settings", "about"):
            open_page(at, name)
            assert not at.exception, name
        assert profile_of(at) == p  # browsing never changes the profile


def test_without_a_pdf_engine_the_page_still_offers_word_text_and_html(monkeypatch):
    from careerforge.render import cv

    def missing():
        raise cv.PdfEngineUnavailable("PDF export needs the Pango text library, which is not available here.")

    monkeypatch.setattr(cv, "_pdf_engine", missing)
    at = page("cv")
    button(at, "Build my files").click()
    at.run()
    assert not at.exception and any("Pango" in w.value for w in at.warning)
    labels = {b.label for b in at.get("download_button")}
    assert {"Word (.docx)", "Plain text", "HTML"} <= labels and "PDF" not in labels
    assert "pdf unavailable on this machine" in texts(at)
    assert at.session_state["built_files"][1]["pdf"] is None
