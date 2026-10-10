"""Letters & interviews: a verified cover letter, interview preparation, and outreach drafts."""

from __future__ import annotations

import streamlit as st

from careerforge.ats.jd import parse_job_description
from careerforge.outreach import (
    Moment,
    attachment_name,
    build_emails,
    build_moment_emails,
    linkedin_boolean,
    linkedin_people_search,
    lint_email,
)
from careerforge.render.cv import PdfEngineUnavailable
from careerforge.render.letter import (
    LetterNotReady,
    render_letter_docx,
    render_letter_pdf,
    render_letter_txt,
    with_body,
)
from careerforge.render.options import DEFAULT_ACCENT, TEMPLATES, RenderOptions
from careerforge.ui import state
from careerforge.ui.errors import explain
from careerforge.ui.pages.match import job_input, report_for
from careerforge.ui.text import md_escape
from careerforge.ui.widgets import download, safe_file_stem
from careerforge.writing.basic_letter import build_basic_letter
from careerforge.writing.cover_letter import write_cover_letter
from careerforge.writing.interview import gap_questions, prepare_interview
from careerforge.writing.letter_format import LetterDetails
from careerforge.writing.letter_lint import lint_letter

VIEWS = ("Cover letter", "Interview prep", "Outreach emails")
LETTER, INTERVIEW = "letter_draft", "interview_prep"
DATE_STYLES = {"US: October 10, 2026": "us", "UK: 10 October 2026": "uk", "ISO: 2026-10-10": "iso"}
TONES = {"Standard": "standard", "Concise (shorter, direct)": "concise", "Warm (friendlier)": "warm"}
LETTER_TEMPLATES = [k for k, t in TEMPLATES.items() if t.columns == 1]
CHECK_ICON = {"fix": ":material/error:", "improve": ":material/warning:", "tip": ":material/lightbulb:"}


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


def _letter_details(company: str, role: str) -> LetterDetails:
    with st.expander("Details that make it a proper business letter", expanded=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Hiring manager's name (optional)", key="lt-name", placeholder="e.g. Ms. Rao")
        title = c2.text_input("Their job title (optional)", key="lt-title", placeholder="e.g. Head of Engineering")
        c3, c4 = st.columns(2)
        city = c3.text_input("Company city (optional)", key="lt-city")
        ref = c4.text_input("Job reference number (optional)", key="lt-ref", help="Shown in the subject line.")
        source = st.text_input(
            "Where you found the job (optional)", key="lt-source", placeholder="e.g. LinkedIn, or a referral from Asha"
        )
        availability = st.text_input(
            "Your availability (optional)", key="lt-avail", placeholder="e.g. I can start on 1 November"
        )
        hook = st.text_input(
            "A real reason you want this company (optional, one sentence, in your own words)", key="lt-hook"
        )
        c5, c6 = st.columns(2)
        date_style = c5.selectbox("Date format", list(DATE_STYLES), key="lt-date")
        tone = c6.selectbox("Tone", list(TONES), key="lt-tone")
        st.caption(
            "No name? The letter opens with “Dear Hiring Manager,”. Use a name only if you know it: "
            "it is never guessed."
        )
    return LetterDetails(
        company=company,
        role=role,
        recipient_name=name,
        recipient_title=title,
        company_city=city,
        job_ref=ref,
        source=source,
        availability=availability,
        hook=hook,
        date_style=DATE_STYLES[date_style],
        tone=TONES[tone],
    )


def _lint_panel(checks) -> None:
    failed = [c for c in checks if not c.passed]
    if not failed:
        st.success("This letter follows every convention checked below.", icon=":material/check_circle:")
    else:
        st.warning(f"{len(failed)} suggestion(s) to improve this letter:", icon=":material/warning:")
    with st.expander("What was checked", expanded=bool(failed)):
        for c in checks:
            if c.passed:
                st.markdown(f":material/check: {md_escape(c.label)}")
            else:
                st.markdown(f"{CHECK_ICON[c.severity]} **{md_escape(c.label)}**. {md_escape(c.detail)}")
        st.caption(
            "These are widely repeated conventions from career-advice sources (one page, 250-400 words, 3-5 short "
            "paragraphs, a named company and role, one measurable example). They are not a guarantee that any "
            "employer or ATS will accept the letter. Details: docs/STANDARDS.md."
        )


def _letter_options() -> RenderOptions | None:
    c1, c2, c3 = st.columns(3)
    template = c1.selectbox("Style", LETTER_TEMPLATES, format_func=lambda k: TEMPLATES[k].label, key="lt-template")
    accent = c2.color_picker("Accent colour", DEFAULT_ACCENT, key="lt-accent")
    paper = c3.selectbox("Paper", ["A4", "Letter"], key="lt-paper")
    try:
        return RenderOptions(template=template, accent=accent, paper=paper)
    except ValueError as exc:
        st.error(f"Appearance: {exc}", icon=":material/error:")
        return None


def _letter_downloads(profile, letter) -> None:
    options = _letter_options()
    if options is None:
        return
    stem = safe_file_stem(profile.name)
    try:
        txt = render_letter_txt(letter)
        docx_bytes = render_letter_docx(letter, options)
    except LetterNotReady as exc:
        st.error(str(exc), icon=":material/error:")
        return
    pdf = None
    try:
        pdf = render_letter_pdf(letter, options)
    except PdfEngineUnavailable as exc:
        st.warning(str(exc), icon=":material/warning:")
    if pdf is not None:
        if pdf.pages == 1:
            st.success("The PDF is one page.", icon=":material/check_circle:")
        for warning in pdf.warnings:
            st.warning(warning, icon=":material/warning:")
    c1, c2, c3 = st.columns(3)
    with c1:
        if pdf is not None:
            download("PDF", pdf.data, f"{stem}_cover_letter.pdf", "application/pdf", key="dl-letter-pdf", primary=True)
    with c2:
        download(
            "Word (.docx)",
            docx_bytes,
            f"{stem}_cover_letter.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="dl-letter-docx",
        )
    with c3:
        download("Text", txt, f"{stem}_cover_letter.txt", "text/plain", key="dl-letter-txt")
    st.caption(
        f"Attach your CV as **{attachment_name(profile)}**. Send the letter as a PDF unless the employer asks "
        "for another format."
    )


def _letter(profile, job: str, company: str, role: str) -> None:
    st.write(
        "A one-page business letter: your contact block, date, the recipient, a subject line, a greeting and a "
        "sign-off are laid out by code. Only the body is written, and every sentence comes from your own CV."
    )
    if not job.strip():
        st.info("Paste a job posting above first.")
        return
    details = _letter_details(company, role)
    ai = state.ai_configured()
    mode = st.radio(
        "How should the body be written?",
        ["AI-written (checked against your CV)", "Basic (no AI: your own bullets, arranged)"],
        index=0 if ai else 1,
        key="lt-mode",
    )
    use_ai = mode.startswith("AI")
    if use_ai and not ai:
        st.info("AI is not set up. Add a free key in **Settings**, or choose Basic.", icon=":material/info:")
    if st.button("Create my cover letter", type="primary", key="letter-go", disabled=use_ai and not ai):
        try:
            with st.spinner("Writing..."):
                if use_ai:
                    client = state.charge_ai()
                    draft = write_cover_letter(client, profile.exportable(), job, details=details)
                else:
                    draft = build_basic_letter(profile.exportable(), job, details=details)
        except Exception as exc:  # noqa: BLE001
            st.error(explain(exc), icon=":material/error:")
            return
        st.session_state[LETTER] = draft
    draft = st.session_state.get(LETTER)
    if draft is None:
        return
    if draft.verified:
        st.success(
            "Checked: every number, name and skill comes from your CV, the posting or the details you typed.",
            icon=":material/check_circle:",
        )
    else:
        st.warning("Not fully verified. Fix these before sending:", icon=":material/warning:")
        for issue in draft.issues:
            st.markdown(f"- {md_escape(issue)}")
    if draft.letter.subject:
        st.markdown(f"**{md_escape(draft.letter.subject)}**")
    edited = st.text_area(
        "Letter body (edit freely; leave a blank line between paragraphs)",
        draft.letter.body,
        height=360,
        key=f"letter-text-{hash(draft.text)}",
    )
    letter = with_body(draft.letter, edited)
    _lint_panel(lint_letter(letter, profile.exportable(), job, company=details.company, role=details.role))
    with st.expander("Preview the whole letter"):
        st.code(letter.text(), language=None, wrap_lines=True)
    _letter_downloads(profile, letter)


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
            with st.spinner("Preparing..."):
                client = state.charge_ai()
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


EMAIL_TITLES = {
    "cold_email": "Cold email to a recruiter or hiring manager",
    "follow_up_1": "Follow-up after a week",
    "follow_up_2": "Second follow-up (two weeks)",
    "thank_you": "Thank-you after an interview",
    "linkedin_note": "LinkedIn connection note (under 200 characters)",
    "referral_request": "Ask a contact for a referral",
    "recruiter_reply": "Reply to a recruiter who contacted you",
    "interview_confirmation": "Confirm an interview",
    "offer_acknowledgement": "Acknowledge an offer",
    "decline": "Politely withdraw or decline",
    "after_rejection": "Reply to a rejection",
    "linkedin_accepted": "Message after someone accepts your connection",
}


def _show_mails(mails) -> None:
    for key, mail in mails.items():
        with st.expander(EMAIL_TITLES.get(key, key)):
            if mail.subject:
                st.caption(f"Subject: {mail.subject}")
            st.code(mail.body, language=None, wrap_lines=True)
            failed = [c for c in lint_email(mail, key) if not c.passed]
            if failed:
                for c in failed:
                    st.caption(f":material/warning: {md_escape(c.label)}. {md_escape(c.detail)}")
            else:
                st.caption(":material/check: Short, one request, signed, no placeholders.")


def _outreach(profile, job: str, company: str, role: str) -> None:
    if not company:
        st.info("Enter the company name above to draft outreach.")
        return
    st.caption(
        "Drafts use only your CV and what you type here. Anything left empty is left out, never invented. "
        "Length limits are common advice (short subject, under 150 words, one request), not guarantees."
    )
    p = profile.exportable()
    start, replies, people = st.tabs(["Apply and follow up", "Replies for other moments", "Find the right people"])
    with start:
        c1, c2 = st.columns(2)
        recipient = c1.text_input("Recipient's name (optional)", key="out-recipient")
        topic = c2.text_input("Something from the interview to mention in a thank-you (optional)", key="out-topic")
        hook = st.text_input("A real reason you like this company (optional, one sentence)", key="out-hook")
        report = report_for(profile, job) if job.strip() else None
        mails = build_emails(p, company, role, report=report, recipient=recipient, hook=hook, interview_topic=topic)
        _show_mails(mails)
        st.caption(
            f"Attach your CV as **{attachment_name(p)}**: a recruiter sees the file name in their inbox. "
            "Send a PDF unless the posting asks for something else."
        )
    with replies:
        c1, c2 = st.columns(2)
        contact = c1.text_input("Person's name (optional)", key="mo-contact")
        how = c2.text_input(
            "How you know them (referral request)", key="mo-how", placeholder="We worked together on..."
        )
        c3, c4 = st.columns(2)
        when = c3.text_input(
            "Interview date and time (confirmation)", key="mo-when", placeholder="Tuesday 14 Oct, 3 pm"
        )
        avail = c4.text_input("Your availability (reply to a recruiter)", key="mo-avail")
        c5, c6 = st.columns(2)
        deadline = c5.text_input("Date you will answer an offer by", key="mo-deadline")
        notice = c6.text_input(
            "Notice period (reply to a recruiter)", key="mo-notice", placeholder="My notice is 30 days"
        )
        reason = st.text_input("Your reason, if you decline (optional, your words)", key="mo-reason")
        moment = Moment(
            contact=contact,
            how_known=how,
            when=when,
            availability=avail,
            deadline=deadline,
            notice=notice,
            reason=reason,
        )
        _show_mails(build_moment_emails(p, company, role, moment))
    with people:
        st.caption("Opens LinkedIn searches. Email addresses are never guessed.")
        for label, url in linkedin_people_search(company):
            st.link_button(label, url, icon=":material/open_in_new:")
        extra = st.text_input("Add a city or team to narrow the search (optional)", key="bool-extra")
        st.markdown("**Boolean search**: paste into LinkedIn's search box, then choose *People*.")
        st.code(linkedin_boolean(company, keywords=extra), language=None, wrap_lines=True)
        st.caption(
            "Uses quotes, upper-case AND/OR and brackets, which LinkedIn's help documents. Not tested live here."
        )


def render() -> None:
    profile = state.require_profile()
    st.title("Letters & interviews")
    job = job_input()
    company, role = _company_fields(job)
    view = st.radio("What do you need?", VIEWS, horizontal=True, key="write-view")
    if view == "Cover letter":
        _letter(profile, job, company, role)
    elif view == "Interview prep":
        _interview(profile, job)
    else:
        _outreach(profile, job, company, role)


if __name__ == "__main__":
    render()
