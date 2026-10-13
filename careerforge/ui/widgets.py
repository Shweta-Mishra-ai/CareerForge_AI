"""Reusable Streamlit pieces. Colour is never the only signal: every status also has words and an icon."""

from __future__ import annotations

import streamlit as st

from careerforge.ats.report import AtsReport
from careerforge.models import Profile
from careerforge.readiness import Readiness, check
from careerforge.ui.text import md_escape

SEVERITY_ICON = {"blocker": ":material/error:", "warning": ":material/warning:", "tip": ":material/lightbulb:"}
BAND_HELP = {
    "Excellent": "Strong match on the things this tool can measure.",
    "Good": "Solid, with a few gaps worth closing.",
    "Fair": "Some gaps; the fixes below will help most.",
    "Needs work": "Several important gaps. Work through the fixes below.",
}


def readiness_panel(profile: Profile) -> Readiness:
    """Shows what stops this CV from being submitted, and what would improve it."""
    result = check(profile)
    blockers, warnings, tips = result.of("blocker"), result.of("warning"), result.of("tip")
    if result.ready:
        st.success("Ready to export: nothing blocks submission.", icon=":material/check_circle:")
    else:
        st.error(f"{len(blockers)} thing(s) must be fixed before you can export.", icon=":material/error:")
        for issue in blockers:
            st.markdown(f"- **{md_escape(issue.message)}** (`{issue.path}`)")
    if warnings:
        with st.expander(f"{len(warnings)} warning(s): likely to cost interviews"):
            for issue in warnings:
                st.markdown(f"- {md_escape(issue.message)} (`{issue.path}`)")
    if tips:
        with st.expander(f"{len(tips)} tip(s) to polish"):
            for issue in tips:
                st.markdown(f"- {md_escape(issue.message)}")
    return result


def ats_report_view(report: AtsReport, *, show_disclaimer: bool = True) -> None:
    """Score, components, matched/missing requirements and the prioritised fixes."""
    left, right = st.columns([1, 3])
    with left:
        label = "ATS match score" if report.kind == "match" else "ATS-readiness score"
        st.metric(label, f"{report.overall}/100", help=BAND_HELP.get(report.band, ""))
        st.markdown(f"**{report.band}**")
    with right:
        for comp in report.components:
            value = comp.score
            if value is None:
                st.markdown(f"**{comp.label}**: not measured. {md_escape(comp.detail)}")
                continue
            st.progress(value / 100, text=f"{comp.label}: {value}/100 (weight {comp.weight})")
            if comp.detail:
                st.caption(comp.detail)
    if report.kind == "match":
        hit, miss = st.columns(2)
        with hit:
            st.subheader("Matched", anchor=False)
            if not report.matches:
                st.write("No requirements matched.")
            for m in report.matches:
                where = ", ".join(m.where) or "-"
                note = f" (implied by {md_escape(m.implied_by)})" if m.implied_by else ""
                st.markdown(
                    f"- :material/check: **{md_escape(m.requirement.term)}**{note}: found in {md_escape(where)}"
                )
        with miss:
            st.subheader("Missing", anchor=False)
            if not report.missing:
                st.write("Nothing important is missing.")
            for r in report.missing:
                st.markdown(f"- :material/close: **{md_escape(r.term)}** ({r.importance})")
    if report.fixes:
        st.subheader("What to fix, most important first", anchor=False)
        for fix in report.fixes:
            st.markdown(f"- {SEVERITY_ICON.get(fix.severity, '')} **{md_escape(fix.area)}**: {md_escape(fix.message)}")
    for note in report.notes:
        st.caption(note)
    if show_disclaimer:
        st.caption(report.disclaimer)


def ai_status_badge() -> None:
    from careerforge.ui import state

    if not state.ai_configured():
        problem = " Check Settings: a problem was found." if state.config_problems() else ""
        st.caption(f":material/smart_toy: AI: not set up (basic mode).{problem}")
        return
    left = state.ai_calls_left()
    detail = "your own key" if left is None else f"{left} shared actions left"
    st.caption(f":material/smart_toy: AI: ready ({detail})")


def download(label: str, data: str | bytes, file_name: str, mime: str, *, key: str, primary: bool = False) -> None:
    st.download_button(
        label,
        data,
        file_name=file_name,
        mime=mime,
        key=key,
        type="primary" if primary else "secondary",
        icon=":material/download:",
        width="stretch",
    )


def safe_file_stem(name: str, fallback: str = "cv") -> str:
    """A filename-safe version of a person's name (no path characters, no spaces)."""
    import re

    stem = re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_")
    return stem[:60] or fallback
