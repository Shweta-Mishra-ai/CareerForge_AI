"""CareerForge AI: turn an old CV, a LinkedIn profile or a GitHub account into a ready-to-submit CV and portfolio.

Entry point. Pages live in careerforge/ui/pages/; all logic lives in the `careerforge` package.
"""

from __future__ import annotations

import streamlit as st

from careerforge.readiness import check
from careerforge.tracker import dump_file
from careerforge.ui import state
from careerforge.ui.widgets import ai_status_badge, download, safe_file_stem

st.set_page_config(
    page_title="CareerForge AI",
    page_icon="📄",  # an emoji needs no request; Material icons would be fetched from a Google CDN
    layout="wide",
    initial_sidebar_state="auto",
)

P = "careerforge/ui/pages/"
PAGES = {
    "Build": [
        st.Page(P + "start.py", title="Start", icon=":material/play_arrow:", url_path="start", default=True),
        st.Page(P + "review.py", title="Review & edit", icon=":material/edit_note:", url_path="review"),
    ],
    "Improve": [
        st.Page(P + "match.py", title="ATS check", icon=":material/fact_check:", url_path="ats"),
        st.Page(P + "tailor.py", title="Tailor to a job", icon=":material/tune:", url_path="tailor"),
        st.Page(P + "insights.py", title="Insights", icon=":material/insights:", url_path="insights"),
    ],
    "Deliver": [
        st.Page(P + "export.py", title="CV & portfolio", icon=":material/description:", url_path="export"),
        st.Page(P + "linkedin.py", title="LinkedIn profile", icon=":material/badge:", url_path="linkedin"),
        st.Page(P + "write.py", title="Letters & interviews", icon=":material/mail:", url_path="write"),
    ],
    "Apply": [
        st.Page(P + "jobs.py", title="Jobs & tracker", icon=":material/work_history:", url_path="jobs"),
    ],
    "More": [
        st.Page(P + "settings.py", title="Settings", icon=":material/settings:", url_path="settings"),
        st.Page(P + "about.py", title="How it works", icon=":material/info:", url_path="about"),
    ],
}


def sidebar() -> None:
    with st.sidebar:
        st.markdown("### CareerForge AI")
        profile = state.profile()
        if profile is None:
            st.caption("No profile loaded yet.")
        else:
            ready = check(profile).ready
            st.markdown(f"**{profile.name or 'Unnamed profile'}**")
            st.caption(
                ":material/check_circle: Ready to export" if ready else ":material/error: Not ready to export yet"
            )
            download(
                "Save my profile",
                dump_file(profile, state.tracker()),
                f"{safe_file_stem(profile.name, 'profile')}_careerforge.json",
                "application/json",
                key="sidebar-save",
            )
            st.caption("Keeps your profile and job tracker. Load it later on the Start page.")
            if st.button("Clear everything", key="sidebar-clear", icon=":material/delete_forever:"):
                st.session_state.clear()
                st.rerun()
        ai_status_badge()


sidebar()
st.navigation(PAGES).run()
