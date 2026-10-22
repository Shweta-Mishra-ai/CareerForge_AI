"""Start: get your details in from a CV, a LinkedIn export, pasted text, GitHub, a saved profile, or from scratch."""

from __future__ import annotations

import streamlit as st

from careerforge.ai.errors import AIError
from careerforge.ingest.github import fetch_github, merge_github, parse_github_user
from careerforge.ingest.pipeline import IngestResult, ingest_upload
from careerforge.models import Profile
from careerforge.tracker import Tracker, load_file
from careerforge.ui import state, style
from careerforge.ui.errors import AIBudgetExceeded, explain

MAX_PASTE = 60_000
SOURCES = ("Upload a file", "Paste text", "GitHub", "Start from scratch")
REVIEW = "careerforge/ui/pages/review.py"


def _finish(result: IngestResult, *, tracker: Tracker | None = None) -> None:
    state.set_profile(result.profile, ingest=result)
    if tracker is not None:
        state.set_tracker(tracker)
    st.session_state.pop("start_retry", None)
    st.switch_page(REVIEW)


def _read(name: str, data: bytes, *, use_ai: bool) -> None:
    try:
        with st.spinner("Reading your document..."):
            client = state.charge_ai() if use_ai else None
            result = ingest_upload(name, data, client)
            tracker = load_file(data)[1] if result.source == "profile_json" else None
    except (AIError, AIBudgetExceeded) as exc:
        st.error(explain(exc), icon=":material/error:")
        st.session_state["start_retry"] = (name, data)
        return
    except Exception as exc:  # noqa: BLE001 - every failure is shown as a sentence, never a traceback
        st.error(explain(exc), icon=":material/error:")
        return
    _finish(result, tracker=tracker)


def _reading_mode() -> bool:
    """True = AI-assisted. Explicit, never a silent fallback."""
    if not state.ai_configured():
        st.info(
            "AI is not set up, so your document is read with the **basic reader** (it finds contact details, "
            "sections, skills and dates, but cannot restructure messy text). Add a free key in **Settings** for "
            "AI-assisted reading.",
            icon=":material/info:",
        )
        return False
    choice = st.radio(
        "How should your document be read?",
        ["AI-assisted (recommended)", "Basic (no AI, nothing leaves this app)"],
        horizontal=True,
        key="start-reading",
        help="AI-assisted sends the text of your document to the AI provider. Everything it returns is checked "
        "against your original text, and anything that cannot be found there is removed.",
    )
    return choice.startswith("AI")


def _upload_tab() -> None:
    use_ai = _reading_mode()
    with st.expander("Where do I get my details from LinkedIn?"):
        st.markdown(
            "- **LinkedIn PDF:** open your profile, choose **More → Save to PDF**, upload it here.\n"
            "- **Full data export (most complete):** LinkedIn **Settings → Data privacy → Get a copy of your data**, "
            "pick the options you want, download the ZIP and upload it here. Only the profile-related files are "
            "read; messages, contacts and other files are ignored.\n"
            "- **Chrome extension:** the `chrome_extension` folder copies your open profile as text; paste it in the "
            "**Paste text** option."
        )
    upload = st.file_uploader(
        "Your CV, LinkedIn PDF or data export, or a saved CareerForge profile",
        type=["pdf", "docx", "txt", "md", "zip", "json"],
        accept_multiple_files=False,
        help="Up to 10 MB. Scanned (image-only) PDFs cannot be read; use a text-based PDF.",
    )
    if upload is not None and st.button("Read this file", type="primary", key="read-upload"):
        _read(upload.name, upload.getvalue(), use_ai=use_ai)


def _paste_tab() -> None:
    use_ai = _reading_mode()
    text = st.text_area(
        "Paste your CV or LinkedIn profile text",
        height=300,
        max_chars=MAX_PASTE,
        placeholder="Paste the full text here...",
    )
    if st.button("Read this text", type="primary", key="read-paste"):
        if len(text.strip()) < 80:
            st.error("Paste at least a few lines: there is not enough text to work with.", icon=":material/error:")
        else:
            _read("pasted.txt", text.encode("utf-8"), use_ai=use_ai)


def _github_tab() -> None:
    st.markdown(
        "Adds your **public repositories as projects** and your languages as skills. It never invents jobs or "
        "education. Only import your own account: GitHub does not let us verify ownership."
    )
    current = state.profile()
    user = st.text_input("GitHub username or profile URL", placeholder="e.g. octocat", key="gh-user")
    add_skills = st.checkbox("Also add my repository languages to my skills", value=True, key="gh-skills")
    label = "Add projects to my current profile" if current else "Create a profile from GitHub"
    if st.button(label, type="primary", key="gh-go"):
        try:
            with st.spinner("Reading your public repositories..."):
                imp = fetch_github(parse_github_user(user), token=state.site_secret("GITHUB_TOKEN") or None)
                base = current or Profile()
                merged = merge_github(base, imp, add_skills=add_skills)
        except Exception as exc:  # noqa: BLE001
            st.error(explain(exc), icon=":material/error:")
            return
        notes = list(imp.warnings)
        if imp.public_repos or imp.total_stars or imp.followers:
            notes.append(
                f"GitHub summary (for your information, not added to your CV): {imp.public_repos} public repositories, "
                f"{imp.total_stars} stars, {imp.followers} followers."
            )
        if not current:
            notes.append(
                "This profile has projects and skills only. Add your experience and education on the Review page "
                "(or upload a CV) before exporting a CV."
            )
        _finish(IngestResult(merged, "github", tuple(notes)))


def _blank_tab() -> None:
    st.markdown("Build everything by hand on the Review page. Nothing is pre-filled.")
    if st.button("Start with an empty profile", type="primary", key="blank-go"):
        _finish(IngestResult(Profile(), "blank"))


def render() -> None:
    st.title("Start")
    st.write("Add your details once. Everything else (ATS check, tailoring, CV, portfolio) is built from them.")
    style.steps()
    current = state.profile()
    if current is not None:
        st.warning(
            f"A profile is already loaded ({current.name or 'unnamed'}). Importing something new replaces it. "
            "Download your profile from the sidebar first if you want to keep it.",
            icon=":material/warning:",
        )
    source = st.radio("Where are your details?", SOURCES, horizontal=True, key="start-source")
    {"Upload a file": _upload_tab, "Paste text": _paste_tab, "GitHub": _github_tab, "Start from scratch": _blank_tab}[
        source
    ]()
    if "start_retry" in st.session_state:
        name, data = st.session_state["start_retry"]
        if st.button("Read it with the basic reader instead (no AI)", key="retry-basic"):
            _read(name, data, use_ai=False)
    with st.expander("Privacy"):
        st.markdown(
            "Your details stay in this browser session's memory and are gone when you close the tab. Nothing is "
            "stored on a server. If you choose AI-assisted features, the text involved is sent to the AI provider "
            "whose key is configured. Download your profile (sidebar) to keep it."
        )


if __name__ == "__main__":
    render()
