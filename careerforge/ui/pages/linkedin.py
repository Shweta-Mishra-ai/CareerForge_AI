"""LinkedIn profile: the text to paste into each part of your LinkedIn profile, built from your CV."""

from __future__ import annotations

import streamlit as st

from careerforge.linkedin_kit import (
    ABOUT_LIMIT,
    HEADLINE_LIMIT,
    build_linkedin_kit,
)
from careerforge.ui import state
from careerforge.ui.text import md_escape


def _field(title: str, text: str, limit: int | None = None) -> None:
    st.markdown(f"**{title}**")
    if not text:
        st.caption("Nothing to paste: your profile has no text for this part.")
        return
    st.code(text, language=None, wrap_lines=True)
    if limit:
        over = len(text) > limit
        st.caption(f"{len(text)} of {limit} characters" + (" (over the limit)" if over else ""))


def render() -> None:
    profile = state.require_profile()
    st.title("LinkedIn profile")
    st.write(
        "Your CV, rearranged for LinkedIn. Every line is your own text: nothing is added or invented. Use the copy "
        "button on each box, paste it into the matching part of your profile, and check the character counter "
        "LinkedIn shows (its limits can change)."
    )
    kit = build_linkedin_kit(profile)
    for note in kit.notes:
        st.info(note, icon=":material/info:")

    _field("Headline", kit.headline, HEADLINE_LIMIT)
    _field("About", kit.about, ABOUT_LIMIT)

    st.subheader("Experience", anchor=False)
    if not kit.experience:
        st.caption("No experience in your profile.")
    for e in kit.experience:
        with st.expander(f"{e.title}" + (f", {e.company}" if e.company else "")):
            meta = " · ".join(x for x in (e.company, e.location, e.dates) if x)
            st.caption(md_escape(meta))
            _field("Description", e.description)

    st.subheader("Skills", anchor=False)
    if kit.skills:
        st.markdown("**Pin these three as Top skills:** " + md_escape(", ".join(kit.top_skills)))
        st.code(", ".join(kit.skills), language=None, wrap_lines=True)
        st.caption(f"{len(kit.skills)} skills. Add them one by one in LinkedIn's Skills section.")

    if kit.education:
        st.subheader("Education", anchor=False)
        for ed in kit.education:
            with st.expander(ed.school):
                st.caption(md_escape(" · ".join(x for x in (ed.degree, ed.dates, ed.grade) if x)))
                if ed.description:
                    _field("Activities and notes", ed.description)

    if kit.projects:
        st.subheader("Projects", anchor=False)
        for pr in kit.projects:
            with st.expander(pr.name):
                _field("Description", pr.description)
                if pr.url:
                    st.caption("Link: " + md_escape(pr.url))
                if pr.skills:
                    st.caption("Skills used: " + md_escape(", ".join(pr.skills)))

    if kit.certifications:
        st.subheader("Licenses & certifications", anchor=False)
        for c in kit.certifications:
            st.markdown("- " + md_escape(" · ".join(x for x in (c.name, c.issuer, c.date) if x)))


if __name__ == "__main__":
    render()
