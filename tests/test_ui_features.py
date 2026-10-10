"""ATS check, tailoring, insights, letters, jobs, tracker, settings and the export page."""

from datetime import date, timedelta

import pytest
from helpers import scripted_client
from test_render_cv import experienced, fresher
from test_writing import GOOD_PARAS
from ui_helpers import button, find, new_app, open_page, profile_of, texts

from careerforge.ai.errors import AIAuthError, AIQuotaExhausted
from careerforge.jobs import Job
from careerforge.models import Contact, Profile
from careerforge.tracker import Tracker

pytestmark = pytest.mark.usefixtures("ui_env")

JD = (
    "Senior Backend Engineer\nRequirements: 5+ years of Python or Go; Kafka, PostgreSQL, Redis, Kubernetes, Docker, "
    "AWS, REST API design, CI/CD; mentoring engineers. Nice to have: Terraform, gRPC."
)
B1 = "Cut p95 API latency from 480ms to 190ms by introducing Redis caching."


def set_job(at, text=JD):
    at.text_area(key="job-input").set_value(text).run()
    return at


def page(name, profile=None, **session):
    at = new_app(experienced() if profile is None else profile, **session).run()
    return open_page(at, name)


# ── ATS check ───────────────────────────────────────────────────────────────


class TestAtsCheck:
    def test_requires_a_profile(self):
        at = open_page(new_app().run(), "match")
        assert any("Start by adding" in i.value for i in at.info)

    def test_without_a_posting_it_is_a_general_readiness_check(self):
        at = page("match")
        assert not at.exception and "general ats-readiness check" in texts(at)
        assert any(m.label == "ATS-readiness score" for m in at.metric)

    def test_with_a_posting_it_scores_the_match_and_lists_matched_and_missing(self):
        at = set_job(page("match"))
        assert not at.exception
        score = next(m for m in at.metric if m.label == "ATS match score")
        assert 0 < int(score.value.split("/")[0]) <= 100
        matched, missing = texts(at).split("\nmissing\n", 1)
        assert "kafka" in matched and "terraform" not in matched  # a preferred skill the CV lacks is not "matched"
        assert "rest api" in missing and "terraform" in missing
        assert any("ATS" in c.value for c in at.caption)  # the "not an official ATS" disclaimer is shown
        assert at.session_state["job_text"] == JD  # kept for the other pages

    def test_posting_title_is_detected(self):
        assert "detected job title" in texts(set_job(page("match")))

    def test_posting_text_with_markdown_and_html_is_shown_safely(self):
        at = set_job(page("match"), "Dev\nRequirements: <script>alert(1)</script> Python, [click](http://evil.example)")
        assert not at.exception
        for m in at.markdown:
            assert "<script" not in m.value.replace("\\<script", "")

    def test_section_tips_view(self):
        at = set_job(page("match"))
        at.radio(key="ats-view").set_value("Section tips").run()
        assert not at.exception and at.markdown

    def test_compare_postings_ranks_them(self):
        at = page("match")
        at.radio(key="ats-view").set_value("Compare postings").run()
        at.text_input(key="cmp-name-1").set_value("Backend")
        at.text_area(key="cmp-text-1").set_value(JD)
        at.text_input(key="cmp-name-2").set_value("Chef")
        at.text_area(key="cmp-text-2").set_value("Head Chef\nRequirements: knife skills, menu planning, food safety")
        at.run()
        assert not at.exception and len(at.dataframe) == 1
        frame = at.dataframe[0].value
        assert list(frame["Posting"]) == ["Backend", "Chef"] and frame["Score"][0] > frame["Score"][1]

    def test_compare_needs_two_postings(self):
        at = page("match")
        at.radio(key="ats-view").set_value("Compare postings").run()
        at.text_area(key="cmp-text-1").set_value(JD).run()
        assert "add at least two" in texts(at) and not at.dataframe

    def test_uploading_the_pdf_you_will_send_adds_a_measured_parse_score(self):
        from careerforge.render.cv import render_cv_pdf

        at = page("match")
        at.file_uploader(key="ats-pdf").upload("cv.pdf", render_cv_pdf(experienced()).data, "application/pdf").run()
        assert not at.exception and "pdf readability" in texts(at)
        assert "not measured" not in texts(at).split("pdf readability")[1][:60]

    def test_smart_matches_need_ai_and_a_posting(self):
        at = page("match")
        at.radio(key="ats-view").set_value("Smart matches (AI)").run()
        assert "paste a job posting first" in texts(at)
        set_job(at)
        assert "needs ai" in texts(at)

    def test_smart_matches_only_show_quotes_that_exist_in_the_cv(self, ui_env):
        reply = {"matches": [
            {"requirement": "REST API", "cv_quote": "Built real-time tracking APIs in Flask serving 50k requests/min.", "why": "Flask APIs"},
            {"requirement": "gRPC", "cv_quote": "Designed gRPC services at Google", "why": "invented"},
        ]}  # fmt: skip
        client, _ = scripted_client(reply)
        ui_env.ai(client)
        at = page("match")
        set_job(at)
        at.radio(key="ats-view").set_value("Smart matches (AI)").run()
        button(at, "Find smart matches").click()
        at.run()
        body = texts(at)
        assert "rest api" in body and "tracking apis in flask" in body and "grpc" not in body
        assert "1 suggestion(s) were discarded" in body

    def test_ai_failure_on_smart_matches_is_a_sentence_and_changes_nothing(self, ui_env):
        client, _ = scripted_client(*[AIAuthError("bad key")] * 3)
        ui_env.ai(client)
        at = page("match")
        set_job(at)
        at.radio(key="ats-view").set_value("Smart matches (AI)").run()
        button(at, "Find smart matches").click()
        at.run()
        assert not at.exception and "rejected the api key" in at.error[0].value.lower()


# ── Tailor ──────────────────────────────────────────────────────────────────


class TestTailor:
    def test_needs_ai(self):
        at = set_job(page("tailor"))
        assert "needs ai" in texts(at) and not [b for b in at.button if "Suggest" in b.label]

    def test_needs_a_posting(self, ui_env):
        client, _ = scripted_client()
        ui_env.ai(client)
        assert "paste a job posting" in texts(page("tailor"))

    def run_tailor(self, ui_env, reply):
        client, provider = scripted_client(reply)
        ui_env.ai(client)
        at = page("tailor")
        set_job(at)
        button(at, "Suggest improvements").click()
        at.run()
        return at, provider

    def test_safe_rewording_applied_unsafe_rejected_and_nothing_changes_the_main_profile(self, ui_env):
        reply = {"bullets": [
            {"id": "1", "text": "Reduced p95 API latency from 480ms to 190ms by introducing Redis caching."},
            {"id": "0", "text": "Designed an event-driven settlement service handling 9M transactions/day using Kafka and PostgreSQL."},
        ]}  # fmt: skip
        at, _ = self.run_tailor(ui_env, reply)
        assert not at.exception
        body = texts(at)
        assert "applied automatically" in body and "reduced p95" in body
        assert any("1 rejected suggestion" in e.label for e in at.expander)
        before = profile_of(at).model_dump()
        button(at, "Use this tailored version").click()
        at.run()
        assert profile_of(at).model_dump() == before  # master profile untouched
        tailored = at.session_state["tailored"]
        assert tailored.experience[0].bullets[1].startswith("Reduced p95")
        assert tailored.experience[0].bullets[0] == experienced().experience[0].bullets[0]  # rejected one never applied

    def test_new_wording_from_the_posting_waits_for_the_users_decision(self, ui_env):
        reply = {"bullets": [{"id": "3", "text": "Built REST API endpoints in Flask serving 50k requests/min."}]}
        at, _ = self.run_tailor(ui_env, reply)
        assert "needs your decision" in texts(at) and "true for you" in texts(at)
        button(at, "Use this tailored version").click()  # without ticking the box
        at.run()
        assert at.session_state["tailored"].experience[1].bullets[0] == experienced().experience[1].bullets[0]

    def test_accepting_a_held_rewording_applies_only_that_one(self, ui_env):
        reply = {"bullets": [{"id": "3", "text": "Built REST API endpoints in Flask serving 50k requests/min."}]}
        at, _ = self.run_tailor(ui_env, reply)
        at.checkbox(key="tailor-accept-0").set_value(True).run()
        button(at, "Use this tailored version").click()
        at.run()
        assert at.session_state["tailored"].experience[1].bullets[0].startswith("Built REST API")

    def test_results_are_discarded_when_the_profile_changes(self, ui_env):
        at, _ = self.run_tailor(ui_env, {"bullets": [{"id": "1", "text": B1.replace("Cut", "Reduced")}]})
        assert "applied automatically" in texts(at)
        at.session_state["profile"] = experienced().model_copy(update={"headline": "Changed"})
        at.run()
        assert "applied automatically" not in texts(at)

    def test_quota_exhaustion_message(self, ui_env):
        client, _ = scripted_client(*[AIQuotaExhausted("daily")] * 3)
        ui_env.ai(client)
        at = page("tailor")
        set_job(at)
        button(at, "Suggest improvements").click()
        at.run()
        assert "out of quota" in at.error[0].value


# ── Insights ────────────────────────────────────────────────────────────────


class TestInsights:
    def test_timeline_total_and_gaps(self):
        at = page("insights")
        assert not at.exception and any("Total experience" in m.label for m in at.metric)
        assert len(at.dataframe[0].value) == 2

    def test_timeline_without_dates_asks_for_them(self):
        at = page("insights", fresher())
        assert "add dated experience" in texts(at)

    def test_skill_coverage_chart_and_comparison_with_a_posting(self):
        at = page("insights")
        at.radio(key="insights-view").set_value("Skill coverage").run()
        assert not at.exception and at.get("vega_lite_chart")
        set_job(at)
        assert "Required by posting" in list(at.dataframe[-1].value.columns)

    def test_keyword_heat_and_roadmap_need_a_posting_then_work(self):
        at = page("insights")
        at.radio(key="insights-view").set_value("Keyword heat").run()
        assert "paste a job posting" in texts(at)
        set_job(at)
        assert not at.exception and "Keyword" in list(at.dataframe[-1].value.columns)
        at.radio(key="insights-view").set_value("Learning roadmap").run()
        assert any("REST API" in e.label for e in at.expander) and "do not add a skill" in texts(at).replace(
            "only add", "do not add"
        )


# ── Letters, interview prep, outreach ───────────────────────────────────────


class TestWrite:
    def test_outreach_needs_only_a_company_and_never_guesses_emails(self):
        at = page("write")
        at.radio(key="write-view").set_value("Outreach emails").run()
        assert "enter the company name" in texts(at)
        at.text_input(key="company-input").set_value("Northwind Payments").run()
        at.text_input(key="role-input").set_value("Backend Engineer").run()
        assert not at.exception
        codes = [c.value for c in at.code]
        # 5 apply-and-follow-up drafts, 7 replies for other moments, 1 Boolean search string
        assert len(codes) == 13 and all("Priya Nair" in c or len(c) < 300 for c in codes)
        assert not any("@northwind" in c or "hr@" in c for c in codes)
        assert "[" not in "".join(codes[:12])  # no placeholders in any draft
        assert len(at.get("link_button")) == 4  # LinkedIn people searches
        assert codes[-1].startswith('("Technical Recruiter" OR') and codes[-1].endswith('AND "Northwind Payments"')

    def test_outreach_drafts_show_their_own_checks_and_the_attachment_name(self):
        at = page("write")
        at.radio(key="write-view").set_value("Outreach emails").run()
        at.text_input(key="company-input").set_value("Northwind Payments").run()
        body = texts(at)
        assert "priya_nair_cv.pdf" in body and "short, one request, signed, no placeholders" in body

    def test_outreach_options_flow_into_the_drafts(self):
        at = page("write")
        at.radio(key="write-view").set_value("Outreach emails").run()
        at.text_input(key="company-input").set_value("Northwind").run()
        at.text_input(key="out-recipient").set_value("Ms. Rao").run()
        at.text_input(key="out-topic").set_value("your event-driven design").run()
        joined = "\n".join(c.value for c in at.code)
        assert "Ms. Rao" in joined and "your event-driven design" in joined

    def test_moment_replies_use_only_what_the_user_typed(self):
        at = page("write")
        at.radio(key="write-view").set_value("Outreach emails").run()
        at.text_input(key="company-input").set_value("Northwind").run()
        at.text_input(key="mo-when").set_value("Tuesday 14 October, 3 pm IST").run()
        at.text_input(key="mo-reason").set_value("I accepted another offer").run()
        joined = "\n".join(c.value for c in at.code)
        assert "Tuesday 14 October, 3 pm IST" in joined and "I accepted another offer" in joined
        assert "boolean search" in texts(at)

    def test_boolean_search_takes_extra_keywords(self):
        at = page("write")
        at.radio(key="write-view").set_value("Outreach emails").run()
        at.text_input(key="company-input").set_value("Northwind").run()
        at.text_input(key="bool-extra").set_value("Pune").run()
        assert at.code[-1].value.endswith('AND "Northwind" AND "Pune"')

    def test_basic_cover_letter_needs_no_ai(self):
        at = page("write")
        assert "paste a job posting" in texts(at)
        set_job(at)
        assert at.radio(key="lt-mode").value.startswith("Basic")  # no AI key: the no-AI mode is the default
        button(at, "Create my cover letter").click()
        at.run()
        assert not at.exception
        draft = at.session_state["letter_draft"]
        assert draft.letter.salutation == "Dear Hiring Manager," and draft.verified
        assert "Priya Nair" in draft.text and "Enclosure: Curriculum Vitae" in draft.text

    def test_choosing_ai_without_a_key_says_so_and_disables_the_button(self):
        at = set_job(page("write"))
        at.radio(key="lt-mode").set_value("AI-written (checked against your CV)").run()
        assert "ai is not set up" in texts(at) and button(at, "Create my cover letter").disabled

    def test_letter_details_shape_the_business_letter(self):
        at = set_job(page("write"))
        at.text_input(key="company-input").set_value("Northwind Payments").run()
        at.text_input(key="lt-name").set_value("Ms. Rao").run()
        at.text_input(key="lt-title").set_value("Head of Engineering").run()
        at.text_input(key="lt-city").set_value("Pune").run()
        at.text_input(key="lt-ref").set_value("ENG-2041").run()
        at.text_input(key="lt-source").set_value("LinkedIn").run()
        at.text_input(key="lt-avail").set_value("I can start on 1 November").run()
        at.selectbox(key="lt-date").set_value("UK: 10 October 2026").run()
        button(at, "Create my cover letter").click()
        at.run()
        assert not at.exception
        text = at.session_state["letter_draft"].text
        assert "Dear Ms. Rao," in text and "Yours sincerely," in text and "(Ref: ENG-2041)" in text
        assert "Head of Engineering" in text and "Pune" in text and "through LinkedIn" in text
        assert "I can start on 1 November." in text

    def test_a_bad_recipient_name_is_a_message_not_a_crash(self):
        at = set_job(page("write"))
        at.text_input(key="lt-name").set_value("<script>alert(1)</script>").run()
        button(at, "Create my cover letter").click()
        at.run()
        assert not at.exception and at.error and "letter_draft" not in at.session_state

    def test_the_lint_report_and_downloads_follow_the_edited_body(self):
        at = set_job(page("write"))
        button(at, "Create my cover letter").click()
        at.run()
        assert "What was checked" in [e.label for e in at.expander]
        labels = {b.label for b in at.get("download_button")}
        assert {"PDF", "Word (.docx)", "Text"} <= labels
        area = next(a for a in at.text_area if a.label.startswith("Letter body"))
        area.set_value("Too short.\n\nVery short.").run()
        assert not at.exception and "suggestion(s) to improve this letter" in texts(at)
        assert "words" in texts(at)

    def test_a_letter_with_placeholders_cannot_be_downloaded(self):
        at = set_job(page("write"))
        button(at, "Create my cover letter").click()
        at.run()
        area = next(a for a in at.text_area if a.label.startswith("Letter body"))
        area.set_value("At [Company] I did x.\n\nSecond.\n\nThird.").run()
        assert not at.exception and any("placeholder" in e.value for e in at.error)
        assert not [b for b in at.get("download_button") if b.label == "PDF"]

    def test_cover_letter_verified(self, ui_env):
        client, _ = scripted_client({"paragraphs": GOOD_PARAS})
        ui_env.ai(client)
        at = page("write")
        set_job(at)
        at.text_input(key="company-input").set_value("Northwind Payments").run()
        assert at.radio(key="lt-mode").value.startswith("AI")
        button(at, "Create my cover letter").click()
        at.run()
        assert not at.exception and "Checked: every number" in " ".join(s.value for s in at.success)
        body = next(a for a in at.text_area if a.label.startswith("Letter body")).value
        assert body.split("\n\n")[0] == GOOD_PARAS[0]
        draft = at.session_state["letter_draft"]
        assert draft.text.startswith("Priya Nair") and draft.text.rstrip().endswith("Enclosure: Curriculum Vitae")
        assert "+91 98765 43210" in draft.text.split("\n\n")[0]

    def test_cover_letter_with_invented_claims_is_flagged_not_called_ready(self, ui_env):
        bad = [GOOD_PARAS[0], GOOD_PARAS[1] + " I also led 40 engineers at Google.", GOOD_PARAS[2], GOOD_PARAS[3]]
        client, _ = scripted_client({"paragraphs": bad}, {"paragraphs": bad})
        ui_env.ai(client)
        at = page("write")
        set_job(at)
        button(at, "Create my cover letter").click()
        at.run()
        assert any("Not fully verified" in w.value for w in at.warning)
        assert not any("Checked: every number" in s.value for s in at.success)
        assert "google" in texts(at)  # the issue names what is wrong

    def test_interview_gap_questions_work_without_ai(self):
        at = page("write")
        set_job(at)
        at.radio(key="write-view").set_value("Interview prep").run()
        assert not at.exception and "questions about gaps" in texts(at) and "rest api" in texts(at)
        assert "add a free key" in texts(at)

    def test_interview_ai_questions_with_verified_evidence(self, ui_env):
        reply = {"questions": [
            {"category": "technical", "question": "How did you reduce API latency at Finlytics?", "why_asked": "Performance", "cv_evidence": B1, "tips": "Use STAR."},
            {"category": "behavioural", "question": "Tell me about mentoring engineers.", "why_asked": "Leadership", "cv_evidence": "Mentored 40 interns at Google", "tips": ""},
        ]}  # fmt: skip
        client, _ = scripted_client(reply)
        ui_env.ai(client)
        at = page("write")
        set_job(at)
        at.radio(key="write-view").set_value("Interview prep").run()
        button(at, "Prepare my interview questions").click()
        at.run()
        assert (
            not at.exception
            and len([e for e in at.expander if "Technical" in e.label or "Behavioural" in e.label]) == 2
        )
        body = " ".join(m.value for m in at.markdown)
        assert "Cut p95 API latency" in body and "no direct example" in body and "Google" not in body
        assert "1 quote(s) were removed" in texts(at)


# ── Jobs and tracker ────────────────────────────────────────────────────────


class FakeProvider:
    name = "Remotive"

    def __init__(self, *a, **k):
        pass

    def search(self, query, limit):
        return [
            Job("Senior Python Engineer", "Acme", "Remote", "We need Python, Kafka and Docker.", "https://acme.example/jobs/1", "Remotive"),
            Job("Pastry Chef", "Bakery", "Paris", "Bake bread.", "javascript:alert(1)", "Remotive"),
        ]  # fmt: skip


class TestJobs:
    @pytest.fixture(autouse=True)
    def fake_boards(self, monkeypatch):
        import careerforge.jobs as jobs

        jobs._cache.clear()
        monkeypatch.setattr(jobs, "RemotiveProvider", FakeProvider)
        monkeypatch.setattr(
            jobs,
            "JobicyProvider",
            lambda *a, **k: type(
                "J",
                (),
                {
                    "name": "Jobicy",
                    "search": lambda s, q, n: (_ for _ in ()).throw(jobs.ProviderError("Jobicy is down")),
                },
            )(),
        )

    def search(self):
        at = page("jobs")
        find(at.text_input, "Search").set_value("python backend").run()
        button(at, "Search").click()
        return at.run()

    def test_query_ideas_come_from_the_cv(self):
        at = page("jobs")
        assert not at.exception and "ideas from your cv" in texts(at)

    def test_results_are_ranked_and_one_failing_board_does_not_hide_the_others(self):
        at = self.search()
        body = texts(at)
        assert not at.exception and "senior python engineer" in body and "jobicy is down" in body
        assert body.index("senior python engineer") < body.index("pastry chef")  # better match first

    def test_unsafe_job_links_get_no_button(self):
        at = self.search()
        assert [b.proto.url for b in at.get("link_button")] == ["https://acme.example/jobs/1"]

    def test_check_my_cv_against_a_job_fills_the_posting_and_opens_the_ats_page(self):
        at = self.search()
        button(at, "Check my CV against it").click()
        at.run()
        assert at.title[0].value == "ATS check" and "Kafka" in at.session_state["job_text"]

    def test_add_to_tracker_records_the_score(self):
        at = self.search()
        button(at, "Add to tracker").click()
        at.run()
        (app,) = at.session_state["tracker"].applications
        assert (app.company, app.role, app.status) == (
            "Acme",
            "Senior Python Engineer",
            "saved",
        ) and app.ats_score is not None


class TestTracker:
    def tracker_page(self, tracker=None):
        at = new_app(experienced(), tracker=tracker or Tracker()).run()
        open_page(at, "jobs")
        at.radio(key="jobs-view").set_value("Application tracker").run()
        return at

    def test_add_validates_and_lists(self):
        at = self.tracker_page()
        button(at, "Add application").click()
        at.run()
        assert "enter the company and the role" in texts(at)
        at.text_input[0].set_value("Acme")
        at.text_input[1].set_value("Engineer")
        button(at, "Add application").click()
        at.run()
        assert [a.company for a in at.session_state["tracker"].applications] == ["Acme"]
        assert len(at.dataframe[0].value) == 1

    def test_bad_link_is_a_message_not_a_crash(self):
        at = self.tracker_page()
        at.text_input[0].set_value("Acme")
        at.text_input[1].set_value("Engineer")
        at.text_input[2].set_value("javascript:alert(1)")
        button(at, "Add application").click()
        at.run()
        assert not at.exception and at.error and not at.session_state["tracker"].applications

    def test_move_remove_and_event_history(self):
        t, app = Tracker().add("Acme", "Engineer")
        at = self.tracker_page(t)
        find(at.selectbox, "New status").set_value("applied").run()
        button(at, "Update status").click()
        at.run()
        moved = at.session_state["tracker"].get(app.id)
        assert moved.status == "applied" and moved.applied_on == date.today().isoformat() and len(moved.events) == 2
        button(at, "Remove").click()
        at.run()
        assert at.session_state["tracker"].applications == []

    def test_follow_ups_are_due_after_a_week_and_can_be_marked_sent(self):
        t, app = Tracker().add("Acme", "Engineer", status="applied", on=date.today() - timedelta(days=9))
        at = self.tracker_page(t)
        assert "follow-ups due" in texts(at) and "first follow-up" in texts(at)
        assert any("Acme" in c.value for c in at.code)
        button(at, "Mark as sent").click()
        at.run()
        assert at.session_state["tracker"].get(app.id).followups_sent == ["follow_up_1"]
        assert "first follow-up" not in texts(at)

    def test_close_out_is_advice_not_an_email(self):
        t, _ = Tracker().add("Acme", "Engineer", status="applied", on=date.today() - timedelta(days=30))
        at = self.tracker_page(t)
        assert "consider moving on" in texts(at)

    def test_tracker_travels_inside_the_saved_profile(self):
        from careerforge.tracker import load_file

        t, _ = Tracker().add("Acme", "Engineer")
        at = self.tracker_page(t)
        sidebar_download = at.sidebar.get("download_button")
        assert sidebar_download  # the save button exists
        # the exact file the button serves round-trips
        from careerforge.tracker import dump_file

        profile, tracker = load_file(dump_file(profile_of(at), at.session_state["tracker"]))
        assert profile.name == "Priya Nair" and tracker.applications[0].company == "Acme"


# ── Settings and about ──────────────────────────────────────────────────────


class TestSettings:
    def test_no_key_means_basic_mode(self):
        at = open_page(new_app().run(), "settings")
        assert not at.exception and "basic mode" in texts(at)

    def test_visitor_keys_are_session_only_and_remove_the_shared_limit(self, ui_env):
        at = open_page(new_app().run(), "settings")
        # the placeholder client is replaced when keys are set; here we only check the state transitions
        ui_env.ai(scripted_client()[0])
        find(at.text_input, "Gemini").set_value("my-secret-key-123456")
        button(at, "Use my keys").click()
        at.run()
        assert at.session_state["user_keys"] == {"GEMINI_API_KEY": "my-secret-key-123456"}
        assert "your own key" in texts(at)
        assert "my-secret-key-123456" not in texts(at) and "my-secret-key-123456" not in " ".join(
            m.value for m in at.markdown
        )
        button(at, "Stop using my keys").click()
        at.run()
        assert at.session_state["user_keys"] == {}

    def test_shared_key_shows_remaining_actions(self, ui_env):
        ui_env.ai(scripted_client()[0])
        ui_env.site(CAREERFORGE_SESSION_AI_LIMIT="7")
        at = open_page(new_app().run(), "settings")
        assert "7 ai actions left" in texts(at)

    def test_connection_test_success_and_failure(self, ui_env):
        client, _ = scripted_client("OK")
        ui_env.ai(client)
        at = open_page(new_app().run(), "settings")
        button(at, "Test the AI connection").click()
        at.run()
        assert any("Working. Answered by fake / m" in s.value for s in at.success)
        client2, _ = scripted_client(*[AIAuthError("nope")] * 3)
        ui_env.ai(client2)
        at = open_page(new_app().run(), "settings")
        button(at, "Test the AI connection").click()
        at.run()
        assert "rejected the api key" in at.error[0].value.lower()

    def test_models_in_use_are_listed(self, ui_env):
        ui_env.ai(scripted_client()[0])
        at = open_page(new_app().run(), "settings")
        assert any("Models in use" in e.label for e in at.expander)


def test_about_page_explains_the_score_and_limits():
    at = open_page(new_app().run(), "about")
    body = texts(at)
    assert not at.exception and "never invents experience" in body and "keywords" in body and "weight 40" in body
    assert at.warning  # the "not an official ATS" disclaimer


# ── Export page ─────────────────────────────────────────────────────────────


class TestExport:
    def test_requires_a_profile(self):
        assert any("Start by adding" in i.value for i in open_page(new_app().run(), "export").info)

    def test_not_ready_shows_blockers_a_draft_preview_and_no_downloads(self):
        at = page("export", experienced().model_copy(update={"contact": Contact(email="x@example.com")}))
        assert not at.exception and "must be fixed" in texts(at)
        assert not [b for b in at.get("download_button") if "pdf" in b.label.lower()]
        assert "draft preview" in at.get("iframe")[0].proto.srcdoc.lower()

    def test_ready_profile_builds_every_format_and_reports_the_pdf_parse(self):
        at = page("export")
        assert "ready to export" in texts(at)
        button(at, "Build my files").click()
        at.run()
        assert not at.exception
        signature, files = at.session_state["built_files"]
        assert files["pdf"].data[:5] == b"%PDF-" and files["docx"][:2] == b"PK" and "priya nair" in files["txt"].lower()
        assert files["pdf"].parse.score >= 95 and "ats parse check of this exact pdf" in texts(at)
        labels = {b.label for b in at.get("download_button")}
        assert {"PDF", "Word (.docx)", "Plain text", "HTML"} <= labels

    def test_changing_a_setting_invalidates_the_built_files(self):
        at = page("export")
        button(at, "Build my files").click()
        at.run()
        find(at.selectbox, "Template").set_value("executive").run()
        assert "build again" in texts(at) and not [b for b in at.get("download_button") if b.label == "PDF"]

    def test_every_template_option_renders_a_preview(self):
        at = page("export")
        for template in ("ats-classic", "ats-modern", "executive", "sidebar"):
            find(at.selectbox, "Template").set_value(template).run()
            assert not at.exception and "Priya Nair" in at.get("iframe")[0].proto.srcdoc
        assert any("not ATS-safe" in w.value or "simple ATS parsers" in w.value for w in at.warning)

    def test_unreadable_accent_is_explained(self):
        at = page("export")
        find(at.color_picker, "Accent").set_value("#ffff00").run()
        assert not at.exception and any("too light" in e.value for e in at.error)

    def test_section_selection_and_order_reach_the_preview(self):
        at = page("export")
        sections = find(at.multiselect, "Sections")
        sections.set_value(["skills", "experience"]).run()
        html = at.get("iframe")[0].proto.srcdoc
        assert html.index("Skills") < html.index("Work Experience") and "Certifications" not in html

    def test_tailored_version_can_be_chosen(self):
        tailored = experienced().model_copy(update={"headline": "Tailored Headline"})
        at = page("export", tailored=tailored)
        assert "Tailored Headline" not in at.get("iframe")[0].proto.srcdoc
        find(at.radio, "Which version").set_value("Tailored version").run()
        assert "Tailored Headline" in at.get("iframe")[0].proto.srcdoc

    def test_portfolio_tab_builds_zip_and_respects_privacy_defaults(self):
        at = page("export")
        at.radio(key="export-tab").set_value("Portfolio website").run()
        assert not at.exception
        html = at.get("iframe")[0].proto.srcdoc
        assert "Priya Nair" in html and "98765" not in html and "mailto:priya.nair@gmail.com" in html
        assert {"Download site (.zip with deploy guide)", "Download index.html only"} <= {
            b.label for b in at.get("download_button")
        }
        at.checkbox(key="pf-phone").set_value(True).run()
        assert "98765" in at.get("iframe")[0].proto.srcdoc

    def test_portfolio_theme_accent_and_hidden_sections(self):
        at = page("export")
        at.radio(key="export-tab").set_value("Portfolio website").run()
        at.radio(key="pf-theme").set_value("light").run()
        at.multiselect(key="pf-hide").set_value(["education", "contact"]).run()
        html = at.get("iframe")[0].proto.srcdoc
        assert "--bg: #ffffff" in html and 'id="education"' not in html and 'id="contact"' not in html

    def test_portfolio_bad_options_are_explained(self):
        at = page("export")
        at.radio(key="export-tab").set_value("Portfolio website").run()
        at.radio(key="pf-theme").set_value("light").run()
        at.checkbox(key="pf-use-accent").set_value(True).run()
        at.color_picker(key="pf-accent").set_value("#ffff00").run()  # yellow on white is unreadable
        assert not at.exception and any("hard to read" in e.value for e in at.error)
        at.checkbox(key="pf-use-accent").set_value(False).run()
        at.text_input(key="pf-url").set_value("javascript:alert(1)").run()
        assert any("Options" in e.value for e in at.error)

    def test_github_only_profile_can_publish_a_portfolio_but_not_a_cv(self):
        from careerforge.models import Project

        p = Profile(
            name="Sam Rivera", contact=Contact(github="github.com/sam"), projects=[Project(name="Tool", stars=3)]
        )
        at = page("export", p)
        assert "must be fixed" in texts(at)  # CV needs an email
        at.radio(key="export-tab").set_value("Portfolio website").run()
        assert not at.exception and "Sam Rivera" in at.get("iframe")[0].proto.srcdoc


# ── LinkedIn profile text (reverse mode) ────────────────────────────────────


class TestLinkedInPage:
    def test_requires_a_profile(self):
        assert any("Start by adding" in i.value for i in open_page(new_app().run(), "linkedin").info)

    def test_every_part_is_offered_with_character_counts(self):
        at = page("linkedin")
        assert not at.exception
        codes = [c.value for c in at.code]
        assert codes[0] == "Senior Backend Engineer | Python | Go | PostgreSQL"
        assert codes[1].startswith("Backend engineer with 7 years") and "Highlights:" in codes[1]
        body = texts(at)
        assert f"{len(codes[0])} of 220 characters" in body and f"{len(codes[1])} of 2600 characters" in body
        assert "pin these three as top skills" in body and "python, go, postgresql" in body

    def test_experience_education_and_certifications_are_listed(self):
        at = page("linkedin")
        labels = [e.label for e in at.expander]
        assert "Senior Backend Engineer, Finlytics Pvt Ltd" in labels and "NIT Calicut" in labels
        assert "aws certified developer - associate" in texts(at).replace("\\", "")  # shown escaped

    def test_hostile_text_is_shown_literally(self):
        evil = experienced().model_copy(update={"skills": ["Python", "<img src=x onerror=alert(1)>"]})
        at = page("linkedin", evil)
        assert not at.exception
        pinned = next(m.value for m in at.markdown if "Pin these three" in m.value)
        assert "\\<img" in pinned  # the markdown line is escaped; the code box shows raw text safely

    def test_unconfirmed_suggestions_are_not_offered(self):
        from careerforge.models import Experience

        ghost = Experience(title="Wizard", company="FakeCo", origin="suggested", bullets=["Conjured revenue"])
        at = page("linkedin", experienced().model_copy(update={"experience": [ghost, *experienced().experience]}))
        assert "FakeCo" not in texts(at) and "FakeCo" not in " ".join(c.value for c in at.code)
