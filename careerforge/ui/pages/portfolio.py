"""Portfolio: build a professional one-file website from your profile, preview it live, download it, host it free."""

from __future__ import annotations

import streamlit as st
from pydantic import ValidationError

from careerforge.models import Profile
from careerforge.readiness import NotReady
from careerforge.render.cv import PdfEngineUnavailable, render_cv_pdf
from careerforge.render.options import RenderOptions
from careerforge.render.photo import PhotoError
from careerforge.render.portfolio import (
    LAYOUT_KEYS,
    LAYOUTS,
    PORTFOLIO_SECTIONS,
    PORTFOLIO_TITLES,
    Layout,
    PortfolioOptions,
    blockers,
    build_portfolio,
)
from careerforge.render.themes import PRESETS, THEMES
from careerforge.ui import state
from careerforge.ui.errors import explain
from careerforge.ui.widgets import download, first_error, safe_file_stem


def _portfolio_cv(profile: Profile) -> bytes | None:
    """The CV PDF for the portfolio (ATS Classic), or None with the reason shown. Cached per profile."""
    key = ("pf-cv-pdf", profile.content_hash())
    cached = st.session_state.get("pf-cv-cache")
    if cached and cached[0] == key:
        return cached[1]
    try:
        with st.spinner("Making your CV PDF..."):
            data = render_cv_pdf(profile, RenderOptions(template="ats-classic")).data
    except PdfEngineUnavailable as exc:
        st.warning(str(exc), icon=":material/warning:")
        return None
    except NotReady as exc:
        st.warning(
            f"The CV is not ready to export, so it is left out of the site. {explain(exc)}", icon=":material/warning:"
        )
        return None
    st.session_state["pf-cv-cache"] = (key, data)
    return data


def _look() -> tuple[Layout, str, str | None, str | None]:
    """Layout, theme, custom accent and named colour, from the "Look" controls."""
    st.subheader("1. Look", anchor=False)
    layout: Layout = st.radio("Layout", LAYOUT_KEYS, format_func=lambda k: LAYOUTS[k][0], key="pf-layout")
    st.caption(LAYOUTS[layout][1])
    theme = st.radio(
        "Page colours",
        list(THEMES),
        index=list(THEMES).index("light"),
        format_func=lambda k: THEMES[k].label.split(" (")[0],  # "Automatic (light or dark ...)" is long; see the help
        help="Automatic follows the visitor's device: a light page on a light device, a dark page on a dark one.",
        key="pf-theme",
    )
    is_auto = theme == "auto"
    # A named colour works on every theme (the automatic one gets a light and a dark shade); your own colour cannot
    # work on both pages of the automatic theme, so it is not offered there.
    choices = ["theme", *PRESETS, *([] if is_auto else ["custom"])]
    colour = st.selectbox(
        "Accent colour",
        choices,
        format_func=lambda k: {"theme": "Theme default", "custom": "My own colour..."}.get(k) or PRESETS[k][0],
        key="pf-colour",
    )
    if is_auto:
        st.caption("Your own colour is not offered here: no single colour is readable on both a light and a dark page.")
    accent = st.color_picker("My accent colour", "#1d4ed8", key="pf-accent") if colour == "custom" else None
    return layout, theme, accent, colour if colour in PRESETS else None


def _content() -> dict:
    st.subheader("2. Content", anchor=False)
    order = st.multiselect(
        "Sections shown, in this order",
        list(PORTFOLIO_SECTIONS),
        default=list(PORTFOLIO_SECTIONS),
        format_func=lambda k: PORTFOLIO_TITLES[k],
        key="pf-order",
        help="Remove a section to leave it out. A section your profile has no content for is skipped anyway.",
    )
    show_contact = st.checkbox("Show the contact section", value=True, key="pf-contact")
    show_email = st.checkbox("Show my email address", value=True, key="pf-email")
    show_phone = st.checkbox(
        "Show my phone number",
        value=False,
        key="pf-phone",
        help="A public phone number invites spam, so it is off by default.",
    )
    show_location = st.checkbox(
        "Show my city", value=False, key="pf-location", help="It is public once you publish the site."
    )
    show_stats = st.checkbox(
        "Show summary figures",
        value=True,
        key="pf-stats",
        help="Years of experience, number of projects and GitHub stars: all computed from your profile.",
    )
    open_to_work = st.checkbox(
        'Show an "Open to opportunities" badge',
        value=False,
        key="pf-open",
        help="Your own statement, so it is off unless you turn it on.",
    )
    include_cv = st.checkbox(
        "Add a CV download button",
        value=False,
        key="pf-cv",
        help="Puts your CV (PDF, ATS Classic template) in the site. The CV is public too once you publish.",
    )
    return {
        "order": tuple(order),
        "hidden": frozenset(
            {s for s in PORTFOLIO_SECTIONS if s not in order} | (set() if show_contact else {"contact"})
        ),
        "show_email": show_email,
        "show_phone": show_phone,
        "show_location": show_location,
        "show_stats": show_stats,
        "include_cv": include_cv,
        "open_to_work": open_to_work,
    }


def _photo() -> bytes | None:
    upload = st.file_uploader(
        "Your photo (optional)",
        type=["jpg", "jpeg", "png", "webp"],
        key="pf-photo",
        help="Used by every layout except Editorial. A clear head-and-shoulders photo works best.",
    )
    st.caption(
        "Cropped to a square and re-saved small; camera and location data are removed. It is public once you "
        "publish, and it is not kept in your saved profile file."
    )
    return upload.getvalue() if upload is not None else None


def _publishing() -> dict:
    st.subheader("3. Publishing", anchor=False)
    site_url = st.text_input("Site address (optional)", key="pf-url", placeholder="https://yourname.dev")
    custom_domain = st.text_input(
        "Own domain (optional)",
        key="pf-domain",
        placeholder="yourname.dev",
        help="Adds the CNAME file GitHub Pages needs. You still point the domain's DNS at GitHub yourself.",
    )
    noindex = st.checkbox("Hide from search engines", value=False, key="pf-noindex")
    return {"site_url": site_url, "custom_domain": custom_domain, "noindex": noindex}


def _downloads(profile: Profile, built) -> None:
    st.subheader("Download and publish", anchor=False)
    stem = safe_file_stem(profile.name)
    d1, d2 = st.columns(2)
    with d1:
        download(
            "Download site (.zip with deploy guide)",
            built.zip_bytes,  # built on click, not on every rerun
            f"{stem}_portfolio.zip",
            "application/zip",
            key="dl-pf-zip",
            primary=True,
        )
    with d2:
        download("Download index.html only", lambda: built.html, "index.html", "text/html", key="dl-pf-html")
    host1, host2, host3 = st.columns(3)
    host1.link_button(
        "Publish on Netlify (drag the unzipped folder)", "https://app.netlify.com/drop", icon=":material/open_in_new:"
    )
    host2.link_button(
        "GitHub Pages guide",
        "https://docs.github.com/pages/getting-started-with-github-pages",
        icon=":material/open_in_new:",
    )
    host3.link_button(
        "Cloudflare Pages guide", "https://developers.cloudflare.com/pages/", icon=":material/open_in_new:"
    )
    st.caption(
        "Nothing is hosted for you and nothing is stored: download the site and put it on a free host yourself, "
        "or send the single `index.html` file to anyone (it opens in any browser, offline). To try another look "
        "later, save your profile (sidebar) and load it again: the same data builds every layout. "
        "The page is public once you publish it. Read it once and hide anything you do not want strangers to see. "
        "Mark your best projects as featured case studies in **Review & edit**."
    )
    with st.expander("How to publish it for free"):
        st.markdown(built.readme)


def render() -> None:
    profile = state.require_profile()
    st.title("Portfolio")
    st.write(
        "A professional one-file website made from your profile. No scripts, no trackers, works offline, and you "
        "can host it for free. Everything on it comes from your confirmed profile: nothing is invented."
    )
    look, content_col, publish_col = st.columns(3, gap="large")
    with look:
        layout, theme, accent, preset = _look()
    with content_col:
        content = _content()
        photo = _photo()
    with publish_col:
        publishing = _publishing()
    try:
        options = PortfolioOptions(theme=theme, accent=accent, preset=preset, layout=layout, **content, **publishing)
    except ValidationError as exc:
        st.error(f"Options: {first_error(exc)}", icon=":material/error:")
        return
    gate = blockers(profile, options)
    if not gate.ready:
        for issue in gate.blockers:
            st.error(issue.message, icon=":material/error:")
        return
    cv_pdf = _portfolio_cv(profile) if options.include_cv else None
    try:
        try:
            built = build_portfolio(profile, options, cv_pdf=cv_pdf, photo=photo)
        except PhotoError as exc:  # a bad photo must not block the site: say why, build it without one
            content_col.error(f"{exc}. The site below is built without a photo.", icon=":material/error:")
            built = build_portfolio(profile, options, cv_pdf=cv_pdf)
    except (ValueError, NotReady) as exc:
        st.error(explain(exc) if isinstance(exc, NotReady) else str(exc), icon=":material/error:")
        return
    st.subheader("Live preview", anchor=False)
    for warning in built.warnings:
        st.warning(warning, icon=":material/warning:")
    st.iframe(built.html, height=900)
    _downloads(profile, built)


if __name__ == "__main__":
    render()
