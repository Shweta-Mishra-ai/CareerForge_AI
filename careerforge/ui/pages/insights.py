"""Insights: where your profile is strong, where it has gaps, and a plan to close them. No AI needed."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from careerforge.analytics import keyword_heat, skill_radar, timeline
from careerforge.roadmap import build_roadmap
from careerforge.ui import state
from careerforge.ui.pages.match import job_input, report_for
from careerforge.ui.text import md_escape

VIEWS = ("Career timeline", "Skill coverage", "Keyword heat", "Learning roadmap")


def render() -> None:
    profile = state.require_profile()
    p = profile.exportable()
    st.title("Insights")
    job = job_input()
    view = st.radio("View", VIEWS, horizontal=True, key="insights-view")
    if view == "Career timeline":
        tl = timeline(p)
        if not tl.spans:
            st.info("Add dated experience to see your timeline.")
            return
        st.metric(
            "Total experience (overlaps counted once)", f"{tl.total_months // 12} years {tl.total_months % 12} months"
        )
        st.dataframe(
            pd.DataFrame(
                [{"Role": s.label, "From": s.start, "To": s.end or "Present", "Months": s.months} for s in tl.spans]
            ),
            hide_index=True,
            use_container_width=True,
        )
        for gap in tl.gaps:
            st.warning(gap, icon=":material/warning:")
    elif view == "Skill coverage":
        axes = skill_radar(p, job or None)
        if not axes:
            st.info("Add skills to see coverage.")
            return
        frame = pd.DataFrame(
            {a.category: {"Listed": a.listed, "Required by posting": a.required, "Matched": a.matched} for a in axes}
        ).T
        if not job.strip():
            frame = frame[["Listed"]]
            st.caption("Paste a job posting above to compare against what it requires.")
        st.bar_chart(frame)
        st.dataframe(frame, use_container_width=True)
    elif view == "Keyword heat":
        if not job.strip():
            st.info("Paste a job posting above: this shows where each keyword appears in your CV.")
            return
        rows = keyword_heat(p, job)
        if not rows:
            st.info("No keywords were found in the posting.")
            return
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Keyword": r.term,
                        "Importance": r.importance,
                        "Skills": r.skills,
                        "Summary": r.summary,
                        "Experience": r.experience,
                        "Projects": r.projects,
                    }
                    for r in rows
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Numbers are how often the keyword appears in each section. A keyword only in Skills carries less weight."
        )
    else:
        if not job.strip():
            st.info("Paste a job posting above to get a roadmap for the skills you are missing.")
            return
        items = build_roadmap(report_for(profile, job), p)
        if not items:
            st.success("You already cover everything the posting asks for.")
        for item in items:
            low, high = item.weeks
            with st.expander(f"{item.skill} ({item.priority}): about {low}-{high} weeks"):
                if item.builds_on:
                    st.caption(f"Builds on what you already know: {item.builds_on}")
                for step in item.steps:
                    st.markdown(f"1. {md_escape(step)}")
                st.markdown(f"**Project idea:** {md_escape(item.project)}")
        st.caption(
            "Estimates are rough and assume part-time study. Only add a skill to your CV once you have really used it."
        )


if __name__ == "__main__":
    render()
