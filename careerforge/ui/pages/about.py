"""How it works: what is measured, what is not, and what the app promises."""

from __future__ import annotations

import streamlit as st

from careerforge.ats.report import DISCLAIMER, WEIGHTS


def render() -> None:
    st.title("How it works")
    st.subheader("What this app promises", anchor=False)
    st.markdown(
        "- **It never invents experience.** AI may reword or suggest; every output is checked against your own text. "
        "Suggestions stay out of your CV until you confirm them.\n"
        "- **It tells you when it is unsure.** Failures are shown, never hidden behind made-up content.\n"
        "- **It will not export an unfinished CV.** Missing name or email, sample emails and leftover placeholders "
        "block the download.\n"
        "- **Your data stays in your session.** Nothing is stored on a server."
    )
    st.subheader("How the ATS score is calculated", anchor=False)
    st.markdown("The number comes from plain code, never from an AI. With a job posting, these parts are combined:")
    for key, weight in WEIGHTS.items():
        st.markdown(f"- **{key}**: weight {weight}")
    st.markdown(
        "- Keywords count most when they appear in your experience bullets, less when only listed under Skills.\n"
        "- A skill implied by another (Flask implies Python) counts, at a small discount.\n"
        "- Parts that cannot be measured (the PDF part, when you have not uploaded a PDF) are left out and the rest "
        "is re-weighted."
    )
    st.warning(DISCLAIMER, icon=":material/warning:")
    st.subheader("Limits you should know about", anchor=False)
    st.markdown(
        "- Real ATS products differ and are secret; no tool can predict one exactly.\n"
        "- Scanned (image-only) PDFs cannot be read; use a text-based PDF.\n"
        "- LinkedIn cannot be read directly from a link; use its PDF or data export.\n"
        "- GitHub import cannot prove an account is yours; only import your own.\n"
        "- Free AI models can be slow, busy or change; the app tells you when that happens."
    )


if __name__ == "__main__":
    render()
