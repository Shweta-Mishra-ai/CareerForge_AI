"""Jobs & tracker: find postings ranked against your CV, and keep track of every application."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from careerforge.jobs import (
    AdzunaProvider,
    JobicyProvider,
    RankedJob,
    RemotiveProvider,
    rank_jobs,
    search_all,
    suggest_queries,
)
from careerforge.outreach import build_emails
from careerforge.text import normalize_url
from careerforge.tracker import STATUSES
from careerforge.ui import state
from careerforge.ui.pages.match import report_for
from careerforge.ui.text import md_escape

VIEWS = ("Find jobs", "Application tracker")
RESULTS = "job_results"
FOLLOW_UP_LABELS = {"follow_up_1": "first follow-up", "follow_up_2": "second follow-up", "close_out": "close out"}


def _providers(chosen: list[str]) -> list:
    out: list = []
    if "Remotive" in chosen:
        out.append(RemotiveProvider())
    if "Jobicy" in chosen:
        out.append(JobicyProvider())
    if "Adzuna" in chosen:
        out.append(AdzunaProvider(state.site_secret("ADZUNA_APP_ID"), state.site_secret("ADZUNA_APP_KEY")))
    return out


def _safe_link(url: str) -> str:
    try:
        return normalize_url(url)
    except ValueError:
        return ""


def _show_job(profile, ranked: RankedJob, i: int) -> None:
    job = ranked.job
    with st.container(border=True):
        st.markdown(
            f"**{md_escape(job.title)}** at {md_escape(job.company)}  \n"
            f"{md_escape(job.location)} · {md_escape(job.source)}"
        )
        st.markdown(f"Match with your CV: **{ranked.score}/100**")
        if ranked.matched:
            st.caption("You have: " + md_escape(", ".join(ranked.matched)))
        if ranked.missing:
            st.caption("Missing: " + md_escape(", ".join(ranked.missing)))
        link = _safe_link(job.url)
        c1, c2, c3 = st.columns(3)
        if link:
            c1.link_button("Open posting", link, icon=":material/open_in_new:")
        if c2.button("Check my CV against it", key=f"job-use-{i}"):
            state.set_job(job.description or job.title, title=job.title, company=job.company)
            st.session_state.pop("job-input", None)
            st.switch_page("careerforge/ui/pages/match.py")
        if c3.button("Add to tracker", key=f"job-add-{i}"):
            report = report_for(profile, job.description) if job.description else None
            tracker, _ = state.tracker().add(
                job.company, job.title, url=link, ats_score=report.overall if report else None
            )
            state.set_tracker(tracker)
            st.toast("Added to your tracker.", icon=":material/check_circle:")


def _find(profile) -> None:
    st.caption("Searches public job boards. Results are ranked by how well your CV matches each posting.")
    suggestions = suggest_queries(profile.exportable())
    query = st.text_input("Search", value=suggestions[0] if suggestions else "", key="job-query")
    if suggestions:
        st.caption("Ideas from your CV: " + ", ".join(suggestions))
    options = ["Remotive", "Jobicy"] + (
        ["Adzuna"] if state.site_secret("ADZUNA_APP_ID") and state.site_secret("ADZUNA_APP_KEY") else []
    )
    chosen = st.multiselect("Job boards", options, default=options[:2], key="job-sources")
    if st.button("Search", type="primary", key="job-search") and query.strip():
        with st.spinner("Searching..."):
            found = search_all(_providers(chosen), query)
        st.session_state[RESULTS] = (found, rank_jobs(profile.exportable(), found.jobs))
    stored = st.session_state.get(RESULTS)
    if not stored:
        return
    found, ranked = stored
    for name, message in found.errors.items():
        st.warning(f"{name} could not be searched: {message}", icon=":material/warning:")
    if not ranked:
        st.info("No postings found. Try a broader search.")
    for i, r in enumerate(ranked):
        _show_job(profile, r, i)


def _tracker(profile) -> None:
    tracker = state.tracker()
    with st.form("tracker-add", clear_on_submit=True):
        c1, c2 = st.columns(2)
        company = c1.text_input("Company")
        role = c2.text_input("Role")
        url = st.text_input("Posting link (optional)")
        status = st.selectbox("Status", STATUSES, index=0)
        added = st.form_submit_button("Add application", type="primary")
    if added:
        if not (company.strip() and role.strip()):
            st.error("Enter the company and the role.", icon=":material/error:")
        else:
            try:
                new, _ = tracker.add(company, role, url=url, status=status)
            except ValueError as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                state.set_tracker(new)
                st.rerun()
    if not tracker.applications:
        st.info("No applications tracked yet.")
        return
    due = tracker.due(date.today())
    if due:
        st.subheader("Follow-ups due", anchor=False)
        for f in due:
            label = FOLLOW_UP_LABELS.get(f.kind, f.kind)
            with st.container(border=True):
                st.markdown(
                    f"**{md_escape(f.company)}**, {md_escape(f.role)}: {label} ({f.overdue_days} day(s) overdue)"
                )
                if f.kind != "close_out":
                    mail = build_emails(profile.exportable(), f.company, f.role)[f.kind]
                    st.code(mail.body, language=None, wrap_lines=True)
                    if st.button("Mark as sent", key=f"sent-{f.application_id}-{f.kind}"):
                        state.set_tracker(tracker.mark_followup_sent(f.application_id, f.kind))
                        st.rerun()
                else:
                    st.caption("No reply after three weeks usually means no. Consider moving on.")
    st.subheader("Applications", anchor=False)
    frame = pd.DataFrame(
        [
            {
                "Company": a.company,
                "Role": a.role,
                "Status": a.status,
                "Applied": a.applied_on or "-",
                "ATS": a.ats_score if a.ats_score is not None else "-",
            }
            for a in tracker.applications
        ]
    )
    st.dataframe(frame, hide_index=True, width="stretch")
    labels = {a.id: f"{a.company}: {a.role}" for a in tracker.applications}
    pick = st.selectbox("Update an application", list(labels), format_func=labels.get, key="tracker-pick")
    current = tracker.get(pick)
    c1, c2 = st.columns([2, 1])
    new_status = c1.selectbox(
        "New status", STATUSES, index=STATUSES.index(current.status), key=f"tracker-status-{pick}"
    )
    if c1.button("Update status", key="tracker-move") and new_status != current.status:
        state.set_tracker(tracker.move(pick, new_status))
        st.rerun()
    if c2.button("Remove", key="tracker-remove", icon=":material/delete:"):
        state.set_tracker(tracker.remove(pick))
        st.rerun()
    st.caption("Your tracker is saved in the profile file (sidebar: Save my profile).")


def render() -> None:
    profile = state.require_profile()
    st.title("Jobs & tracker")
    view = st.radio("View", VIEWS, horizontal=True, key="jobs-view")
    _find(profile) if view == "Find jobs" else _tracker(profile)


if __name__ == "__main__":
    render()
