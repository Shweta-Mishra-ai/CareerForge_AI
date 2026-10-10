"""A cover letter without AI: the candidate's own evidence arranged in the standard structure.

It will not read like a poem, and it says so (the lint flags a short letter). What it does is the part that matters to a
recruiter: the role and company named, the posting's main requirements each answered with a real, measurable example,
and a clear next step. Everything comes from the candidate's CV and the details they typed in.
"""

from __future__ import annotations

from datetime import date

from careerforge.ats import match as mt
from careerforge.ats.jd import parse_job_description
from careerforge.ats.report import analyze
from careerforge.models import Profile
from careerforge.writing.cover_letter import LetterDraft, _company
from careerforge.writing.evidence import evidence_pairs
from careerforge.writing.letter_format import LetterDetails, assemble_letter
from careerforge.writing.letter_lint import lint_letter

LEADS = ("Your posting asks for {r}.", "You also look for {r}.", "{r} is another requirement of the role.")


def _join(items: list[str]) -> str:
    """['a', 'b', 'c'] -> 'a, b and c'"""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def _opening(p: Profile, d: LetterDetails, years: int) -> str:
    title = p.headline or (p.experience[0].title if p.experience else "")
    via = f" through {d.source}" if d.source else ""
    role = f"the {d.role} position" if d.role else "an opportunity"
    where = f" at {d.company}" if d.company else ""
    first = f"I am applying for {role}{where}, which I found{via}." if d.source else f"I am applying for {role}{where}."
    who = f"I am a {title}" if title else "I bring experience"
    span = f" with {years} years of experience" if years >= 1 else ""
    skills = _join(p.skills[:3])
    focus = f", working mainly with {skills}" if skills else ""
    return f"{first} {who}{span}{focus}."


def build_basic_letter(
    profile: Profile, job_text: str, *, details: LetterDetails | None = None, today: date | None = None
) -> LetterDraft:
    p = profile.exportable()
    today = today or date.today()
    jd = parse_job_description(job_text)
    d = (details or LetterDetails()).cleaned()
    d = LetterDetails(**{**d.__dict__, "company": d.company or _company(job_text), "role": d.role or jd.title})
    years = round(mt.experience_months(p, today) / 12)
    report = analyze(p, job_text, today=today)
    pairs = evidence_pairs(p, report.matches)

    paragraphs = [_opening(p, d, years)]
    if pairs:
        paragraphs.append(
            " ".join(f"{LEADS[k % len(LEADS)].format(r=e.requirement)} {e.as_sentence()}" for k, e in enumerate(pairs))
        )
    if d.hook:
        paragraphs.append(d.hook if d.hook.endswith((".", "!", "?")) else d.hook + ".")
    where = f" to {d.company}" if d.company else ""
    start = d.availability if d.availability.endswith((".", "!", "?")) or not d.availability else d.availability + "."
    paragraphs.append(
        " ".join(
            x
            for x in (
                f"I would welcome the chance to discuss how my experience could contribute{where}.",
                start,
                "Thank you for your time and consideration.",
            )
            if x
        )
    )
    d_layout = LetterDetails(**{**d.__dict__, "availability": ""})  # already placed before the thanks
    letter = assemble_letter(p, paragraphs, d_layout, today)
    checks = lint_letter(letter, p, job_text, company=d.company, role=d.role)
    return LetterDraft(letter, (), tuple(checks), tuple(pairs))
