"""Matching a Profile against a JobDescription, with EVIDENCE of where each requirement is satisfied.

A keyword that only sits in the skills list is weaker evidence than one shown in an experience/project bullet, so
stuffing the skills list does not buy a high score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from careerforge import skills as taxonomy
from careerforge.ats.jd import JobDescription, Requirement
from careerforge.models import Profile
from careerforge.nlp import content_tokens, normalize, stem
from careerforge.text import date_key

QUALITY_APPLIED = 1.0  # shown in an experience/project bullet
QUALITY_SKILLS_ONLY = 0.7  # only listed in the skills section
QUALITY_SKILLS_ONLY_STUFFED = 0.5  # ...in a list so long it looks stuffed
QUALITY_SUMMARY_ONLY = 0.6
STUFFED_SKILLS = 25
SENIORITY = frozenset("senior junior lead principal staff head chief associate intern trainee sr jr entry".split())


IMPLIED_DISCOUNT = 0.85  # satisfied through a related skill (Flask -> Python), so a little less certain


@dataclass(frozen=True)
class Match:
    requirement: Requirement
    quality: float
    where: tuple[str, ...]
    implied_by: str | None = None  # set when the requirement is met through a related skill, not named directly


def _applied_text(profile: Profile) -> str:
    parts = []
    for e in profile.experience:
        parts += [e.title, *e.bullets]
    for p in profile.projects:
        parts += [p.name, p.description, *p.bullets]
    return "\n".join(x for x in parts if x)


def _skills_by_location(profile: Profile) -> dict[str, set[str]]:
    """Which taxonomy skills the profile shows, and where (skills list / experience-and-projects / summary)."""
    listed = {taxonomy.canonicalize(s) for s in profile.skills} | {
        taxonomy.canonicalize(t) for p in profile.projects for t in p.tech
    }
    return {
        "skills": listed,
        "experience": set(taxonomy.find_skills(_applied_text(profile))),
        "summary": set(taxonomy.find_skills(f"{profile.summary}\n{profile.headline}")),
    }


def _location_flags(profile: Profile, req: Requirement, by_loc: dict[str, set[str]]) -> tuple[set[str], str | None]:
    """(locations where the requirement is evidenced, the implying skill if it is only met indirectly)."""
    if req.kind == "skill":
        direct = {loc for loc, found in by_loc.items() if req.term in found}
        if direct:
            return direct, None
        for loc, found in by_loc.items():
            if via := taxonomy.implied_by(req.term, found):
                implied_where = {name for name, skills in by_loc.items() if via in skills}
                return implied_where or {loc}, via
        return set(), None
    needle = {stem(t) for t in content_tokens(req.term)}
    where: set[str] = set()
    if needle:
        for label, text in (
            ("experience", _applied_text(profile)),
            ("summary", f"{profile.summary}\n{profile.headline}"),
            ("skills", " ".join(profile.skills)),
        ):
            if needle <= {stem(t) for t in content_tokens(text)}:
                where.add(label)
    return where, None


def match_requirements(profile: Profile, jd: JobDescription) -> tuple[tuple[Match, ...], tuple[Requirement, ...]]:
    """(matched, missing). `profile` should already be the exportable view."""
    stuffed = len(profile.skills) > STUFFED_SKILLS
    by_loc = _skills_by_location(profile)
    matched: list[Match] = []
    missing: list[Requirement] = []
    for req in jd.requirements:
        where, via = _location_flags(profile, req, by_loc)
        if not where:
            missing.append(req)
            continue
        if "experience" in where:
            quality = QUALITY_APPLIED
        elif "skills" in where:
            quality = QUALITY_SKILLS_ONLY_STUFFED if stuffed else QUALITY_SKILLS_ONLY
        else:
            quality = QUALITY_SUMMARY_ONLY
        if via:
            quality *= IMPLIED_DISCOUNT
        matched.append(Match(req, quality, tuple(sorted(where)), via))
    return tuple(matched), tuple(missing)


def coverage_score(matched: tuple[Match, ...], missing: tuple[Requirement, ...]) -> int | None:
    """Weighted share of requirements met, 0-100. None when the posting yielded no requirements."""
    total = sum(m.requirement.weight for m in matched) + sum(r.weight for r in missing)
    if total == 0:
        return None
    earned = sum(m.requirement.weight * m.quality for m in matched)
    return round(100 * earned / total)


def experience_months(profile: Profile, today: date | None = None) -> int:
    """Months of work covered by dated roles, counting overlapping roles once. Year-only dates span Jan..Dec."""
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    spans = []
    for e in profile.experience:
        if not e.dates.start:
            continue
        start = date_key(e.dates.start)
        end = now if e.dates.current else (date_key(e.dates.end, end=True) if e.dates.end else start)
        if end >= start:
            spans.append((start, min(end, now)))
    total, cursor = 0, -1
    for start, end in sorted(spans):
        start = max(start, cursor + 1)
        if end >= start:
            total += end - start + 1
            cursor = end
    return total


def role_alignment(profile: Profile, jd: JobDescription) -> tuple[int | None, str]:
    """Share of the posting's title words (minus seniority) found in the candidate's headline and recent titles."""
    wanted = [t for t in content_tokens(jd.title) if t not in SENIORITY]
    if not wanted:
        return None, "The posting has no clear job title"
    have_text = " ".join([profile.headline, *[e.title for e in profile.experience[:3]]])
    squashed = normalize(have_text).replace(" ", "")
    have = {stem(t) for t in content_tokens(have_text)}
    hits = [t for t in wanted if stem(t) in have or t in squashed]
    return round(
        100 * len(hits) / len(wanted)
    ), f"{len(hits)} of {len(wanted)} title words found in your headline/recent roles"


FIRST_PERSON = re.compile(r"\b(?:I|[Mm]y|[Mm]e|[Mm]yself)\b")
ACTION_VERBS = frozenset(
    """achieved architected automated built championed collaborated conducted configured consolidated created cut
    decreased delivered deployed designed developed directed drove enabled engineered established executed expanded
    founded generated grew guided implemented improved increased integrated introduced launched led maintained managed
    mentored migrated modernized negotiated optimized orchestrated organized owned partnered pioneered planned presented
    produced reduced refactored released replaced researched resolved restructured saved scaled secured shipped
    simplified
    spearheaded standardized streamlined supervised trained transformed upgraded wrote analyzed analysed administered
    coordinated defined diagnosed documented evaluated forecasted identified initiated investigated monitored operated
    prototyped reviewed tested validated visualized won""".split()
)


def starts_with_action_verb(bullet: str) -> bool:
    first = re.match(r"[A-Za-z]+", bullet)
    if not first:
        return False
    word = first.group(0).lower()
    return word in ACTION_VERBS or (word.endswith("ed") and len(word) > 4 and first.group(0)[0].isupper())
