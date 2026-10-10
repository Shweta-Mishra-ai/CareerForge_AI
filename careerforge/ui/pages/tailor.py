"""Tailor: reword your CV for one posting. Nothing is invented, nothing changes without your say-so."""

from __future__ import annotations

import streamlit as st

from careerforge.tailor.service import TailorResult, apply_proposal, tailor
from careerforge.ui import state
from careerforge.ui.errors import explain
from careerforge.ui.pages.match import job_input
from careerforge.ui.text import md_escape

RESULT = "tailor_result"
STATUS_TEXT = {
    "applied": "Safe rewording (same facts): applied",
    "needs_review": "Adds wording from the posting: apply only if it is TRUE for you",
    "rejected": "Rejected: it changed the facts",
}


def _run(profile, job: str) -> None:
    try:
        client = state.charge_ai()
        with st.spinner("Rewording your bullets for this posting..."):
            result = tailor(client, profile.exportable(), job)
    except Exception as exc:  # noqa: BLE001
        st.error(explain(exc), icon=":material/error:")
        return
    st.session_state[RESULT] = (profile.content_hash(), job, result)


def _current(profile, job: str) -> TailorResult | None:
    stored = st.session_state.get(RESULT)
    if not stored:
        return None
    digest, stored_job, result = stored
    if digest != profile.content_hash() or stored_job != job:
        return None  # the profile or posting changed since: the old suggestions no longer apply
    return result


def _show(profile, result: TailorResult) -> None:
    left, right = st.columns(2)
    left.metric("Match before", f"{result.before.overall}/100")
    right.metric("Match after", f"{result.after.overall}/100", delta=result.after.overall - result.before.overall)
    for note in result.notes:
        st.caption(md_escape(note))
    groups = {s: [p for p in result.proposals if p.status == s] for s in STATUS_TEXT}
    if not result.proposals:
        st.info("The model found nothing worth rewording.")
    if groups["applied"]:
        st.subheader("Applied automatically", anchor=False)
        for p in groups["applied"]:
            st.markdown(f"**{p.path}**  \nBefore: {md_escape(p.before)}  \nAfter: {md_escape(p.after)}")
    accepted: list = []
    if groups["needs_review"]:
        st.subheader("Needs your decision", anchor=False)
        st.caption(STATUS_TEXT["needs_review"])
        for i, p in enumerate(groups["needs_review"]):
            terms = f" (new: {md_escape(', '.join(p.new_terms))})" if p.new_terms else ""
            st.markdown(f"**{p.path}**{terms}  \nBefore: {md_escape(p.before)}  \nAfter: {md_escape(p.after)}")
            if st.checkbox("This is true for me: use the new wording", key=f"tailor-accept-{i}"):
                accepted.append(p)
    if groups["rejected"]:
        with st.expander(f"{len(groups['rejected'])} rejected suggestion(s)"):
            for p in groups["rejected"]:
                st.markdown(f"**{p.path}**: {md_escape('; '.join(p.reasons))}")
    if st.button("Use this tailored version for export", type="primary", key="tailor-use"):
        tailored = result.profile
        for p in accepted:
            tailored = apply_proposal(tailored, p)
        state.set_tailored(tailored)
        st.success("Saved. Choose 'Tailored version' on the CV & portfolio page. Your main profile is unchanged.")
        st.page_link("careerforge/ui/pages/export.py", label="Go to CV & portfolio", icon=":material/description:")


def render() -> None:
    profile = state.require_profile()
    st.title("Tailor to a job")
    st.write(
        "The AI rewords your existing bullets to speak the posting's language. Every rewording is checked: "
        "new numbers, employers or skills are rejected, and wording that mentions something from the posting "
        "that your CV never said is held for your decision."
    )
    job = job_input()
    if not state.ai_configured():
        st.info("Tailoring needs AI. Add a free Gemini or Groq key in **Settings**.", icon=":material/info:")
        return
    if not job.strip():
        st.info("Paste a job posting above to begin.")
        return
    if st.button("Suggest improvements", type="primary", key="tailor-go"):
        _run(profile, job)
    result = _current(profile, job)
    if result is not None:
        _show(profile, result)


if __name__ == "__main__":
    render()
