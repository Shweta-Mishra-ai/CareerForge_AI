"""Turn a Profile into the small, display-ready pieces the templates need (links, grouped skills)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from careerforge import skills as taxonomy
from careerforge.models import Contact, Profile
from careerforge.render.options import SECTION_TITLES, RenderOptions

GROUP_LABELS = {"Languages": "Programming Languages"}  # plain "Languages" would read as spoken languages on a CV
GROUP_MIN_SKILLS = 9  # shorter skill lists read better as one line than as many one-item groups


@dataclass(frozen=True)
class ContactItem:
    kind: str  # email | phone | location | linkedin | github | website
    text: str
    href: str = ""


def short_url(url: str) -> str:
    """'https://www.linkedin.com/in/x/' -> 'linkedin.com/in/x' (the form people write on a CV)."""
    return re.sub(r"^https?://(?:www\.)?", "", url).rstrip("/")


def contact_items(c: Contact, *, include: frozenset[str] | None = None) -> list[ContactItem]:
    """Contact details in the order recruiters scan them. `include` limits which kinds are shown."""
    digits = re.sub(r"[^\d+]", "", c.phone)
    items = [
        ContactItem("email", c.email, f"mailto:{c.email}" if c.email else ""),
        ContactItem("phone", c.phone, f"tel:{digits}" if c.phone else ""),
        ContactItem("location", c.location),
        ContactItem("linkedin", short_url(c.linkedin), c.linkedin),
        ContactItem("github", short_url(c.github), c.github),
        ContactItem("website", short_url(c.website), c.website),
    ]
    return [i for i in items if i.text and (include is None or i.kind in include)]


def skill_groups(skills: list[str], *, group: bool) -> list[tuple[str, list[str]]]:
    """[('Backend', [...]), ...]; a single unlabeled group when grouping is off, the list is short or uncategorised."""
    if not group or len(skills) < GROUP_MIN_SKILLS:
        return [("", list(skills))] if skills else []
    buckets: dict[str, list[str]] = {}
    for s in skills:
        buckets.setdefault(taxonomy.category_of(s), []).append(s)
    if set(buckets) == {"Other"}:
        return [("", list(skills))]
    order = [*taxonomy.CATEGORY_ORDER, "Other"]
    return [(GROUP_LABELS.get(cat, cat), buckets[cat]) for cat in order if cat in buckets]


def meta_description(summary: str, headline: str, name: str, limit: int = 155) -> str:
    """A search-snippet description built only from the user's own words."""
    text = summary or (f"{name} - {headline}" if headline else "")
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:- ")
    return cut + "…"


# ── format-neutral document structure: HTML, DOCX and TXT all render from this ──────────────────────────────


@dataclass(frozen=True)
class Entry:
    head: str
    when: str = ""
    sub: str = ""
    text: str = ""
    bullets: tuple[str, ...] = ()
    url: str = ""


@dataclass(frozen=True)
class Block:
    name: str
    title: str
    paragraph: str = ""  # summary / languages
    entries: tuple[Entry, ...] = ()
    skills: tuple[tuple[str, str], ...] = ()  # (label, "a, b, c")


def _join(*parts: str) -> str:
    return " · ".join(p for p in parts if p)


def build_blocks(profile: Profile, options: RenderOptions) -> list[Block]:
    """The visible sections, in order, with every string already composed for display."""
    out: list[Block] = []
    for name in options.section_order(profile):
        title = SECTION_TITLES[name]
        if name == "summary":
            out.append(Block(name, title, paragraph=profile.summary))
        elif name == "languages":
            out.append(Block(name, title, paragraph=", ".join(profile.languages)))
        elif name == "skills":
            groups = skill_groups(profile.skills, group=options.group_skills)
            out.append(Block(name, title, skills=tuple((label, ", ".join(names)) for label, names in groups)))
        elif name == "experience":
            entries = tuple(
                Entry(
                    e.title or e.company,
                    e.dates.display(),
                    _join(e.company if e.title else "", e.location),
                    bullets=tuple(e.bullets),
                )
                for e in profile.experience
            )
            out.append(Block(name, title, entries=entries))
        elif name == "projects":
            entries = tuple(
                Entry(
                    pr.name,
                    short_url(pr.url),
                    ", ".join(pr.tech),
                    pr.description,
                    tuple(pr.bullets),
                    pr.url,
                )
                for pr in profile.projects
            )
            out.append(Block(name, title, entries=entries))
        elif name == "education":
            entries = tuple(
                Entry(
                    ed.degree or ed.institution,
                    ed.dates.display(),
                    _join(ed.institution if ed.degree else "", ed.location, ed.grade),
                    bullets=tuple(ed.details),
                )
                for ed in profile.education
            )
            out.append(Block(name, title, entries=entries))
        elif name == "certifications":
            entries = tuple(Entry(c.name, c.date, c.issuer) for c in profile.certifications)
            out.append(Block(name, title, entries=entries))
    return out
