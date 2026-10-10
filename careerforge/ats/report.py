"""ATS v2 report: a score built from visible components, plus concrete, honest fixes.

Nothing here calls an LLM. Weights are our design choices (not fitted to any vendor's ATS), which is why the report
carries a disclaimer and shows every component, so users can see exactly where points come from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from careerforge.ats import checks as chk
from careerforge.ats import match as mt
from careerforge.ats.jd import JobDescription, Requirement, parse_job_description
from careerforge.models import Profile

WEIGHTS = {"keywords": 40, "experience": 10, "role": 10, "structure": 15, "parse": 10, "quality": 15}
LABELS = {
    "keywords": "Keyword match",
    "experience": "Experience level",
    "role": "Role alignment",
    "structure": "Structure & completeness",
    "parse": "PDF readability",
    "quality": "Content quality",
}
DISCLAIMER = (
    "This is an estimate from transparent rules, not the score of any specific employer's ATS (Workday, Greenhouse, "
    "Lever and others each parse differently). Use it to find real gaps; never add skills you do not have."
)
Severity = Literal["high", "medium", "low"]
_SEV = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    score: int | None  # None = could not be assessed (excluded from the total)
    weight: int
    detail: str = ""
    checks: tuple[chk.Check, ...] = ()


@dataclass(frozen=True)
class Fix:
    severity: Severity
    area: str
    message: str
    path: str = ""


@dataclass(frozen=True)
class AtsReport:
    kind: Literal["match", "quality"]  # "match" = scored against a posting, "quality" = no posting given
    overall: int
    band: str
    components: tuple[Component, ...]
    matches: tuple[mt.Match, ...] = ()
    missing: tuple[Requirement, ...] = ()
    fixes: tuple[Fix, ...] = ()
    job_title: str = ""
    notes: tuple[str, ...] = ()
    disclaimer: str = DISCLAIMER

    def component(self, key: str) -> Component | None:
        return next((c for c in self.components if c.key == key), None)


def _component(key: str, score: int | None, detail: str, checks: tuple[chk.Check, ...] = ()) -> Component:
    return Component(key, LABELS[key], score, WEIGHTS[key], detail, checks)


def band(score: int) -> str:
    return "Strong" if score >= 80 else "Good" if score >= 65 else "Fair" if score >= 50 else "Needs work"


def _overall(components: list[Component]) -> int:
    scored = [c for c in components if c.score is not None]
    total = sum(c.weight for c in scored)
    return round(sum(c.score * c.weight for c in scored) / total) if total else 0  # type: ignore[operator]


def _fixes(
    profile: Profile,
    jd: JobDescription | None,
    matches: tuple[mt.Match, ...],
    missing: tuple[Requirement, ...],
    comps: dict[str, Component],
    weak_bullets: tuple[tuple[str, str], ...],
    parse_findings: tuple[str, ...],
) -> list[Fix]:
    fixes: list[Fix] = []
    honest = "If you have real experience with it, add it to Skills and show it in a bullet; if not, do not claim it."
    for req in sorted(missing, key=lambda r: -r.weight)[:8]:
        if req.importance != "preferred":
            severity: Severity = "high" if req.importance == "required" else "medium"
            fixes.append(Fix(severity, "keywords", f'The posting asks for "{req.term}". {honest}', req.term))
    for req in [r for r in missing if r.importance == "preferred"][:3]:
        fixes.append(
            Fix("low", "keywords", f'Nice-to-have: "{req.term}". Mention it only if you genuinely have it.', req.term)
        )
    for m in [m for m in matches if m.where == ("skills",)][:5]:
        msg = f'"{m.requirement.term}" is only listed under Skills. Add a bullet showing where you used it.'
        fixes.append(Fix("medium", "keywords", msg, m.requirement.term))
    exp = comps.get("experience")
    if jd and exp and exp.score is not None and exp.score < 100:
        msg = (
            f"The posting asks for {jd.min_years}+ years. {exp.detail}. Do not inflate your dates; "
            "highlight your most relevant projects and results instead."
        )
        fixes.append(Fix("medium", "experience", msg))
    if jd and jd.degree and not profile.education:
        fixes.append(
            Fix(
                "medium",
                "structure",
                f"The posting mentions a {jd.degree}-level degree; add your education.",
                "education",
            )
        )
    for c in comps["structure"].checks:
        if not c.passed:
            fixes.append(
                Fix("high" if c.points >= 2 else "low", "structure", f"{c.label}: missing. {c.detail}".strip())
            )
    for path, text in weak_bullets[:5]:
        short = text if len(text) <= 70 else text[:67] + "…"
        fixes.append(
            Fix(
                "low", "quality", f'Add a measurable result (number, %, time, scale) to "{short}" - only if true.', path
            )
        )
    fixes += [Fix("high", "parse", finding) for finding in parse_findings]
    return sorted(fixes, key=lambda f: _SEV[f.severity])


def analyze(
    profile: Profile,
    job_text: str | None = None,
    *,
    pdf: bytes | None = None,
    today: date | None = None,
) -> AtsReport:
    """Score `profile` (its exportable view) against a posting, or for general quality when no posting is given.

    Pass the exported `pdf` bytes to include a real readability check of that file.
    """
    p = profile.exportable()
    notes: list[str] = []
    if dropped := len(profile.pending_items()):
        notes.append(f"{dropped} unconfirmed AI suggestion(s) are not counted: they will not be in the exported CV")

    jd = parse_job_description(job_text) if job_text and job_text.strip() else None
    comps: dict[str, Component] = {}
    matches: tuple[mt.Match, ...] = ()
    missing: tuple[Requirement, ...] = ()

    if jd:
        matches, missing = mt.match_requirements(p, jd)
        kw = mt.coverage_score(matches, missing)
        if kw is None:
            notes.append(
                "No skills or requirements could be found in the posting; paste more of it for a keyword score"
            )
            comps["keywords"] = _component("keywords", None, "No requirements found in the posting")
        else:
            total = len(matches) + len(missing)
            detail = f"{len(matches)} of {total} requirements found (weighted by importance and by evidence)"
            comps["keywords"] = _component("keywords", kw, detail)
        if jd.min_years:
            have = mt.experience_months(p, today) / 12
            score = min(100, round(100 * have / jd.min_years))
            comps["experience"] = _component("experience", score, f"Your dated roles add up to about {have:.1f} years")
        else:
            comps["experience"] = _component("experience", None, "The posting states no years of experience")
        role_score, role_detail = mt.role_alignment(p, jd)
        comps["role"] = _component("role", role_score, role_detail)

    s_checks = chk.structure_checks(p)
    passed = sum(c.passed for c in s_checks)
    comps["structure"] = _component(
        "structure", chk.score_checks(s_checks), f"{passed} of {len(s_checks)} checks passed", tuple(s_checks)
    )

    parse_findings: tuple[str, ...] = ()
    if pdf is not None:
        parsed = chk.check_pdf(pdf, p)
        parse_findings = parsed.findings
        notes.extend(parsed.notes)
        comps["parse"] = _component("parse", parsed.score, "Checked on the actual PDF file", parsed.checks)
    else:
        comps["parse"] = _component("parse", None, "Export a PDF to check how ATS software will read it")

    q = chk.quality(p)
    q_detail = (
        "Numbers, action verbs, length and tone of your bullets" if q.score is not None else "No bullets to assess yet"
    )
    comps["quality"] = _component("quality", q.score, q_detail, q.checks)

    ordered = [comps[k] for k in WEIGHTS if k in comps]
    overall = _overall(ordered)
    return AtsReport(
        kind="match" if jd else "quality",
        overall=overall,
        band=band(overall),
        components=tuple(ordered),
        matches=matches,
        missing=missing,
        fixes=tuple(_fixes(p, jd, matches, missing, comps, q.weak_bullets, parse_findings)),
        job_title=jd.title if jd else "",
        notes=tuple(notes),
    )


def compare(
    profile: Profile, postings: dict[str, str], *, pdf: bytes | None = None, today: date | None = None
) -> list[tuple[str, AtsReport]]:
    """Score one profile against several postings, best fit first. Keys are labels chosen by the caller."""
    results = [(name, analyze(profile, text, pdf=pdf, today=today)) for name, text in postings.items()]
    return sorted(results, key=lambda item: -item[1].overall)
