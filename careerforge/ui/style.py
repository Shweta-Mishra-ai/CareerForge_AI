"""The app's look: one fixed stylesheet, the logo and a fixed strip of steps.

Nothing here is built from user data, so it can be injected as raw HTML without any escaping question. Selectors use
Streamlit's `data-testid` attributes (the most stable hooks it offers) and our own `cf-` classes; if a Streamlit
upgrade renames something, the page falls back to Streamlit's own look rather than breaking.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

CSS = (Path(__file__).parent / "assets" / "app.css").read_text(encoding="utf-8")

STEPS = """
<ol class="cf-steps" aria-label="How it works">
<li><b>Add your details</b><span>Upload a CV or LinkedIn export, paste text, or import your GitHub projects.</span></li>
<li><b>Check and improve</b><span>Review every fact, run the ATS check, tailor your CV to a job.</span></li>
<li><b>Download and apply</b><span>CV, portfolio website, cover letter, outreach e-mails and a job tracker.</span></li>
</ol>
"""


LOGO = str(Path(__file__).parent / "assets" / "logo.svg")  # absolute: the server may be started from any folder


def inject() -> None:
    """Add the stylesheet and the logo to the page. Call once per run, before anything else is drawn."""
    st.html(f"<style>{CSS}</style>")
    st.logo(LOGO, size="large")


def steps() -> None:
    st.html(STEPS)


def next_step(profile_loaded: bool, ready: bool) -> tuple[str, str]:
    """(page, what to do) for the sidebar's "Next" box. Pure, so it can be tested without a browser."""
    if not profile_loaded:
        return "Start", "Add your CV, a LinkedIn export or your GitHub projects."
    if not ready:
        return "Review & edit", "Fix the items marked as blocking before you export."
    return "CV", "Download your CV, build your portfolio website, or tailor your CV to a job first."
