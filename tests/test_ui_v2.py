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
        open_page(at, "portfolio")
        return at

    def test_the_automatic_theme_is_offered_and_switches_with_the_visitors_device(self):
        at = self.page()
        at.radio(key="pf-theme").set_value("auto").run()
        html = at.get("iframe")[0].proto.srcdoc
        assert not at.exception and "prefers-color-scheme: dark" in html
        assert "custom" not in at.selectbox(key="pf-colour").options  # own colour cannot work on both pages
        assert "no single colour is readable" in texts(at)
        at.selectbox(key="pf-colour").set_value("teal").run()  # a named colour has a light and a dark shade
        html = at.get("iframe")[0].proto.srcdoc
        assert not at.exception and not at.error and "#115e59" in html and "#5eead4" in html

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


class TestOldAppParity:
    """Features the old CareerBoost app had that the merged app must also have."""

    def test_the_posting_upload_box_exists_on_every_page_that_takes_a_posting(self):
        for name in ("match", "tailor", "insights", "write"):
            at = new_app(experienced()).run()
            open_page(at, name)
            labels = [e.label for e in at.expander]
            assert "Or upload the posting (PDF, Word or text file)" in labels, name

    def test_roadmap_markdown_is_a_checklist_of_the_roadmaps_own_fields(self):
        from careerforge.ats.report import analyze
        from careerforge.roadmap import build_roadmap, roadmap_markdown

        p = experienced()
        items = build_roadmap(analyze(p, "Dev\nRequirements: Terraform, gRPC, Rust", today=TODAY), p)
        md = roadmap_markdown(items)
        assert md.startswith("# Learning roadmap") and md.count("## ") == len(items) and "**Project idea:**" in md
        assert "1. " in md and md.rstrip().endswith("really used it.")
        assert roadmap_markdown([]).startswith("# Learning roadmap")


class TestPortfolioLayouts:
    def page(self):
        at = new_app(experienced()).run()
        open_page(at, "portfolio")
        return at

    def test_each_layout_can_be_chosen_and_changes_the_preview(self):
        at = self.page()
        assert 'class="profile"' in at.get("iframe")[0].proto.srcdoc
        for layout, marker in (
            ("hero", 'class="hero"'),
            ("editorial", 'class="masthead"'),
            ("profile", 'class="profile"'),
        ):
            at.radio(key="pf-layout").set_value(layout).run()
            html = at.get("iframe")[0].proto.srcdoc
            assert not at.exception and marker in html and "Priya Nair" in html, layout

    def test_the_city_is_hidden_until_asked(self):
        at = self.page()
        assert "Bengaluru" not in at.get("iframe")[0].proto.srcdoc
        at.checkbox(key="pf-location").set_value(True).run()
        assert "Bengaluru" in at.get("iframe")[0].proto.srcdoc

    def test_hosting_is_explained_and_links_are_offered(self):
        at = self.page()
        urls = [b.proto.url for b in at.get("link_button")]
        assert "https://app.netlify.com/drop" in urls and len(urls) == 3
        assert "nothing is hosted for you" in texts(at)


class TestSidebarSafety:
    """Clearing is a destructive click: it asks first. A save file too big to load back says so."""

    def app(self):
        return new_app(experienced()).run()

    def test_clear_everything_asks_before_it_deletes(self):
        at = self.app()
        button(at, "Clear everything").click()
        at.run()
        assert at.session_state["profile"] is not None  # nothing was deleted by the first click
        assert "this removes your profile" in " ".join(w.value.lower() for w in at.sidebar.warning)
        button(at, "Yes, clear").click()
        at.run()
        assert "profile" not in at.session_state or at.session_state["profile"] is None

    def test_keep_cancels_the_clear(self):
        at = self.app()
        button(at, "Clear everything").click()
        at.run()
        button(at, "Keep").click()
        at.run()
        assert at.session_state["profile"] is not None and not at.sidebar.warning
        assert any(b.label == "Clear everything" for b in at.sidebar.button)

    def test_a_save_file_too_large_to_load_back_is_flagged(self, monkeypatch):
        from careerforge import models

        monkeypatch.setattr(models, "MAX_FILE_BYTES", 500)
        at = self.app()
        assert any("too big to be loaded back" in e.value for e in at.sidebar.error)

    def test_a_normal_save_file_raises_no_flag(self):
        assert not self.app().sidebar.error

    def test_the_real_save_limit_is_one_the_loader_enforces(self):
        from careerforge.models import MAX_FILE_BYTES, Profile, ProfileError

        with pytest.raises(ProfileError):
            Profile.from_json(" " * (MAX_FILE_BYTES + 1))


class TestTrackerSummary:
    def test_the_tracker_shows_how_many_applications_are_at_each_stage(self):
        t, _ = Tracker().add("A", "Dev", status="applied")
        t, _ = t.add("B", "Dev", status="applied")
        t, _ = t.add("C", "Dev", status="interview")
        at = new_app(experienced(), tracker=t).run()
        open_page(at, "jobs")
        at.radio(key="jobs-view").set_value("Application tracker").run()
        assert {m.label: m.value for m in at.metric} == {"Applied": "2", "Interview": "1"}


class TestLinkedInPageSections:
    """Every part of the LinkedIn page, including the ones a short CV never shows."""

    def page(self, profile):
        at = new_app(profile).run()
        return open_page(at, "linkedin")

    def test_a_full_profile_shows_experience_education_projects_and_certifications(self):
        from test_render_cv import maximal

        from careerforge.models import Project

        p = maximal().model_copy(
            update={
                "projects": [
                    Project(name="Tool", description="Does things.", url="https://github.com/a/tool", tech=["Go"])
                ]
            }
        )
        at = self.page(p)
        body = texts(at)
        assert not at.exception
        for heading in ("experience", "skills", "education", "projects", "certifications"):
            assert heading in body, heading
        assert "github" in body and "a/tool" in body and "skills used: go" in body
        assert "pin these three as top skills" in body
        assert any("characters" in c.value for c in at.caption)

    def test_a_profile_with_nothing_to_paste_says_so_instead_of_showing_empty_boxes(self):
        from careerforge.models import Contact, Profile, Project

        at = self.page(
            Profile(name="Sam Rivera", contact=Contact(email="sam@gmail.com"), projects=[Project(name="Tool")])
        )
        body = texts(at)
        assert not at.exception and "nothing to paste" in body and "no experience in your profile" in body

    def test_character_counters_are_shown_against_linkedins_limits(self):
        from test_render_cv import experienced

        at = self.page(experienced())
        captions = [c.value for c in at.caption]
        assert any("of 220 characters" in c for c in captions) and any("of 2600 characters" in c for c in captions)


class TestSettingsConfigurationWarnings:
    def test_a_configuration_problem_is_shown_on_the_settings_page_and_in_the_sidebar(self, monkeypatch):
        from careerforge.ui import state

        monkeypatch.setattr(
            state, "config_problems", lambda: ["The secrets could not be parsed, so every key is ignored."]
        )
        at = open_page(new_app().run(), "settings")
        assert any("could not be parsed" in w.value for w in at.warning)
        assert "check settings" in texts(at)
