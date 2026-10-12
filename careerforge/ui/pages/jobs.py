"""Jobs & tracker: find postings ranked against your CV, and keep track of every application."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from careerforge.jobs import (
    EMPLOYMENT_TYPES,
    SENIORITY_ORDER,
    AdzunaProvider,
    ArbeitnowProvider,
    JobicyProvider,
    MuseProvider,
    Preferences,
    RankedJob,
    RemoteOkProvider,
    RemotiveProvider,
    filter_jobs,
    providers_from_urls,
    rank_jobs,
    search_all,
    suggest_queries,
)
from careerforge.outreach import build_emails
from careerforge.text import normalize_url
from careerforge.tracker import MAX_SAVED_SEARCHES, STATUSES
from careerforge.ui import state
from careerforge.ui.pages.match import report_for
from careerforge.ui.text import md_escape

VIEWS = ("Find jobs", "Application tracker")
RESULTS = "job_results"
FOLLOW_UP_LABELS = {"follow_up_1": "first follow-up", "follow_up_2": "second follow-up", "close_out": "close out"}
FEEDS = ("Remotive", "Jobicy", "The Muse", "RemoteOK", "Arbeitnow")
POSTED = {"Any time": None, "Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30}


def _providers(chosen: list[str]) -> list:
    out: list = []
    if "Remotive" in chosen:
        out.append(RemotiveProvider())
    if "Jobicy" in chosen:
        out.append(JobicyProvider())
    if "The Muse" in chosen:
        out.append(MuseProvider())
    if "RemoteOK" in chosen:
        out.append(RemoteOkProvider())
    if "Arbeitnow" in chosen:
        out.append(ArbeitnowProvider())
    if "Adzuna" in chosen:
        out.append(AdzunaProvider(state.site_secret("ADZUNA_APP_ID"), state.site_secret("ADZUNA_APP_KEY")))
    return out


def _safe_link(url: str) -> str:
    try:
        return normalize_url(url)
    except ValueError:
        return ""


def _score_breakdown(ranked: RankedJob) -> None:
    with st.expander("How this score was calculated"):
        for part in ranked.parts:
            if part.score is None:
                st.markdown(f"- {md_escape(part.label)}: **not measured** ({md_escape(part.detail)})")
            else:
                st.markdown(
                    f"- {md_escape(part.label)}: **{part.score}/100**, weight {part.weight:.0%} "
                    f"({md_escape(part.detail)})"
                )
        st.caption(
            "Parts that cannot be measured for a posting are left out and the others re-weighted. The weights are "
            "design choices, not fitted to hiring outcomes."
        )


def _show_job(profile, ranked: RankedJob, i: int, *, new: bool) -> None:
    job = ranked.job
    with st.container(border=True):
        badge = " :green-badge[NEW]" if new else ""
        st.markdown(
            f"**{md_escape(job.title)}** at {md_escape(job.company)}{badge}  \n"
            f"{md_escape(job.location)} · via {md_escape(job.source)}"
            + (f" · posted {md_escape(job.posted)}" if job.posted else "")
        )
        facts = [x for x in (job.seniority, job.employment, "remote" if job.remote else "", job.salary) if x]
        if facts:
            st.caption(" · ".join(md_escape(x) for x in facts))
        st.markdown(f"Match with your CV: **{ranked.score}/100**")
        if ranked.matched:
            st.caption("You have: " + md_escape(", ".join(ranked.matched)))
        if ranked.missing:
            st.caption("Missing: " + md_escape(", ".join(ranked.missing)))
        for flag in ranked.flags:
            st.warning(flag, icon=":material/warning:")
        _score_breakdown(ranked)
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
                job.company, job.title, url=link, ats_score=report.overall if report else None, source=job.source
            )
            state.set_tracker(tracker)
            st.toast("Added to your tracker.", icon=":material/check_circle:")


def _load_search(tracker, search_id: str) -> None:
    found = next((x for x in tracker.saved_searches if x.id == search_id), None)
    if found is None:
        return
    st.session_state.update(
        {
            "job-query": found.query,
            "job-location": found.location,
            "job-remote": found.remote_only,
            "job-boards-text": "\n".join(found.boards),
        }
    )


def _saved_searches() -> None:
    tracker = state.tracker()
    if not tracker.saved_searches:
        return
    labels = {s.id: s.query + (f" ({s.location})" if s.location else "") for s in tracker.saved_searches}
    c1, c2, c3 = st.columns([3, 1, 1])
    pick = c1.selectbox("Saved searches", list(labels), format_func=labels.get, key="job-saved-pick")
    # A callback runs before the boxes are drawn, which is the only moment their values can be set reliably (setting
    # them and calling st.rerun() left the old text showing in the browser).
    c2.button("Load", key="job-saved-load", on_click=_load_search, args=(tracker, pick))
    if c3.button("Delete", key="job-saved-del"):
        state.set_tracker(tracker.remove_search(pick))
        st.rerun()


def _find(profile) -> None:
    st.caption(
        "Searches public job boards and the careers pages of companies you choose. Results are ranked by "
        "how well your CV matches each posting."
    )
    if message := st.session_state.pop("job-flash", None):
        st.toast(message, icon=":material/check_circle:")
    _saved_searches()
    suggestions = suggest_queries(profile.exportable())
    query = st.text_input("Search", value=suggestions[0] if suggestions else "", key="job-query")
    if suggestions:
        st.caption("Ideas from your CV: " + ", ".join(suggestions))
    c1, c2 = st.columns([3, 1])
    location = c1.text_input("Where (optional)", key="job-location", placeholder="e.g. Pune")
    remote_only = c2.checkbox("Remote only", key="job-remote")
    options = [
        *FEEDS,
        *(["Adzuna"] if state.site_secret("ADZUNA_APP_ID") and state.site_secret("ADZUNA_APP_KEY") else []),
    ]
    chosen = st.multiselect("Job boards", options, default=list(FEEDS[:2]), key="job-sources")
    boards_text = st.text_area(
        "Company careers pages (optional, one link per line)",
        key="job-boards-text",
        height=80,
        placeholder="https://boards.greenhouse.io/company\nhttps://jobs.lever.co/company",
        help="Links on Greenhouse or Lever only. Other links are ignored.",
    )
    boards = [b for b in boards_text.splitlines() if b.strip()]
    board_providers, rejected = providers_from_urls(boards)
    for bad in rejected:
        st.warning(f"Not a Greenhouse or Lever link, ignored: {bad}", icon=":material/warning:")
    c3, c4 = st.columns(2)
    if c3.button("Search", type="primary", key="job-search") and query.strip():
        tracker = state.tracker()
        with st.spinner("Searching..."):
            found = search_all([*_providers(chosen), *board_providers], query)
        prefs = Preferences(location=location, remote_only=remote_only)
        ranked = rank_jobs(profile.exportable(), found.jobs, prefs=prefs)
        links = [link for r in ranked if (link := _safe_link(r.job.url))]
        st.session_state[RESULTS] = (found, ranked, set(links) - set(tracker.seen))
        state.set_tracker(tracker.mark_seen(links))
    if c4.button(
        "Save this search", key="job-save", disabled=len(state.tracker().saved_searches) >= MAX_SAVED_SEARCHES
    ):
        try:
            tracker, _ = state.tracker().add_search(
                query, location=location, remote_only=remote_only, boards=boards[:10]
            )
        except ValueError as exc:
            st.error(str(exc), icon=":material/error:")
        else:
            state.set_tracker(tracker)
            st.session_state["job-flash"] = "Search saved in your profile file."
            st.rerun()  # the "Saved searches" list is drawn above this button, so it needs a fresh run to show it
    stored = st.session_state.get(RESULTS)
    if not stored:
        return
    found, ranked, fresh = stored
    for name, message in found.errors.items():
        st.warning(f"{name} could not be searched: {message}", icon=":material/warning:")
    if not ranked:
        st.info("No postings found. Try a broader search.")
        return
    with st.expander("Filters", expanded=False):
        f1, f2 = st.columns(2)
        levels = f1.multiselect("Seniority (from the job title)", SENIORITY_ORDER, key="job-f-level")
        kinds = f2.multiselect("Employment type", EMPLOYMENT_TYPES, key="job-f-kind")
        f3, f4, f5 = st.columns(3)
        posted = f3.selectbox("Posted", list(POSTED), key="job-f-posted")
        min_score = f4.slider("Minimum match", 0, 100, 0, key="job-f-min")
        hide = f5.checkbox("Hide postings with warnings", key="job-f-hide")
    shown = [
        r
        for r in filter_jobs(
            ranked,
            remote_only=remote_only,
            seniority=levels,
            employment=kinds,
            posted_within_days=POSTED[posted],
            hide_flagged=hide,
        )
        if r.score >= min_score
    ]
    st.caption(f"{len(shown)} of {len(ranked)} postings shown, {len(fresh)} new since your last search.")
    st.caption("Job data comes from the boards named on each card; follow the link for the original posting.")
    for i, r in enumerate(shown):
        _show_job(profile, r, i, new=r.job.url in fresh)


def _tracker(profile) -> None:
    tracker = state.tracker()
    with st.form("tracker-add", clear_on_submit=True):
        c1, c2 = st.columns(2)
        company = c1.text_input("Company")
        role = c2.text_input("Role")
        url = st.text_input("Posting link (optional)")
        c3, c4 = st.columns(2)
        source = c3.text_input("Where you found it (optional)")
        contact = c4.text_input("Recruiter or contact (optional)")
        status = st.selectbox("Status", STATUSES, index=0)
        added = st.form_submit_button("Add application", type="primary")
    if added:
        if not (company.strip() and role.strip()):
            st.error("Enter the company and the role.", icon=":material/error:")
        else:
            try:
                new, _ = tracker.add(company, role, url=url, status=status, source=source, contact=contact)
            except ValueError as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                state.set_tracker(new)
                st.rerun()
    if not tracker.applications:
        st.info("No applications tracked yet.")
        return
    actions = tracker.actions_due(date.today())
    if actions:
        st.subheader("Your next actions", anchor=False)
        for a in actions:
            when = "today" if a.overdue_days == 0 else f"{a.overdue_days} day(s) overdue"
            st.markdown(f"- **{md_escape(a.company)}**, {md_escape(a.role)}: {md_escape(a.action)} ({when})")
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
                "Source": a.source or "-",
                "Contact": a.contact or "-",
                "Next action": f"{a.next_action} ({a.next_action_on})" if a.next_action and a.next_action_on else "-",
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
    with st.expander("Next action and contact"):
        n1, n2 = st.columns([3, 1])
        action = n1.text_input("Next action", value=current.next_action, key=f"tracker-action-{pick}")
        due_on = n2.text_input(
            "Due (YYYY-MM-DD)", value=current.next_action_on, key=f"tracker-due-{pick}", placeholder="2026-10-31"
        )
        n3, n4 = st.columns(2)
        contact = n3.text_input("Contact", value=current.contact, key=f"tracker-contact-{pick}")
        source = n4.text_input("Source", value=current.source, key=f"tracker-source-{pick}")
        if st.button("Save details", key=f"tracker-details-{pick}"):
            try:
                state.set_tracker(
                    tracker.update(pick, next_action=action, next_action_on=due_on, contact=contact, source=source)
                )
            except ValueError as exc:
                st.error(str(exc).splitlines()[-1] if str(exc) else "Check the date.", icon=":material/error:")
            else:
                st.rerun()
    st.caption("Your tracker is saved in the profile file (sidebar: Save my profile).")


def render() -> None:
    profile = state.require_profile()
    st.title("Jobs & tracker")
    view = st.radio("View", VIEWS, horizontal=True, key="jobs-view")
    if view == "Find jobs":
        _find(profile)
    else:
        _tracker(profile)


if __name__ == "__main__":
    render()
