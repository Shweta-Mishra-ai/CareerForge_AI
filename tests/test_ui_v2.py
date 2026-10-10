"""The v2 screens: job filters and saved searches, next actions, the portfolio options and project fields."""

from datetime import date, timedelta

import pytest
from test_render_cv import experienced
from ui_helpers import button, find, new_app, open_page, texts

from careerforge import jobs
from careerforge.jobs import Job
from careerforge.tracker import Tracker

pytestmark = pytest.mark.usefixtures("ui_env")

TODAY = date.today()


def board_jobs():
    old = (TODAY - timedelta(days=90)).isoformat()
    return [
        Job("Senior Python Engineer", "Acme", "Remote", "We need Python, Kafka and Docker.", "https://acme.example/1", "Remotive", remote=True, posted=TODAY.isoformat()),
        Job("Junior Python Developer", "Beta", "Berlin", "We need Python.", "https://beta.example/2", "Remotive", type="Contract", posted=old),
        Job("Data Entry Clerk", "Gamma", "Remote", "You must pay a registration fee. Python not needed.", "https://gamma.example/3", "Remotive"),
    ]  # fmt: skip


class FakeBoard:
    name = "Remotive"

    def __init__(self, *a, **k):
        pass

    def search(self, query, limit):
        return board_jobs()


class FakeCompanyBoard:
    name = "Greenhouse (acme)"

    def __init__(self, token, **k):
        self.token = token

    def search(self, query, limit):
        return [
            Job(
                "Platform Engineer",
                "Acme Corp",
                "Pune",
                "Python, Kafka and Kubernetes.",
                "https://boards.greenhouse.io/acme/jobs/9",
                self.name,
            )
        ]


@pytest.fixture(autouse=True)
def fake_boards(monkeypatch):
    jobs.clear_cache()
    monkeypatch.setattr(jobs, "RemotiveProvider", FakeBoard)
    monkeypatch.setattr(
        jobs, "JobicyProvider", lambda *a, **k: type("J", (), {"name": "Jobicy", "search": lambda s, q, n: []})()
    )
    monkeypatch.setattr(jobs, "GreenhouseProvider", FakeCompanyBoard)


def jobs_page(**session):
    at = new_app(experienced(), **session).run()
    return open_page(at, "jobs")


def searched(at=None, query="python backend"):
    at = at or jobs_page()
    at.text_input(key="job-query").set_value(query).run()
    button(at, "Search").click()
    return at.run()


def titles(at):
    return [
        m.value.split("**")[1] for m in at.markdown if m.value.startswith("**") and " at " in m.value.split("\n")[0]
    ]


class TestFindJobs:
    def test_every_card_explains_its_score_and_names_its_source(self):
        at = searched()
        assert not at.exception
        assert [e.label for e in at.expander].count("How this score was calculated") == 3
        assert "via remotive" in texts(at) and "job data comes from the boards named on each card" in texts(at)

    def test_a_posting_that_asks_for_a_fee_is_flagged_and_can_be_hidden(self):
        at = searched()
        assert any("Asks you to pay a fee" in w.value for w in at.warning)
        find(at.checkbox, "Hide postings with warnings").set_value(True).run()
        assert "data entry clerk" not in texts(at) and "2 of 3 postings shown" in texts(at)

    def test_filters_narrow_the_list(self):
        at = searched()
        assert "3 of 3 postings shown" in texts(at)
        find(at.multiselect, "Seniority").set_value(["junior"]).run()
        assert "1 of 3 postings shown" in texts(at) and "junior python developer" in texts(at)
        find(at.multiselect, "Seniority").set_value([]).run()
        find(at.multiselect, "Employment").set_value(["contract"]).run()
        assert "1 of 3 postings shown" in texts(at)
        find(at.multiselect, "Employment").set_value([]).run()
        find(at.selectbox, "Posted").set_value("Last 7 days").run()
        assert "1 of 3 postings shown" in texts(at) and "senior python engineer" in texts(at)

    def test_remote_only_hides_places_that_do_not_say_remote(self):
        at = jobs_page()
        at.checkbox(key="job-remote").set_value(True).run()
        searched(at)
        assert "junior python developer" not in texts(at)

    def test_the_minimum_match_slider_filters(self):
        at = searched()
        find(at.slider, "Minimum match").set_value(100).run()
        assert "0 of 3 postings shown" in texts(at)

    def test_only_new_postings_are_marked_on_the_next_search(self):
        at = searched()
        assert "3 new since your last search" in texts(at)
        assert len(at.session_state["tracker"].seen) == 3
        jobs.clear_cache()
        at = searched(at)
        assert "0 new since your last search" in texts(at)

    def test_unsafe_links_are_never_remembered(self, monkeypatch):
        class Evil(FakeBoard):
            def search(self, query, limit):
                return [Job("Dev", "X", "Remote", "Python", "javascript:alert(1)", "Remotive")]

        monkeypatch.setattr(jobs, "RemotiveProvider", Evil)
        at = searched()
        assert not at.exception and at.session_state["tracker"].seen == []

    def test_company_careers_links_are_searched_and_bad_ones_are_named(self):
        at = jobs_page()
        at.text_area(key="job-boards-text").set_value("https://boards.greenhouse.io/acme\nhttps://evil.example/x").run()
        assert any("Not a Greenhouse or Lever link, ignored: https://evil.example/x" in w.value for w in at.warning)
        searched(at)
        assert "platform engineer" in texts(at) and "via greenhouse" in texts(at)

    def test_searches_can_be_saved_loaded_and_deleted(self):
        at = jobs_page()
        at.text_input(key="job-query").set_value("data engineer").run()
        at.text_input(key="job-location").set_value("Pune").run()
        button(at, "Save this search").click()
        at.run()
        (saved,) = at.session_state["tracker"].saved_searches
        assert (saved.query, saved.location) == ("data engineer", "Pune")
        at.text_input(key="job-query").set_value("something else").run()
        button(at, "Load").click()
        at.run()
        assert (
            at.text_input(key="job-query").value == "data engineer"
            and at.text_input(key="job-location").value == "Pune"
        )
        button(at, "Delete").click()
        at.run()
        assert at.session_state["tracker"].saved_searches == []

    def test_saving_an_empty_search_is_a_message(self):
        at = jobs_page()
        at.text_input(key="job-query").set_value("   ").run()
        button(at, "Save this search").click()
        at.run()
        assert not at.exception and at.error

    def test_add_to_tracker_remembers_the_source(self):
        at = searched()
        button(at, "Add to tracker").click()
        at.run()
        (app,) = at.session_state["tracker"].applications
        assert app.source == "Remotive"


class TestTrackerV2:
    def page(self, tracker=None):
        at = new_app(experienced(), tracker=tracker or Tracker()).run()
        open_page(at, "jobs")
        at.radio(key="jobs-view").set_value("Application tracker").run()
        return at

    def test_source_and_contact_are_saved_with_the_application(self):
        at = self.page()
        find(at.text_input, "Company").set_value("Acme")
        find(at.text_input, "Role").set_value("Engineer")
        find(at.text_input, "Where you found it").set_value("LinkedIn")
        find(at.text_input, "Recruiter or contact").set_value("Ms. Rao")
        button(at, "Add application").click()
        at.run()
        (app,) = at.session_state["tracker"].applications
        assert (app.source, app.contact) == ("LinkedIn", "Ms. Rao")

    def test_a_next_action_that_is_due_is_listed_and_a_bad_date_is_a_message(self):
        t, app = Tracker().add("Acme", "Engineer", status="applied")
        at = self.page(t)
        at.text_input(key=f"tracker-action-{app.id}").set_value("Send the note").run()
        at.text_input(key=f"tracker-due-{app.id}").set_value("next week").run()
        button(at, "Save details").click()
        at.run()
        assert not at.exception and at.error
        at.text_input(key=f"tracker-due-{app.id}").set_value((TODAY - timedelta(days=2)).isoformat()).run()
        button(at, "Save details").click()
        at.run()
        assert "your next actions" in texts(at) and "send the note" in texts(at) and "2 day(s) overdue" in texts(at)
        assert at.session_state["tracker"].get(app.id).next_action == "Send the note"


class TestPortfolioTab:
    def page(self, profile=None):
        at = new_app(profile or experienced()).run()
        open_page(at, "export")
        at.radio(key="export-tab").set_value("Portfolio website").run()
        return at

    def test_the_automatic_theme_is_offered_and_switches_with_the_visitors_device(self):
        at = self.page()
        at.radio(key="pf-theme").set_value("auto").run()
        html = at.get("iframe")[0].proto.srcdoc
        assert not at.exception and "prefers-color-scheme: dark" in html
        assert at.checkbox(key="pf-use-accent").disabled and "no single accent is readable" in texts(at)

    def test_a_custom_domain_is_validated_and_explained(self):
        at = self.page()
        at.text_input(key="pf-domain").set_value("https://jane.dev/x").run()
        assert any("custom domain must look like" in e.value for e in at.error)
        at.text_input(key="pf-domain").set_value("jane.dev").run()
        assert (
            not at.exception
            and not at.error
            and 'rel="canonical" href="https://jane.dev/"' in at.get("iframe")[0].proto.srcdoc
        )

    def test_noindex_is_written_into_the_page(self):
        at = self.page()
        at.checkbox(key="pf-noindex").set_value(True).run()
        assert '<meta name="robots" content="noindex">' in at.get("iframe")[0].proto.srcdoc

    def test_the_cv_download_button_appears_when_asked(self):
        at = self.page()
        assert "Download my CV" not in at.get("iframe")[0].proto.srcdoc
        at.checkbox(key="pf-cv").set_value(True).run()
        assert not at.exception and 'href="Priya_Nair_CV.pdf" download' in at.get("iframe")[0].proto.srcdoc

    def test_the_cv_is_left_out_with_a_reason_when_the_pdf_engine_is_missing(self, monkeypatch):
        from careerforge.render import cv

        def missing():
            raise cv.PdfEngineUnavailable("PDF export needs the Pango text library, which is not available here.")

        monkeypatch.setattr(cv, "_pdf_engine", missing)
        at = self.page()
        at.checkbox(key="pf-cv").set_value(True).run()
        assert not at.exception and "Download my CV" not in at.get("iframe")[0].proto.srcdoc
        assert any("Pango" in w.value for w in at.warning) and any("no CV download link" in w.value for w in at.warning)

    def test_featured_projects_show_as_case_studies(self):
        from careerforge.models import Project

        p = experienced().model_copy(
            update={"projects": [Project(name="Big One", description="Flagship.", featured=True)]}
        )
        html = self.page(p).get("iframe")[0].proto.srcdoc
        assert 'class="case"' in html and "Case study" in html
