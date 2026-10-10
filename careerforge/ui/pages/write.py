"""Letters & interviews: a verified cover letter, interview preparation, and outreach drafts."""

from __future__ import annotations

import streamlit as st

from careerforge.ats.jd import parse_job_description
from careerforge.outreach import build_emails, linkedin_people_search
from careerforge.ui import state
from careerforge.ui.errors import explain
from careerforge.ui.pages.match import job_input, report_for
from careerforge.ui.text import md_escape
from careerforge.ui.widgets import download, safe_file_stem
from careerforge.writing.cover_letter import write_cover_letter
from careerforge.writing.interview import gap_questions, prepare_interview

VIEWS = ("Cover letter", "Interview prep", "Outreach emails")
LETTER, INTERVIEW = "letter_draft", "interview_prep"


def _company_fields(job: str) -> tuple[str, str]:
    detected = parse_job_description(job).title if job.strip() else ""
    c1, c2 = st.columns(2)
    company = c1.text_input(
        "Company", value=state.company(), key="company-input", placeholder="e.g. Northwind Payments"
    )
    role = c2.text_input(
        "Role", value=state.job_title() or detected, key="role-input", placeholder="e.g. Backend Engineer"
    )
    st.session_state[state.COMPANY], st.session_state[state.JOB_TITLE] = company, role
    return company.strip(), role.strip()


def _letter(profile, job: str, company: str) -> None:
    st.write(
        "The AI writes only the body. The date, greeting and sign-off are added by code, and the letter is checked: "
        "numbers, employers or skills that are not in your CV are flagged."
    )
    if not job.strip():
        st.info("Paste a job posting above first.")
        return
    if not state.ai_configured():
        st.info("Cover letters need AI. Add a free key in **Settings**.", icon=":material/info:")
        return
    addressee = st.text_input("Addressed to", value="Hiring Manager", key="letter-to")
    if st.button("Write my cover letter", type="primary", key="letter-go"):
        try:
            client = state.charge_ai()
            with st.spinner("Writing..."):
                draft = write_cover_letter(
                    client, profile.exportable(), job, company=company, addressee=addressee or "Hiring Manager"
                )
        except Exception as exc:  # noqa: BLE001
            st.error(explain(exc), icon=":material/error:")
            return
        st.session_state[LETTER] = draft
    draft = st.session_state.get(LETTER)
    if draft is None:
        return
    if draft.verified:
        st.success(
            "Checked: every number, name and skill in the letter comes from your CV or the posting.",
            icon=":material/check_circle:",
        )
    else:
        st.warning("Not fully verified. Fix these before sending:", icon=":material/warning:")
        for issue in draft.issues:
            st.markdown(f"- {md_escape(issue)}")
    edited = st.text_area("Your letter (edit freely)", draft.text, height=420, key=f"letter-text-{hash(draft.text)}")
    download(
        "Download as text", edited, f"{safe_file_stem(profile.name)}_cover_letter.txt", "text/plain", key="dl-letter"
    )


def _interview(profile, job: str) -> None:
    if not job.strip():
        st.info("Paste a job posting above first.")
        return
    report = report_for(profile, job)
    gaps = gap_questions(report)
    if gaps:
        st.subheader("Questions about gaps in your CV", anchor=False)
        st.caption("Generated without AI from required skills your CV does not show.")
        for q in gaps:
            st.markdown(f"- **{md_escape(q.question)}**  \n  {md_escape(q.tips)}")
    if not state.ai_configured():
        st.info(
            "Add a free key in **Settings** to also get questions about your own experience.", icon=":material/info:"
        )
        return
    if st.button("Prepare my interview questions", type="primary", key="interview-go"):
        try:
            client = state.charge_ai()
            with st.spinner("Preparing..."):
                prep = prepare_interview(client, profile.exportable(), job, report)
        except Exception as exc:  # noqa: BLE001
            st.error(explain(exc), icon=":material/error:")
            return
        st.session_state[INTERVIEW] = prep
    prep = st.session_state.get(INTERVIEW)
    if prep is None:
        return
    st.subheader("Likely questions", anchor=False)
    for q in (q for q in prep.questions if q.category != "gap"):
        with st.expander(f"{q.category.title()}: {q.question}"):
            st.markdown(f"**Why they ask:** {md_escape(q.why_asked)}")
            if q.cv_evidence:
                st.markdown(f"**From your CV:** “{md_escape(q.cv_evidence)}”")
            else:
                st.markdown("**From your CV:** no direct example. Think of a real one before the interview.")
            if q.tips:
                st.markdown(f"**Tip:** {md_escape(q.tips)}")
    if prep.dropped or prep.unverified_evidence:
        st.caption(
            f"{prep.dropped} suggestion(s) and {prep.unverified_evidence} quote(s) were removed "
            "because they could not be verified."
        )


def _outreach(profile, job: str, company: str, role: str) -> None:
    if not company:
        st.info("Enter the company name above to draft outreach.")
        return
    c1, c2 = st.columns(2)
    recipient = c1.text_input("Recipient's name (optional)", key="out-recipient")
    topic = c2.text_input("Something from the interview to mention in a thank-you (optional)", key="out-topic")
    hook = st.text_input("A real reason you like this company (optional, one sentence)", key="out-hook")
    report = report_for(profile, job) if job.strip() else None
    emails = build_emails(
        profile.exportable(), company, role, report=report, recipient=recipient, hook=hook, interview_topic=topic
    )
    titles = {
        "cold_email": "Cold email",
        "follow_up_1": "Follow-up after a week",
        "follow_up_2": "Second follow-up",
        "thank_you": "Thank-you after an interview",
        "linkedin_note": "LinkedIn connection note",
    }
    for key, mail in emails.items():
        with st.expander(titles.get(key, key)):
            st.caption(f"Subject: {mail.subject}")
            st.code(mail.body, language=None, wrap_lines=True)
    st.subheader("Find the right people", anchor=False)
    st.caption("Opens LinkedIn searches. Email addresses are never guessed.")
    for label, url in linkedin_people_search(company):
        st.link_button(label, url, icon=":material/open_in_new:")


def render() -> None:
    profile = state.require_profile()
    st.title("Letters & interviews")
    job = job_input()
    company, role = _company_fields(job)
    view = st.radio("What do you need?", VIEWS, horizontal=True, key="write-view")
    if view == "Cover letter":
        _letter(profile, job, company)
    elif view == "Interview prep":
        _interview(profile, job)
    else:
        _outreach(profile, job, company, role)


if __name__ == "__main__":
    render()
