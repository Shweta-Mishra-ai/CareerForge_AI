"""CV -> LinkedIn: the text to paste into each part of a LinkedIn profile ("reverse mode").

Deterministic and AI-free, so nothing can be invented: every line is the user's own text, rearranged and trimmed to
LinkedIn's field sizes. The limits below are the ones LinkedIn documented when this was written; LinkedIn can change
them, so the UI says to check the counter LinkedIn shows while pasting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from careerforge.models import Profile

HEADLINE_LIMIT = 220
ABOUT_LIMIT = 2600
DESCRIPTION_LIMIT = 2000
SKILLS_LIMIT = 50
TOP_SKILLS = 3  # LinkedIn lets you pin three
ABOUT_SKILLS = 10
HIGHLIGHTS = 3


@dataclass(frozen=True)
class ExperienceText:
    title: str
    company: str
    location: str
    dates: str
    description: str


@dataclass(frozen=True)
class EducationText:
    school: str
    degree: str
    dates: str
    grade: str
    description: str


@dataclass(frozen=True)
class ProjectText:
    name: str
    description: str
    url: str
    skills: tuple[str, ...]


@dataclass(frozen=True)
class CertificationText:
    name: str
    issuer: str
    date: str
    url: str


@dataclass(frozen=True)
class LinkedInKit:
    headline: str
    about: str
    experience: tuple[ExperienceText, ...]
    education: tuple[EducationText, ...]
    skills: tuple[str, ...]
    projects: tuple[ProjectText, ...]
    certifications: tuple[CertificationText, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def top_skills(self) -> tuple[str, ...]:
        return self.skills[:TOP_SKILLS]


def _fits(parts: list[str], sep: str, limit: int) -> str:
    """As many leading parts as fit in `limit` characters (never cutting a part in half)."""
    out = ""
    for part in parts:
        candidate = f"{out}{sep}{part}" if out else part
        if len(candidate) > limit:
            break
        out = candidate
    return out


def _headline(p: Profile, notes: list[str]) -> str:
    base = p.headline or (p.experience[0].title if p.experience else "")
    if not base:
        notes.append("There is no headline or job title in your profile, so the LinkedIn headline is empty.")
        return ""
    return _fits([base, *p.skills[:TOP_SKILLS]], " | ", HEADLINE_LIMIT)


def _highlights(p: Profile) -> list[str]:
    """Your own bullets, measurable ones first, in their original wording."""
    bullets = [b for e in p.experience for b in e.bullets] + [b for pr in p.projects for b in pr.bullets]
    measurable = [b for b in bullets if re.search(r"\d", b)]
    return (measurable or bullets)[:HIGHLIGHTS]


def _about(p: Profile, notes: list[str]) -> str:
    blocks: list[str] = []
    if p.summary:
        blocks.append(p.summary)
    else:
        notes.append("Your profile has no summary, so the About section is built from your skills and highlights only.")
    if p.skills:
        blocks.append("What I work with: " + ", ".join(p.skills[:ABOUT_SKILLS]) + ".")
    highlights = _highlights(p)
    if highlights:
        blocks.append("Highlights:\n" + "\n".join(f"• {h}" for h in highlights))
    # drop the optional parts, last first, until it fits
    while len("\n\n".join(blocks)) > ABOUT_LIMIT and len(blocks) > 1:
        blocks.pop()
        notes.append("The About text was shortened to fit LinkedIn's limit: highlights or skills were left out.")
    text = "\n\n".join(blocks)
    if len(text) > ABOUT_LIMIT:
        text = text[: ABOUT_LIMIT - 1].rsplit(" ", 1)[0] + "…"
        notes.append("Your summary is longer than LinkedIn allows and was cut at a word. Shorten it yourself instead.")
    return text


def _description(bullets: list[str], label: str, notes: list[str]) -> str:
    lines = [f"• {b}" for b in bullets]
    kept = _fits(lines, "\n", DESCRIPTION_LIMIT)
    if kept.count("\n") + (1 if kept else 0) < len(lines):
        notes.append(f"{label}: some bullets were left out to fit LinkedIn's description limit.")
    return kept


def build_linkedin_kit(profile: Profile) -> LinkedInKit:
    """The unconfirmed (AI-suggested) items are never included, exactly as for the CV."""
    p = profile.exportable()
    notes: list[str] = []
    experience = tuple(
        ExperienceText(
            e.title or e.company,
            e.company if e.title else "",
            e.location,
            e.dates.display(),
            _description(e.bullets, e.title or e.company or "Experience", notes),
        )
        for e in p.experience
    )
    education = tuple(
        EducationText(
            ed.institution or ed.degree,
            ed.degree if ed.institution else "",
            ed.dates.display(),
            ed.grade,
            _description(ed.details, ed.institution or ed.degree or "Education", notes),
        )
        for ed in p.education
    )
    skills = tuple(p.skills[:SKILLS_LIMIT])
    if len(p.skills) > SKILLS_LIMIT:
        notes.append(f"LinkedIn accepts {SKILLS_LIMIT} skills; the first {SKILLS_LIMIT} of yours are listed.")
    if p.skills:
        notes.append("Pin the first three skills as your Top skills: they are the ones recruiters see first.")
    projects = tuple(
        ProjectText(
            pr.name,
            " ".join(x for x in (pr.description, *pr.bullets) if x)[:2000],
            pr.url,
            tuple(pr.tech),
        )
        for pr in p.projects
    )
    certifications = tuple(CertificationText(c.name, c.issuer, c.date, c.url) for c in p.certifications)
    return LinkedInKit(
        _headline(p, notes),
        _about(p, notes),
        experience,
        education,
        skills,
        projects,
        certifications,
        tuple(dict.fromkeys(notes)),
    )
