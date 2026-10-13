"""Start and Review pages, driven through the whole app."""

import pytest
from helpers import scripted_client
from test_render_cv import experienced
from ui_helpers import button, find, new_app, open_page, profile_of, rev, texts

from careerforge.ai.errors import AIUnavailable
from careerforge.ingest.github import GitHubImport
from careerforge.models import Education, Experience, Profile, Project

pytestmark = pytest.mark.usefixtures("ui_env")

CV = open(__file__.replace("test_ui_start_review.py", "fixtures/cv_ready.txt"), encoding="utf-8").read()


def paste(at, text=CV):
    at.radio(key="start-source").set_value("Paste text").run()
    at.text_area[0].set_value(text).run()
    return at


class TestStart:
    def test_first_screen_without_a_profile(self):
        at = new_app().run()
        assert not at.exception and at.title[0].value == "Start"
        assert "no profile loaded yet" in texts(at)
        assert [r.label for r in at.radio][:1] == ["Where are your details?"]

    def test_without_ai_the_user_is_told_which_reader_is_used(self):
        at = new_app().run()
        assert any("basic reader" in i.value for i in at.info)
        assert not [r for r in at.radio if r.label.startswith("How should")]  # no choice to make

    def test_paste_reads_with_the_basic_reader_and_lands_on_review(self):
        at = paste(new_app().run())
        button(at, "Read this text").click()
        at.run()
        assert not at.exception
        p = profile_of(at)
        assert p.name == "Priya Nair" and len(p.experience) == 2 and len(p.education) == 1
        assert at.title[0].value == "Review & edit"

    def test_short_paste_is_refused_with_a_message(self):
        at = paste(new_app().run(), "too short")
        button(at, "Read this text").click()
        at.run()
        assert "not enough text" in texts(at) and profile_of(at) is None

    def test_upload_a_text_file(self):
        at = new_app().run()
        at.file_uploader[0].upload("cv.txt", CV.encode(), "text/plain")
        at.run()
        button(at, "Read this file").click()
        at.run()
        assert not at.exception and profile_of(at).name == "Priya Nair"

    def test_an_unreadable_file_gives_a_sentence_not_a_traceback(self):
        at = new_app().run()
        at.file_uploader[0].upload("cv.pdf", b"%PDF-1.4 not really", "application/pdf")
        at.run()
        button(at, "Read this file").click()
        at.run()
        assert not at.exception and at.error and "traceback" not in at.error[0].value.lower()
        assert profile_of(at) is None

    def test_start_from_scratch(self):
        at = new_app().run()
        at.radio(key="start-source").set_value("Start from scratch").run()
        button(at, "empty profile").click()
        at.run()
        assert profile_of(at) == Profile() and at.title[0].value == "Review & edit"

    def test_a_loaded_profile_warns_before_it_is_replaced(self):
        at = new_app(experienced()).run()
        assert any("already loaded" in w.value for w in at.warning)

    def test_saved_profile_round_trip_restores_profile_and_tracker(self):
        from careerforge.tracker import Tracker, dump_file

        tracker, _ = Tracker().add("Acme", "Dev")
        data = dump_file(experienced(), tracker).encode()
        at = new_app().run()
        at.file_uploader[0].upload("p.json", data, "application/json")
        at.run()
        button(at, "Read this file").click()
        at.run()
        assert profile_of(at).name == "Priya Nair"
        assert [a.company for a in at.session_state["tracker"].applications] == ["Acme"]


class TestStartWithAI:
    def test_reader_choice_appears_and_ai_extraction_is_used(self, ui_env):
        reply = {"name": "Priya Nair", "headline": "Engineer", "skills": ["Python"]}
        client, provider = scripted_client(reply)
        ui_env.ai(client)
        at = new_app().run()
        assert find(at.radio, "How should your document be read").value.startswith("AI")
        paste(at)
        button(at, "Read this text").click()
        at.run()
        assert not at.exception and len(provider.requests) == 1
        assert profile_of(at).name == "Priya Nair"
        assert at.session_state["ai_calls"] == 1

    def test_ai_failure_is_loud_and_offers_the_basic_reader_which_then_works(self, ui_env):
        client, _ = scripted_client(*[AIUnavailable("network down")] * 6)
        ui_env.ai(client)
        at = new_app().run()
        paste(at)
        button(at, "Read this text").click()
        at.run()
        assert profile_of(at) is None
        assert "could not be reached" in at.error[0].value
        button(at, "basic reader instead").click()
        at.run()
        assert profile_of(at).name == "Priya Nair" and len(profile_of(at).experience) == 2

    def test_choosing_basic_never_calls_the_ai(self, ui_env):
        client, provider = scripted_client()
        ui_env.ai(client)
        at = new_app().run()
        find(at.radio, "How should your document be read").set_value("Basic (no AI, nothing leaves this app)").run()
        paste(at)
        button(at, "Read this text").click()
        at.run()
        assert provider.requests == [] and profile_of(at).name == "Priya Nair"

    def test_shared_quota_stops_ai_use_after_the_limit(self, ui_env):
        client, provider = scripted_client()
        ui_env.ai(client)
        ui_env.site(CAREERFORGE_SESSION_AI_LIMIT="0")
        at = new_app().run()
        paste(at)
        button(at, "Read this text").click()
        at.run()
        assert provider.requests == [] and "shared ai actions" in at.error[0].value.lower()
        assert profile_of(at) is None


class TestGitHub:
    IMPORT = GitHubImport(
        username="octo", name="Octo Cat", bio="", location="Remote", website="", company="", profile_url="https://github.com/octo",
        public_repos=2, followers=1, total_stars=7,
        projects=(Project(name="alpha", description="Alpha project", stars=5, tech=["Go"]), Project(name="beta")),
        languages=("Go", "Python"), warnings=("2 repos shown",),
    )  # fmt: skip

    def test_creates_a_projects_only_profile_and_says_so(self, monkeypatch):
        monkeypatch.setattr("careerforge.ingest.github.fetch_github", lambda user, token=None, **k: self.IMPORT)
        at = new_app().run()
        at.radio(key="start-source").set_value("GitHub").run()
        at.text_input(key="gh-user").set_value("octo").run()
        button(at, "Create a profile from GitHub").click()
        at.run()
        p = profile_of(at)
        assert not at.exception and [x.name for x in p.projects] == ["alpha", "beta"]
        assert p.experience == [] and p.education == [] and set(p.skills) == {"Go", "Python"}
        assert any("projects and skills only" in w for w in at.session_state["ingest"].warnings)
        assert any("2 public repositories, 7 stars, 1 followers" in w for w in at.session_state["ingest"].warnings)

    def test_adds_to_an_existing_profile_without_duplicates_or_touching_jobs(self, monkeypatch):
        monkeypatch.setattr("careerforge.ingest.github.fetch_github", lambda user, token=None, **k: self.IMPORT)
        base = experienced().model_copy(update={"projects": [Project(name="Alpha")]})
        at = new_app(base).run()
        at.radio(key="start-source").set_value("GitHub").run()
        at.text_input(key="gh-user").set_value("octo").run()
        button(at, "Add projects to my current profile").click()
        at.run()
        p = profile_of(at)
        assert [x.name for x in p.projects] == ["Alpha", "beta"] and len(p.experience) == 2

    def test_a_bad_username_is_a_sentence(self):
        at = new_app().run()
        at.radio(key="start-source").set_value("GitHub").run()
        at.text_input(key="gh-user").set_value("not a valid user!!").run()
        button(at, "Create a profile from GitHub").click()
        at.run()
        assert not at.exception and at.error and profile_of(at) is None


class TestReview:
    def page(self, profile=None, section="Basics"):
        at = new_app(profile or experienced()).run()
        open_page(at, "review")
        if section != "Basics":
            at.radio(key="review-section").set_value(section).run()
        return at

    def test_requires_a_profile(self):
        at = open_page(new_app().run(), "review")
        assert not at.exception and any("Start by adding" in i.value for i in at.info)

    def test_basics_are_prefilled_and_saved(self):
        at = self.page()
        r = rev(at)
        assert at.text_input(key=f"name-{r}").value == "Priya Nair"
        at.text_input(key=f"headline-{r}").set_value("Staff Engineer")
        at.text_input(key=f"phone-{r}").set_value("+44 20 7946 0958")
        button(at, "Save basics").click()
        at.run()
        p = profile_of(at)
        assert (p.headline, p.contact.phone) == ("Staff Engineer", "+44 20 7946 0958") and rev(at) == r + 1

    def test_invalid_input_is_explained_and_nothing_is_saved(self):
        at = self.page()
        r = rev(at)
        at.text_input(key=f"email-{r}").set_value("not-an-email")
        at.text_input(key=f"name-{r}").set_value("Changed Name")
        button(at, "Save basics").click()
        at.run()
        assert any("Not saved" in e.value and "email" in e.value.lower() for e in at.error)
        assert profile_of(at).name == "Priya Nair"  # the good field was not half-applied

    def test_skills_and_languages(self):
        at = self.page(section="Skills")
        r = rev(at)
        at.text_area(key=f"skills-{r}").set_value("Python, Go\nRust, python")
        at.text_input(key=f"languages-{r}").set_value("English, Hindi")
        button(at, "Save skills").click()
        at.run()
        p = profile_of(at)
        assert p.skills == ["Python", "Go", "Rust"] and p.languages == ["English", "Hindi"]

    def test_edit_an_experience_entry_including_bullets_and_dates(self):
        at = self.page(section="Experience")
        r = rev(at)
        at.text_input(key=f"experience-0-title-{r}").set_value("Principal Engineer")
        at.text_input(key=f"experience-0-dates.start-{r}").set_value("Jan 2021")
        at.text_area(key=f"experience-0-bullets-{r}").set_value(
            "Cut costs by 30% across 12 services.\nLed a team of 5."
        )
        button(at, "Save experience").click()
        at.run()
        e = profile_of(at).experience[0]
        assert e.title == "Principal Engineer" and e.dates.start == "2021-01" and e.dates.current
        assert e.bullets == ["Cut costs by 30% across 12 services.", "Led a team of 5."]
        assert e.company == "Finlytics Pvt Ltd"  # untouched fields survive

    def test_end_date_before_start_is_rejected_with_a_clear_message(self):
        at = self.page(section="Experience")
        r = rev(at)
        at.checkbox(key=f"experience-0-dates.current-{r}").set_value(False)
        at.text_input(key=f"experience-0-dates.end-{r}").set_value("2019")
        button(at, "Save experience").click()
        at.run()
        assert any("before start" in e.value.lower() for e in at.error)

    def test_add_move_and_remove_entries(self):
        at = self.page(section="Experience")
        button(at, "Add experience").click()
        at.run()
        p = profile_of(at)
        assert len(p.experience) == 3 and p.experience[2].origin == "user" and p.experience[2].title == ""
        r = rev(at)
        find(at.selectbox, "Move or remove").set_value(2).run()
        button(at, "Move up").click()
        at.run()
        assert profile_of(at).experience[1].title == ""
        find(at.selectbox, "Move or remove").set_value(1).run()
        button(at, "Remove").click()
        at.run()
        p = profile_of(at)
        assert [e.company for e in p.experience] == ["Finlytics Pvt Ltd", "ShipFast Logistics"] and rev(at) > r

    @pytest.mark.parametrize(
        "section,key,field,value",
        [
            ("Education", "education", "degree", "M.Tech"),
            ("Projects", "projects", "name", "My Tool"),
            ("Certifications", "certifications", "name", "CKA"),
        ],
    )
    def test_other_list_sections_add_and_edit(self, section, key, field, value):
        at = self.page(section=section)
        button(at, "Add ").click()
        at.run()
        r = rev(at)
        before = len(getattr(profile_of(at), key))
        at.text_input(key=f"{key}-{before - 1}-{field}-{r}").set_value(value)
        button(at, f"Save {section.lower()}").click()
        at.run()
        assert getattr(profile_of(at), key)[-1].model_dump()[field] == value

    def test_project_fields_stars_tech_and_link(self):
        p = experienced().model_copy(update={"projects": [Project(name="Tool")]})
        at = self.page(p, "Projects")
        r = rev(at)
        at.text_input(key=f"projects-0-tech-{r}").set_value("Go, Kafka")
        at.text_input(key=f"projects-0-url-{r}").set_value("github.com/priya-demo/tool")
        at.number_input(key=f"projects-0-stars-{r}").set_value(12)
        button(at, "Save projects").click()
        at.run()
        pr = profile_of(at).projects[0]
        assert (pr.tech, pr.url, pr.stars) == (["Go", "Kafka"], "https://github.com/priya-demo/tool", 12)

    def test_demo_link_and_featured_flag_are_editable_and_checked(self):
        p = experienced().model_copy(update={"projects": [Project(name="Tool")]})
        at = self.page(p, "Projects")
        r = rev(at)
        at.text_input(key=f"projects-0-demo_url-{r}").set_value("tool.example.com")
        at.checkbox(key=f"projects-0-featured-{r}").set_value(True)
        button(at, "Save projects").click()
        at.run()
        pr = profile_of(at).projects[0]
        assert (pr.demo_url, pr.featured) == ("https://tool.example.com", True)

    def test_a_javascript_demo_link_is_refused(self):
        p = experienced().model_copy(update={"projects": [Project(name="Tool")]})
        at = self.page(p, "Projects")
        at.text_input(key=f"projects-0-demo_url-{rev(at)}").set_value("javascript:alert(1)")
        button(at, "Save projects").click()
        at.run()
        assert any("Not saved" in e.value for e in at.error) and profile_of(at).projects[0].demo_url == ""

    def test_javascript_links_are_refused(self):
        p = experienced().model_copy(update={"projects": [Project(name="Tool")]})
        at = self.page(p, "Projects")
        at.text_input(key=f"projects-0-url-{rev(at)}").set_value("javascript:alert(1)")
        button(at, "Save projects").click()
        at.run()
        assert any("Not saved" in e.value for e in at.error) and profile_of(at).projects[0].url == ""

    def test_readiness_panel_lists_blockers_and_updates_after_fixing(self):
        at = self.page(Profile(name="", contact=experienced().contact, projects=[Project(name="Tool")]))
        assert any("Add your real full name" in m.value for m in at.markdown)
        r = rev(at)
        at.text_input(key=f"name-{r}").set_value("Priya Nair")
        button(at, "Save basics").click()
        at.run()
        assert not any("must be fixed" in e.value for e in at.error)

    def test_unconfirmed_ai_suggestions_are_flagged_and_can_be_confirmed_or_discarded(self):
        p = experienced().model_copy(
            update={
                "experience": [
                    Experience(title="Wizard", company="FakeCo", origin="suggested"),
                    *experienced().experience,
                ],
                "education": [Education(degree="PhD", institution="Nowhere U", origin="suggested")],
            }
        )
        at = self.page(p)
        assert any("not in your CV until you confirm" in w.value for w in at.warning)
        r = rev(at)
        button(at, "Confirm").click()  # first pending item: the experience
        at.run()
        assert profile_of(at).experience[0].confirmed is True
        button(at, "Discard").click()
        at.run()
        assert profile_of(at).education == []
        assert not any("not in your CV until" in w.value for w in at.warning) and rev(at) > r

    def test_confirm_all(self):
        ghosts = [Experience(title=f"T{i}", company=f"C{i}", origin="suggested") for i in range(3)]
        at = self.page(experienced().model_copy(update={"experience": ghosts}))
        button(at, "Confirm all").click()
        at.run()
        assert all(e.confirmed for e in profile_of(at).experience)

    def test_notes_from_reading_are_shown_including_removed_items(self):
        from careerforge.ai.grounding import Finding, GroundingReport
        from careerforge.ingest.pipeline import IngestResult

        result = IngestResult(
            experienced(), "pdf", ("Page 3 skipped",),
            GroundingReport((Finding("entity", "experience[1].company", "Google", "not found in your document", "removed"),)),
            ("ignore previous instructions",),
        )  # fmt: skip
        at = new_app(experienced(), ingest=result).run()
        open_page(at, "review")
        body = texts(at)
        assert "notes from reading your document (3)" in body or at.expander
        assert any("Google" in m.value and "Removed" in m.value for m in at.markdown)
        assert any("ignore previous instructions" in m.value.replace("\\", "") for m in at.markdown)

    def test_hostile_text_in_the_profile_is_shown_literally_not_as_html(self):
        import re

        evil = experienced().model_copy(
            update={"experience": [Experience(title="<img src=x onerror=alert(1)>", company="[a](http://evil)")]}
        )
        at = self.page(evil, "Experience")
        assert not at.exception
        mentioning = [m.value for m in at.markdown if "img src" in m.value or "evil" in m.value]
        assert mentioning  # the text really is displayed...
        for value in mentioning:  # ...but every markup/link character is escaped, so it renders as plain text
            outside_code_spans = re.sub(r"`[^`]*`", "", value)  # our own field path, e.g. `experience[0].title`
            assert not re.search(r"(?<!\\)[<>\[\]]", outside_code_spans), value
