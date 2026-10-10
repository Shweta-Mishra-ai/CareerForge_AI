"""Data behind the analytics dashboard and the section-level tips. Plain data in, plain data out (charts are UI)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from careerforge import skills as taxonomy
from careerforge.ats import match as mt
from careerforge.ats.jd import parse_job_description
from careerforge.ats.report import AtsReport
from careerforge.models import Profile
from careerforge.text import date_key, display_date

ROLE_MIN_BULLETS = 2
LONG_BULLET = 220
GAP_MONTHS = 3


@dataclass(frozen=True)
class RadarAxis:
    category: str
    required: int  # posting requirements in this category
    matched: int  # of those, shown in the CV
    listed: int  # distinct skills the CV lists in this category


def skill_radar(profile: Profile, job_text: str | None = None) -> list[RadarAxis]:
    """Per-category skill coverage. Without a posting `required`/`matched` are 0 and only `listed` is filled."""
    p = profile.exportable()
    listed: dict[str, set[str]] = {}
    for skill in p.skills:
        listed.setdefault(taxonomy.category_of(skill), set()).add(skill)
    required: dict[str, int] = {}
    matched: dict[str, int] = {}
    if job_text and job_text.strip():
        hits, misses = mt.match_requirements(p, parse_job_description(job_text))
        for m in hits:
            if m.requirement.kind == "skill":
                cat = taxonomy.category_of(m.requirement.term)
                required[cat] = required.get(cat, 0) + 1
                matched[cat] = matched.get(cat, 0) + 1
        for r in misses:
            if r.kind == "skill":
                cat = taxonomy.category_of(r.term)
                required[cat] = required.get(cat, 0) + 1
    cats = [c for c in (*taxonomy.CATEGORY_ORDER, "Other") if c in listed or c in required]
    return [RadarAxis(c, required.get(c, 0), matched.get(c, 0), len(listed.get(c, ()))) for c in cats]


@dataclass(frozen=True)
class Span:
    label: str
    start: str
    end: str  # "" = ongoing
    months: int


@dataclass(frozen=True)
class Timeline:
    spans: tuple[Span, ...]
    gaps: tuple[str, ...]
    total_months: int


def timeline(profile: Profile, today: date | None = None) -> Timeline:
    p = profile.exportable()
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    spans = []
    for e in p.experience:
        if not e.dates.start:
            continue
        start = date_key(e.dates.start)
        end = now if e.dates.current else (date_key(e.dates.end, end=True) if e.dates.end else start)
        spans.append((start, min(end, now), e))
    spans.sort(key=lambda s: s[0])
    gaps = []
    for (_, prev_end, prev), (nxt_start, _, nxt) in zip(spans, spans[1:], strict=False):
        if nxt_start - prev_end - 1 >= GAP_MONTHS:
            gaps.append(
                f"{nxt_start - prev_end - 1} months between {prev.company or prev.title} and {nxt.company or nxt.title}"
            )
    out = tuple(
        Span(
            f"{e.title} @ {e.company}".strip(" @"),
            display_date(e.dates.start),
            "" if e.dates.current else display_date(e.dates.end),
            max(0, end - start + 1),
        )
        for start, end, e in spans
    )
    return Timeline(out, tuple(gaps), mt.experience_months(p, today))


@dataclass(frozen=True)
class HeatRow:
    term: str
    importance: str
    skills: int  # 1 if listed in Skills
    summary: int
    experience: int  # number of experience bullets/titles that mention it
    projects: int


def keyword_heat(profile: Profile, job_text: str) -> list[HeatRow]:
    """For each skill the posting asks for: where in the CV it appears, and how often."""
    p = profile.exportable()
    jd = parse_job_description(job_text)
    listed = {taxonomy.canonicalize(s) for s in p.skills}
    rows = []
    for req in jd.skills:
        in_summary = int(req.term in taxonomy.find_skills(f"{p.summary}\n{p.headline}"))
        exp = sum(req.term in taxonomy.find_skills(text) for e in p.experience for text in [e.title, *e.bullets])
        proj = sum(
            req.term in taxonomy.find_skills(text)
            for pr in p.projects
            for text in [pr.name, pr.description, *pr.bullets]
        )
        rows.append(HeatRow(req.term, req.importance, int(req.term in listed), in_summary, exp, proj))
    return rows


@dataclass(frozen=True)
class Tip:
    section: str  # experience[0] | skills | summary | contact | ...
    severity: str
    message: str


def section_tips(profile: Profile, report: AtsReport) -> list[Tip]:
    """Line-level advice per section: the report's fixes plus role-specific observations."""
    p = profile.exportable()
    tips = [
        Tip(f.path.split(".")[0] if f.path and f.area == "quality" else f.area, f.severity, f.message)
        for f in report.fixes
    ]
    for i, e in enumerate(p.experience):
        label = e.company or e.title or f"role {i + 1}"
        if len(e.bullets) < ROLE_MIN_BULLETS:
            tips.append(
                Tip(
                    f"experience[{i}]",
                    "medium",
                    f"{label}: add at least {ROLE_MIN_BULLETS} bullets describing results, not duties.",
                )
            )
        for j, b in enumerate(e.bullets):
            if len(b) > LONG_BULLET:
                tips.append(
                    Tip(
                        f"experience[{i}].bullets[{j}]",
                        "low",
                        f"{label}: this bullet is {len(b)} characters; split it or cut it to one idea.",
                    )
                )
    if p.summary and len(p.summary) > 600:
        tips.append(Tip("summary", "low", "Shorten the summary to 2-3 sentences (under 600 characters)."))
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(tips, key=lambda t: order.get(t.severity, 3))
