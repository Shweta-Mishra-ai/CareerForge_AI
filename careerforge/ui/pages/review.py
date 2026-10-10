"""Review & edit: confirm what was read, correct it, and see what still blocks submission."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import streamlit as st

from careerforge import review
from careerforge.models import Profile, ProfileError
from careerforge.ui import state
from careerforge.ui.text import md_escape
from careerforge.ui.widgets import readiness_panel

SECTIONS = ("Basics", "Skills", "Experience", "Education", "Projects", "Certifications")


@dataclass(frozen=True)
class Field:
    path: tuple[str, ...]
    label: str
    kind: str = "text"  # text | area | lines | csv | bool | int
    help: str = ""


EXPERIENCE = (
    Field(("title",), "Job title"),
    Field(("company",), "Company"),
    Field(("location",), "Location"),
    Field(("dates", "start"), "Start (e.g. 2021-03 or Mar 2021)"),
    Field(("dates", "end"), "End (leave empty if current)"),
    Field(("dates", "current"), "I still work here", "bool"),
    Field(("bullets",), "Achievements (one per line)", "lines", "Start with an action verb; include numbers."),
)
EDUCATION = (
    Field(("degree",), "Degree"),
    Field(("institution",), "Institution"),
    Field(("location",), "Location"),
    Field(("dates", "start"), "Start (year or month)"),
    Field(("dates", "end"), "End (year or month)"),
    Field(("grade",), "Grade / CGPA"),
    Field(("details",), "Details (one per line)", "lines"),
)
PROJECTS = (
    Field(("name",), "Project name"),
    Field(("url",), "Link to the code or page (https://...)"),
    Field(("demo_url",), "Live demo link (https://...)"),
    Field(("featured",), "Show as a featured case study on my portfolio", "bool"),
    Field(("description",), "Description", "area"),
    Field(("tech",), "Technologies (comma separated)", "csv"),
    Field(("bullets",), "What you built or achieved (one per line)", "lines"),
    Field(("stars",), "GitHub stars", "int"),
)
CERTS = (
    Field(("name",), "Certification"),
    Field(("issuer",), "Issuer"),
    Field(("date",), "Date (year or month)"),
    Field(("url",), "Credential link"),
)
LIST_SECTIONS: dict[str, tuple[str, tuple[Field, ...], Callable[[dict], str]]] = {
    "Experience": ("experience", EXPERIENCE, lambda e: e["title"] or e["company"]),
    "Education": ("education", EDUCATION, lambda e: e["degree"] or e["institution"]),
    "Projects": ("projects", PROJECTS, lambda e: e["name"]),
    "Certifications": ("certifications", CERTS, lambda e: e["name"]),
}


def _get(d: dict, path: tuple[str, ...]) -> Any:
    for k in path:
        d = d[k]
    return d


def _set(d: dict, path: tuple[str, ...], value: Any) -> None:
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = value


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _csv(text: str) -> list[str]:
    return [t.strip() for t in text.replace("\n", ",").split(",") if t.strip()]


def _save(mutate: Callable[[dict], None], *, message: str = "Saved.") -> None:
    """Apply a change to a copy of the profile, validate everything, and only then replace it."""
    p = state.require_profile()
    data = p.model_dump()
    mutate(data)
    try:
        new = Profile.from_dict(data)
    except ProfileError as exc:
        st.error(f"Not saved: {exc}", icon=":material/error:")
        return
    state.set_profile(new)
    st.session_state["flash"] = message
    st.rerun()


def _widget(field: Field, value: Any, key: str) -> Any:
    if field.kind == "area":
        return st.text_area(field.label, value, key=key, help=field.help or None, height=110)
    if field.kind == "lines":
        return _lines(st.text_area(field.label, "\n".join(value), key=key, help=field.help or None, height=150))
    if field.kind == "csv":
        return _csv(st.text_input(field.label, ", ".join(value), key=key, help=field.help or None))
    if field.kind == "bool":
        return st.checkbox(field.label, value, key=key, help=field.help or None)
    if field.kind == "int":
        return int(st.number_input(field.label, min_value=0, value=int(value), step=1, key=key))
    return st.text_input(field.label, value, key=key, help=field.help or None)


# ── notes from reading the document ─────────────────────────────────────────


def _ingest_notes() -> None:
    result = state.last_ingest()
    if result is None:
        return
    findings = tuple(result.grounding.findings) if result.grounding else ()
    count = len(result.warnings) + len(findings) + len(result.removed_instruction_lines)
    if not count:
        return
    with st.expander(f"Notes from reading your document ({count})", expanded=bool(findings)):
        for w in result.warnings:
            st.markdown(f"- {md_escape(w)}")
        if findings:
            st.markdown("**Checked against your original text:**")
            for f in findings:
                verb = "Removed" if f.action == "removed" else "Needs your confirmation"
                st.markdown(f"- {verb}: `{f.path}` {md_escape(f.text[:80])}. {md_escape(f.reason)}")
        if result.removed_instruction_lines:
            st.markdown("**Ignored lines that looked like instructions to an AI:**")
            for line in result.removed_instruction_lines:
                st.markdown(f"- {md_escape(line[:120])}")


def _pending(p: Profile) -> None:
    items = p.pending_items()
    if not items:
        return
    st.warning(
        f"{len(items)} item(s) were suggested by AI and are **not in your CV until you confirm them**. "
        "Only confirm what is true.",
        icon=":material/pending:",
    )
    for n, (section, idx, label) in enumerate(items):
        c1, c2, c3 = st.columns([4, 1, 1])
        c1.markdown(f"**{section.title()}**: {md_escape(label)}")
        if c2.button("Confirm", key=f"confirm-{n}-{state.rev()}", help="This is true; include it"):
            state.set_profile(review.confirm(p, section, idx))
            st.rerun()
        if c3.button("Discard", key=f"discard-{n}-{state.rev()}", help="Remove this suggestion"):
            state.set_profile(review.discard(p, section, idx))
            st.rerun()
    if len(items) > 1 and st.button("Confirm all (I have checked every one)", key=f"confirm-all-{state.rev()}"):
        state.set_profile(review.confirm_all(p))
        st.rerun()


# ── section editors ─────────────────────────────────────────────────────────


def _basics(p: Profile) -> None:
    r = state.rev()
    with st.form(f"basics-{r}"):
        name = st.text_input("Full name", p.name, key=f"name-{r}")
        headline = st.text_input("Headline (e.g. Senior Backend Engineer)", p.headline, key=f"headline-{r}")
        summary = st.text_area(
            "Professional summary (2-3 sentences, no 'I')", p.summary, height=140, key=f"summary-{r}"
        )
        c1, c2 = st.columns(2)
        email = c1.text_input("Email", p.contact.email, key=f"email-{r}")
        phone = c2.text_input("Phone", p.contact.phone, key=f"phone-{r}")
        location = c1.text_input("City, country", p.contact.location, key=f"location-{r}")
        website = c2.text_input("Website", p.contact.website, key=f"website-{r}")
        linkedin = c1.text_input("LinkedIn", p.contact.linkedin, key=f"linkedin-{r}")
        github = c2.text_input("GitHub", p.contact.github, key=f"github-{r}")
        saved = st.form_submit_button("Save basics", type="primary")
    if saved:

        def apply(d: dict) -> None:
            d.update(name=name, headline=headline, summary=summary)
            d["contact"].update(
                email=email, phone=phone, location=location, website=website, linkedin=linkedin, github=github
            )

        _save(apply, message="Basics saved.")


def _skills(p: Profile) -> None:
    r = state.rev()
    with st.form(f"skills-{r}"):
        skills = st.text_area(
            "Skills (comma or line separated)",
            ", ".join(p.skills),
            height=140,
            key=f"skills-{r}",
            help="Only list skills you could answer questions about in an interview.",
        )
        languages = st.text_input("Spoken languages", ", ".join(p.languages), key=f"languages-{r}")
        saved = st.form_submit_button("Save skills", type="primary")
    if saved:
        _save(lambda d: d.update(skills=_csv(skills), languages=_csv(languages)), message="Skills saved.")


def _list_section(p: Profile, tab: str) -> None:
    section, fields, label_of = LIST_SECTIONS[tab]
    r = state.rev()
    data = p.model_dump()
    entries = data[section]
    if not entries:
        st.info(f"No {tab.lower()} entries yet. Add one below.")
    with st.form(f"{section}-{r}"):
        collected: list[dict[str, Any]] = []
        for i, entry in enumerate(entries):
            tag = "" if entry["confirmed"] else " (AI suggestion, not yet confirmed)"
            st.markdown(f"**{i + 1}. {md_escape(label_of(entry) or 'New entry')}**{tag}")
            values = {f.path: _widget(f, _get(entry, f.path), f"{section}-{i}-{'.'.join(f.path)}-{r}") for f in fields}
            collected.append(values)
            if i < len(entries) - 1:
                st.divider()
        saved = st.form_submit_button(f"Save {tab.lower()}", type="primary", disabled=not entries)
    if saved:

        def apply(d: dict) -> None:
            for entry, values in zip(d[section], collected, strict=True):
                for path, value in values.items():
                    _set(entry, path, value)

        _save(apply, message=f"{tab} saved.")
    _entry_controls(section, tab, entries, label_of)


def _entry_controls(section: str, tab: str, entries: list[dict], label_of: Callable[[dict], str]) -> None:
    r = state.rev()
    singular = tab.lower().rstrip("s") if tab != "Education" else "education entry"
    if st.button(f"Add {singular}", key=f"add-{section}-{r}", icon=":material/add:"):
        _save(lambda d: d[section].append(_blank(section)), message=f"Added a blank {singular}. Fill it in below.")
    if not entries:
        return
    labels = [f"{i + 1}. {label_of(e) or 'New entry'}" for i, e in enumerate(entries)]
    pick = st.selectbox(
        "Move or remove an entry", range(len(entries)), format_func=labels.__getitem__, key=f"pick-{section}-{r}"
    )
    up, down, remove = st.columns(3)
    if up.button("Move up", key=f"up-{section}-{r}", disabled=pick == 0, icon=":material/arrow_upward:"):
        _save(lambda d: _swap(d[section], pick, pick - 1), message="Moved up.")
    if down.button(
        "Move down", key=f"down-{section}-{r}", disabled=pick == len(entries) - 1, icon=":material/arrow_downward:"
    ):
        _save(lambda d: _swap(d[section], pick, pick + 1), message="Moved down.")
    if remove.button("Remove", key=f"rm-{section}-{r}", icon=":material/delete:"):
        _save(lambda d: d[section].pop(pick), message="Removed.")


def _swap(items: list, a: int, b: int) -> None:
    items[a], items[b] = items[b], items[a]


def _blank(section: str) -> dict:
    from careerforge import models

    cls = {
        "experience": models.Experience,
        "education": models.Education,
        "projects": models.Project,
        "certifications": models.Certification,
    }[section]
    return cls(origin="user").model_dump()


def render() -> None:
    p = state.require_profile()
    st.title("Review & edit")
    st.caption("Check everything. This is exactly what your CV and portfolio will be built from.")
    if flash := st.session_state.pop("flash", None):
        st.toast(flash, icon=":material/check_circle:")
    _ingest_notes()
    _pending(p)
    tab = st.radio("Section", SECTIONS, horizontal=True, key="review-section")
    {"Basics": _basics, "Skills": _skills}.get(tab, lambda prof: _list_section(prof, tab))(p)
    st.divider()
    st.subheader("Is it ready to submit?", anchor=False)
    readiness_panel(p)


if __name__ == "__main__":
    render()
