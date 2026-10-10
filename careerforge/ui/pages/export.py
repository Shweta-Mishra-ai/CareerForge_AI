"""CV & portfolio: choose a look, preview it, download it. Exports are blocked until the CV is ready to submit."""

from __future__ import annotations

import json

import streamlit as st
from pydantic import ValidationError

from careerforge.models import Profile
from careerforge.readiness import NotReady
from careerforge.render.cv import PdfEngineUnavailable, PdfExport, preview_html, render_cv_html, render_cv_pdf
from careerforge.render.docx_export import render_cv_docx
from careerforge.render.options import DEFAULT_ACCENT, SECTION_TITLES, SECTIONS, TEMPLATES, RenderOptions
from careerforge.render.portfolio import PortfolioOptions, blockers, build_portfolio
from careerforge.render.text_export import render_cv_txt
from careerforge.render.themes import THEMES
from careerforge.ui import state
from careerforge.ui.errors import explain
from careerforge.ui.text import md_escape
from careerforge.ui.widgets import download, readiness_panel, safe_file_stem

BUILT = "built_files"
FONTS = {
    "Template default": None,
    "Arial-style (sans)": "sans",
    "Times-style (serif)": "serif",
    "Calibri-style": "humanist",
}
DENSITIES = {"Compact (fits more)": "compact", "Normal": "normal", "Relaxed (more white space)": "relaxed"}


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    return str(err["msg"]).removeprefix("Value error, ")


def _choose_version(profile: Profile) -> Profile:
    tailored = state.tailored()
    if tailored is None:
        return profile
    pick = st.radio("Which version?", ["Main profile", "Tailored version"], horizontal=True, key="export-version")
    return tailored if pick == "Tailored version" else profile


def _cv_options(profile: Profile) -> RenderOptions | None:
    template = st.selectbox(
        "Template",
        list(TEMPLATES),
        format_func=lambda k: TEMPLATES[k].label,
        key="cv-template",
    )
    info = TEMPLATES[template]
    if info.ats_safe:
        st.caption(f":material/verified: {info.description}")
    else:
        st.warning(info.description, icon=":material/warning:")
    present = [s for s in SECTIONS if getattr(profile.exportable(), s)]
    with st.expander("Appearance and sections"):
        c1, c2, c3 = st.columns(3)
        accent = c1.color_picker("Accent colour", DEFAULT_ACCENT, key="cv-accent")
        font = c2.selectbox("Font", list(FONTS), key="cv-font")
        paper = c3.selectbox("Paper", ["A4", "Letter"], key="cv-paper")
        density = st.select_slider("Density", list(DENSITIES), value="Normal", key="cv-density")
        chosen = st.multiselect(
            "Sections, in this order",
            present,
            default=RenderOptions(template=template).section_order(profile.exportable()),
            format_func=SECTION_TITLES.get,
            key=f"cv-sections-{template}-{state.rev()}",
        )
        group = st.checkbox("Group skills by category", value=True, key="cv-group")
    try:
        return RenderOptions(
            template=template,
            accent=accent,
            font=FONTS[font],
            paper=paper,
            density=DENSITIES[density],
            order=tuple(chosen),
            hidden=frozenset(s for s in present if s not in chosen),
            group_skills=group,
        )
    except ValidationError as exc:
        st.error(f"Appearance: {_first_error(exc)}", icon=":material/error:")
        return None


def _build_files(profile: Profile, options: RenderOptions) -> None:
    try:
        with st.spinner("Building your files..."):
            files: dict = {"pdf": None}
            try:
                files["pdf"] = render_cv_pdf(profile, options)
            except PdfEngineUnavailable as exc:  # only the PDF is lost; the other formats do not need the engine
                st.warning(str(exc), icon=":material/warning:")
            files |= {
                "docx": render_cv_docx(profile, options),
                "txt": render_cv_txt(profile, options),
                "html": render_cv_html(profile, options),
            }
    except Exception as exc:  # noqa: BLE001 - includes NotReady: shown as a sentence
        st.error(explain(exc), icon=":material/error:")
        return
    st.session_state[BUILT] = (_signature(profile, options), files)


def _signature(profile: Profile, options: RenderOptions) -> str:
    data = options.model_dump(mode="json")
    data["hidden"] = sorted(data["hidden"])  # a set has no stable order
    return profile.content_hash() + json.dumps(data, sort_keys=True)


def _pdf_report(pdf: PdfExport) -> None:
    st.markdown(f"**{pdf.pages} page(s)**. ATS parse check of this exact PDF: **{pdf.parse.score}/100**")
    for finding in pdf.parse.findings:
        st.warning(finding, icon=":material/warning:")
    for warning in pdf.warnings:
        st.warning(warning, icon=":material/warning:")
    if not pdf.parse.findings and not pdf.warnings:
        st.success(
            "A simple ATS text extractor reads this PDF cleanly, in the right order.", icon=":material/check_circle:"
        )
    with st.expander("What was checked"):
        for item in pdf.parse.checks:
            mark = ":material/check:" if item.passed else ":material/close:"
            st.markdown(f"- {mark} {md_escape(item.label)} {md_escape(item.detail)}")


def _cv_tab(profile: Profile) -> None:
    options = _cv_options(profile)
    if options is None:
        return
    result = readiness_panel(profile, key="export-ready")
    st.subheader("Preview", anchor=False)
    st.iframe(preview_html(profile, options), height=900)
    if not result.ready:
        st.info("Downloads unlock when the blockers above are fixed. Use **Review & edit**.")
        st.page_link("careerforge/ui/pages/review.py", label="Go to Review & edit", icon=":material/edit_note:")
        return
    if st.button("Build my files (PDF, Word, text, HTML)", type="primary", key="build-files"):
        _build_files(profile, options)
    built = st.session_state.get(BUILT)
    if not built:
        return
    signature, files = built
    if signature != _signature(profile, options):
        st.info("Your profile or settings changed. Build again to get matching files.")
        return
    stem = safe_file_stem(profile.name)
    cols = st.columns(4)
    with cols[0]:
        if files["pdf"] is not None:
            download("PDF", files["pdf"].data, f"{stem}_CV.pdf", "application/pdf", key="dl-pdf", primary=True)
        else:
            st.caption("PDF unavailable on this machine")
    with cols[1]:
        download(
            "Word (.docx)",
            files["docx"],
            f"{stem}_CV.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="dl-docx",
        )
    with cols[2]:
        download("Plain text", files["txt"], f"{stem}_CV.txt", "text/plain", key="dl-txt")
    with cols[3]:
        download("HTML", files["html"], f"{stem}_CV.html", "text/html", key="dl-html")
    if files["pdf"] is not None:
        _pdf_report(files["pdf"])


# ── portfolio ───────────────────────────────────────────────────────────────


def _portfolio_tab(profile: Profile) -> None:
    st.write("A one-file website you can host for free. No scripts, no trackers, works offline.")
    c1, c2 = st.columns(2)
    theme = c1.radio("Theme", list(THEMES), format_func=lambda k: THEMES[k].label, horizontal=True, key="pf-theme")
    use_accent = c2.checkbox("Use my own accent colour", key="pf-use-accent")
    accent = (
        c2.color_picker("Accent colour", "#1d4ed8", key="pf-accent", disabled=not use_accent) if use_accent else None
    )
    with st.expander("What to show"):
        show_email = st.checkbox("Show my email address", value=True, key="pf-email")
        show_phone = st.checkbox("Show my phone number (invites spam; off by default)", value=False, key="pf-phone")
        show_stats = st.checkbox(
            "Show summary figures (years, projects, stars: computed from your profile)", value=True, key="pf-stats"
        )
        site_url = st.text_input(
            "Address you will publish at (optional)", key="pf-url", placeholder="https://yourname.dev"
        )
        hide = st.multiselect(
            "Hide sections",
            ["about", "projects", "experience", "skills", "education", "certifications", "languages", "contact"],
            key="pf-hide",
        )
    try:
        options = PortfolioOptions(
            theme=theme,
            accent=accent,
            site_url=site_url,
            show_email=show_email,
            show_phone=show_phone,
            show_stats=show_stats,
            hidden=frozenset(hide),
        )
    except ValidationError as exc:
        st.error(f"Options: {_first_error(exc)}", icon=":material/error:")
        return
    gate = blockers(profile, options)
    if not gate.ready:
        for issue in gate.blockers:
            st.error(issue.message, icon=":material/error:")
        return
    try:
        built = build_portfolio(profile, options)
    except (ValueError, NotReady) as exc:
        st.error(explain(exc) if isinstance(exc, NotReady) else str(exc), icon=":material/error:")
        return
    for warning in built.warnings:
        st.warning(warning, icon=":material/warning:")
    st.iframe(built.html, height=900)
    stem = safe_file_stem(profile.name)
    d1, d2 = st.columns(2)
    with d1:
        download(
            "Download site (.zip with deploy guide)",
            built.zip_bytes(),
            f"{stem}_portfolio.zip",
            "application/zip",
            key="dl-pf-zip",
            primary=True,
        )
    with d2:
        download("Download index.html only", built.html, "index.html", "text/html", key="dl-pf-html")
    st.caption(
        "The page is public once you publish it. Read it once and hide anything you do not want strangers to see."
    )
    with st.expander("How to publish it for free"):
        st.markdown(built.readme)


def render() -> None:
    profile = state.require_profile()
    st.title("CV & portfolio")
    profile = _choose_version(profile)
    tab = st.radio("What do you want to build?", ["CV", "Portfolio website"], horizontal=True, key="export-tab")
    if tab == "CV":
        _cv_tab(profile)
    else:
        _portfolio_tab(profile)


if __name__ == "__main__":
    render()
