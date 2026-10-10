"""Recruiter outreach: LinkedIn people-search links and email drafts built from the user's REAL CV facts.

Deliberately NOT done (the old app did it): guessing addresses like hr@company.com. Guessed addresses are mostly
wrong and sending mail to strangers' guessed inboxes is poor practice; use the search links to find the right person
and reach out through LinkedIn or an address the company publishes.

Drafts are deterministic and contain NO placeholders: optional details (`hook`, `interview_topic`) are simply left out
when the user does not provide them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode

from careerforge.ats.match import experience_months, starts_with_action_verb
from careerforge.ats.report import AtsReport
from careerforge.models import Profile
from careerforge.text import clean_text

SEARCH_TITLES = ("Technical Recruiter", "Talent Acquisition", "Hiring Manager", "Engineering Manager")
NOTE_LIMIT = 300  # LinkedIn connection notes are capped at 300 characters


@dataclass(frozen=True)
class Email:
    subject: str
    body: str


def linkedin_people_search(company: str, titles: tuple[str, ...] = SEARCH_TITLES) -> list[tuple[str, str]]:
    """[(label, url)] for people-search pages at `company`. Query text is URL-encoded, never concatenated."""
    name = clean_text(company)[:80]
    if not name:
        return []
    return [
        (
            title,
            "https://www.linkedin.com/search/results/people/?"
            + urlencode({"keywords": f"{title} {name}", "origin": "GLOBAL_SEARCH_HEADER"}),
        )
        for title in titles
    ]


def _first_sentence(text: str, limit: int = 160) -> str:
    sentence = re.split(r"(?<=[.!?])\s", clean_text(text), maxsplit=1)[0].rstrip(".")
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rsplit(" ", 1)[0] + "…"


def best_achievement(profile: Profile, report: AtsReport | None = None) -> str:
    """The user's own most relevant measurable bullet, verbatim (first sentence). '' if there is none."""
    wanted = {m.requirement.term.lower() for m in (report.matches if report else ())}
    best, best_score = "", 0.0
    for e in profile.experience:
        for b in e.bullets:
            score = (
                2.0 * bool(re.search(r"\d", b)) + 1.0 * starts_with_action_verb(b) + sum(t in b.lower() for t in wanted)
            )
            if score > best_score:
                best, best_score = b, score
    return _first_sentence(best) if best_score >= 2 else ""


def _as_clause(bullet: str) -> str:
    """'Cut p95 latency by 40%' -> 'For example, I cut p95 latency by 40%.' (bullets start with a past-tense verb)."""
    if not bullet:
        return ""
    if starts_with_action_verb(bullet):
        return f"For example, I {bullet[0].lower()}{bullet[1:]}."
    return f"One example from my work: {bullet}."


def _skills_line(profile: Profile, report: AtsReport | None) -> str:
    if report:
        applied = [
            m.requirement.term for m in report.matches if "experience" in m.where and m.requirement.kind == "skill"
        ]
        if applied:
            return ", ".join(applied[:4])
    return ", ".join(profile.skills[:4])


def _letter(*blocks: str) -> str:
    """Join paragraphs, dropping empty ones, so an optional detail that is absent leaves no gap or placeholder."""
    return "\n\n".join(b for b in blocks if b)


def _sentences(*parts: str) -> str:
    return " ".join(x for x in parts if x)


def build_emails(
    profile: Profile,
    company: str,
    role: str,
    *,
    report: AtsReport | None = None,
    recipient: str = "",
    hook: str = "",
    interview_topic: str = "",
    today: date | None = None,
) -> dict[str, Email]:
    """cold_email, follow_up_1 (day 7), follow_up_2 (day 14), thank_you and a LinkedIn connection note."""
    p = profile.exportable()
    company, role = clean_text(company)[:80], clean_text(role)[:100]
    to = clean_text(recipient)
    greeting = f"Dear {to}," if to else "Hello,"
    name, c = p.name, p.contact
    years = round(experience_months(p, today) / 12)
    title = p.headline or (p.experience[0].title if p.experience else "")
    intro = _sentences(f"I'm {name}" + (f", a {title}" if title else ""), "").rstrip()
    intro += f" with {years} years of experience." if years >= 1 else "."
    skills = _skills_line(p, report)
    achievement = best_achievement(p, report)
    sign = "\n".join(x for x in (name, c.email, c.phone, c.linkedin) if x)
    topic = clean_text(interview_topic)

    about_role = f"the {role} role at {company}" if role else f"opportunities at {company}"
    cold = _letter(
        greeting,
        _sentences(f"I'm writing about {about_role}.", intro),
        _sentences(
            clean_text(hook),
            _as_clause(achievement),
            f"I work mainly with {skills}." if skills else "",
        ),
        "I've attached my CV and would welcome a short conversation about how I could contribute.",
        f"Thank you for your time,\n{sign}",
    )
    fit = f", and my experience with {skills} fits what the role involves" if skills else ""
    follow1 = _letter(
        greeting,
        f"I'm following up on my application for {about_role} that I sent last week.",
        f"I remain very interested{fit}. Happy to share anything else that would help.",
        f"Thank you,\n{sign}",
    )
    follow2 = _letter(
        greeting,
        f"One last note about {about_role}.",
        "If the timing isn't right, I'd be glad to be considered for future openings. "
        "Thank you for your consideration either way.",
        f"Best regards,\n{sign}",
    )
    thanks = _letter(
        greeting,
        _sentences(
            f"Thank you for taking the time to speak with me about {about_role}.",
            f"I especially enjoyed our discussion of {topic}." if topic else "",
        ),
        f"The conversation reinforced my interest in joining {company}. "
        "Please let me know if I can provide anything further.",
        f"Best regards,\n{sign}",
    )
    note = _sentences(
        f"Hello, I'm {name}" + (f", a {title}." if title else "."),
        f"I'm exploring {about_role} and would value connecting.",
    )
    tag = f": {role}" if role else ""
    return {
        "cold_email": Email((f"{role} application - {name}" if role else f"Introduction - {name}")[:70], cold),
        "follow_up_1": Email(f"Following up{tag} - {name}"[:70], follow1),
        "follow_up_2": Email(f"Final follow-up{tag} - {name}"[:70], follow2),
        "thank_you": Email(f"Thank you{tag}"[:70], thanks),
        "linkedin_note": Email("", note[:NOTE_LIMIT]),
    }
