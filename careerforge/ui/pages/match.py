"""ATS check: how well does this CV match a job posting (or, with no posting, how ATS-ready is it)?"""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from careerforge.analytics import section_tips
from careerforge.ats.jd import parse_job_description
from careerforge.ats.report import AtsReport, analyze, compare
from careerforge.ats.semantic import possible_matches
from careerforge.ingest.web import fetch_job_text
from careerforge.models import Profile
from careerforge.ui import state
from careerforge.ui.errors import explain
from careerforge.ui.text import md_escape
from careerforge.ui.widgets import ats_report_view

VIEWS = ("Score", "Section tips", "Compare postings", "Smart matches (AI)")
MAX_JOB_CHARS = 30_000


def job_input() -> str:
    """The job-posting box shared by several pages. The text lives in state, not in the widget."""

    def store() -> None:
        state.set_job(st.session_state["job-input"][:MAX_JOB_CHARS])

    st.text_area(
        "Job posting (paste the full text)",
        value=state.job_text(),
        key="job-input",
        height=220,
        max_chars=MAX_JOB_CHARS,
        on_change=store,
        help="Leave empty for a general ATS-readiness check of your CV.",
    )
    with st.expander("Or fetch it from a link"):
        url = st.text_input("Job posting link (https://...)", key="job-url")
        if st.button("Fetch", key="job-fetch"):
            try:
                with st.spinner("Fetching..."):
                    text = fetch_job_text(url)
                state.set_job(text[:MAX_JOB_CHARS])
                st.session_state.pop("job-input", None)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(explain(exc), icon=":material/error:")
    return state.job_text()


def report_for(profile: Profile, job: str, pdf: bytes | None = None) -> AtsReport:
    key = (
        "ats",
        profile.content_hash(),
        hashlib.sha256(job.encode()).hexdigest(),
        hashlib.sha256(pdf or b"").hexdigest(),
    )
    return state.memo(key, lambda: analyze(profile.exportable(), job or None, pdf=pdf))


def _score_view(profile: Profile, job: str) -> AtsReport:
    pdf_file = st.file_uploader(
        "Optional: upload the PDF you would actually send, to check that it can be read",
        type=["pdf"],
        key="ats-pdf",
        help="Adds a measured 'PDF can be parsed' score based on this very file.",
    )
    report = report_for(profile, job, pdf_file.getvalue() if pdf_file else None)
    if not job.strip():
        st.info("No job posting given: this is a general ATS-readiness check. Paste a posting for a match score.")
    ats_report_view(report)
    return report


def _tips_view(profile: Profile, report: AtsReport) -> None:
    tips = section_tips(profile.exportable(), report)
    if not tips:
        st.success("No section-level suggestions: nothing stood out.")
    for tip in tips:
        st.markdown(f"- **{tip.section.title()}** ({tip.severity}): {md_escape(tip.message)}")


def _compare_view(profile: Profile) -> None:
    st.write("Paste up to five postings to see which one your CV fits best.")
    postings: dict[str, str] = {}
    for i in range(1, 6):
        cols = st.columns([1, 3])
        label = cols[0].text_input(f"Name {i}", key=f"cmp-name-{i}", placeholder=f"Job {i}")
        text = cols[1].text_area(
            f"Posting {i}",
            key=f"cmp-text-{i}",
            height=90,
            max_chars=MAX_JOB_CHARS,
            label_visibility="collapsed",
            placeholder="Paste posting...",
        )
        if text.strip():
            postings[label.strip() or f"Job {i}"] = text
    if len(postings) < 2:
        st.caption("Add at least two postings.")
        return
    rows = compare(profile.exportable(), postings)
    frame = pd.DataFrame(
        [
            {
                "Posting": name,
                "Title": r.job_title,
                "Score": r.overall,
                "Band": r.band,
                "Missing (required)": ", ".join(m.term for m in r.missing if m.importance == "required") or "-",
            }
            for name, r in rows
        ]
    )
    st.dataframe(frame, hide_index=True, use_container_width=True)


def _semantic_view(profile: Profile, job: str, report: AtsReport) -> None:
    st.write(
        "Finds places where your CV *already says* what the posting asks for in different words. "
        "Every suggestion must quote your own text exactly, and it **never changes your score**."
    )
    if not job.strip():
        st.info("Paste a job posting first.")
        return
    if not state.ai_configured():
        st.info("Needs AI. Add a free key in Settings.")
        return
    if st.button("Find smart matches", type="primary", key="semantic-go"):
        try:
            client = state.charge_ai()
            with st.spinner("Comparing wording..."):
                result = possible_matches(client, profile.exportable(), job, report)
        except Exception as exc:  # noqa: BLE001
            st.error(explain(exc), icon=":material/error:")
            return
        if not result.matches:
            st.write("No additional matches were found that could be backed by your own wording.")
        for m in result.matches:
            st.markdown(
                f"- **{md_escape(m.requirement)}** may be covered by: “{md_escape(m.cv_quote)}” ({md_escape(m.why)})"
            )
        if result.dropped:
            st.caption(f"{result.dropped} suggestion(s) were discarded because they did not quote your CV exactly.")


def render() -> None:
    profile = state.require_profile()
    st.title("ATS check")
    job = job_input()
    if job.strip():
        title = parse_job_description(job).title
        if title:
            st.caption(f"Detected job title: **{md_escape(title)}**")
    view = st.radio("View", VIEWS, horizontal=True, key="ats-view")
    if view == "Score":
        _score_view(profile, job)
    elif view == "Section tips":
        _tips_view(profile, report_for(profile, job))
    elif view == "Compare postings":
        _compare_view(profile)
    else:
        _semantic_view(profile, job, report_for(profile, job))


if __name__ == "__main__":
    render()
