"""Recruiter outreach: LinkedIn people-search links and email drafts built from the user's REAL CV facts.

Deliberately NOT done (the old app did it): guessing addresses like hr@company.com. Guessed addresses are mostly
wrong and sending mail to strangers' guessed inboxes is poor practice; use the search links to find the right person
and reach out through LinkedIn or an address the company publishes.

Drafts are deterministic and contain NO placeholders: optional details (`hook`, `interview_topic`) are simply left out
when the user does not provide them. Every draft can be checked with `lint_email` against widely repeated cold-email
conventions (short subject, short body, one clear ask). Those limits are conventions from career-advice sources, not
measured results; the report says so.
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
NOTE_LIMIT = (
    200  # connection notes: LinkedIn has capped these at 200-300 characters over time; stay under the lower one
)
NOTE_KINDS = frozenset({"linkedin_note", "linkedin_accepted"})  # short messages: no subject, no signature block


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


SUBJECT_MAX = 60  # mobile inboxes cut longer subjects; a widely repeated rule of thumb, not a measured limit
BODY_WORDS_MAX = {"cold_email": 150, "follow_up_1": 100, "follow_up_2": 80, "referral_request": 150}
DEFAULT_BODY_WORDS_MAX = 150
_ASK = re.compile(
    r"\b(would you|could you|can you|please (?:let|send|share|confirm)|i(?:'d| would) (?:welcome|value|appreciate)"
    r"|would be glad|would love)\b",
    re.I,
)
_PLACEHOLDER = re.compile(r"\[[^\]]*\]|\{[^}]*\}|<[A-Za-z/][^>]*>|\bTODO\b|\bXXX\b|lorem ipsum", re.I)


@dataclass(frozen=True)
class EmailCheck:
    key: str
    label: str
    passed: bool
    detail: str = ""


def attachment_name(profile: Profile, kind: str = "CV", ext: str = "pdf") -> str:
    """`First_Last_CV.pdf`: the file name a recruiter sees in their inbox. Falls back to `CV.pdf` for names with no
    Latin letters (the file name is for people, so it is never left empty or made of path characters)."""
    stem = re.sub(r"[^A-Za-z0-9]+", "_", profile.name or "").strip("_")[:50]
    kind = re.sub(r"[^A-Za-z0-9]+", "_", kind).strip("_") or "CV"
    ext = re.sub(r"[^a-z0-9]", "", ext.lower()) or "pdf"
    return f"{stem}_{kind}.{ext}" if stem else f"{kind}.{ext}"


def lint_email(mail: Email, kind: str = "cold_email") -> list[EmailCheck]:
    """Checks against common outreach advice. `kind` picks the length limit (follow-ups are shorter)."""
    words = len(mail.body.split())
    limit = BODY_WORDS_MAX.get(kind, DEFAULT_BODY_WORDS_MAX)
    out: list[EmailCheck] = []
    if kind not in NOTE_KINDS:
        out.append(
            EmailCheck(
                "subject",
                f"Subject is {SUBJECT_MAX} characters or fewer",
                0 < len(mail.subject) <= SUBJECT_MAX,
                f"{len(mail.subject)} characters.",
            )
        )
    out.append(EmailCheck("length", f"Body is {limit} words or fewer", words <= limit, f"{words} words."))
    asks = len(_ASK.findall(mail.body)) + mail.body.count("?")
    out.append(EmailCheck("one_ask", "Makes one clear request", asks <= 2, f"{asks} request-like phrase(s)."))
    out.append(
        EmailCheck(
            "no_placeholders",
            "No placeholders left",
            not _PLACEHOLDER.search(mail.subject + mail.body),
            "Fill brackets.",
        )
    )
    if kind not in NOTE_KINDS:
        out.append(
            EmailCheck(
                "signature",
                "Signed with a way to reach you",
                bool(re.search(r"@|\+?\d[\d\s().-]{6,}", mail.body.rsplit("\n\n", 1)[-1])),
                "Add your email or phone under your name.",
            )
        )
    return out


def linkedin_boolean(company: str, titles: tuple[str, ...] = SEARCH_TITLES, *, keywords: str = "") -> str:
    """A Boolean people-search string: ("Technical Recruiter" OR "Talent Acquisition") AND "Company" [AND "extra"].
    LinkedIn documents quotes, AND/OR/NOT (upper case) and brackets in its search; this tool has not run it live."""
    name = clean_text(company)[:80].replace('"', "")
    if not name:
        return ""
    ors = " OR ".join(f'"{t}"' for t in titles)
    extra = clean_text(keywords)[:60].replace('"', "")
    return f'({ors}) AND "{name}"' + (f' AND "{extra}"' if extra else "")


@dataclass(frozen=True)
class Moment:
    """Facts only the user knows. Anything left empty is simply omitted from a draft, never invented."""

    contact: str = ""  # a person to refer you / the recruiter who wrote to you
    how_known: str = ""  # "we worked together on the payments team"
    when: str = ""  # "Tuesday 14 October, 3 pm IST"
    availability: str = ""  # "I can speak any weekday after 4 pm"
    deadline: str = ""  # "Friday 17 October"
    notice: str = ""  # "My notice period is 30 days"
    reason: str = ""  # the user's own reason for declining


def build_moment_emails(
    profile: Profile, company: str, role: str, moment: Moment | None = None, *, report: AtsReport | None = None
) -> dict[str, Email]:
    """Replies for the other moments of a job search. Each uses only the CV and what the user typed."""
    p = profile.exportable()
    m = moment or Moment()
    company, role = clean_text(company)[:80], clean_text(role)[:100]
    who = clean_text(m.contact)
    name, c = p.name, p.contact
    sign = "\n".join(x for x in (name, c.email, c.phone, c.linkedin) if x)
    about = f"the {role} role at {company}" if role else f"a role at {company}"
    greeting = f"Hello {who}," if who else "Hello,"
    achievement = best_achievement(p, report)
    c_ = lambda x: clean_text(x)  # noqa: E731
    tag = f": {role}" if role else ""

    referral = _letter(
        greeting,
        _sentences(
            c_(m.how_known).rstrip(".") + "." if m.how_known else "",
            f"I'm applying for {about} and saw that you work at {company}.",
        ),
        _sentences(_as_clause(achievement), "I've attached my CV."),
        "Would you be open to referring me, or pointing me to the right person? No problem at all if not.",
        f"Thank you,\n{sign}",
    )
    reply = _letter(
        greeting,
        f"Thank you for reaching out about {about}. I'm interested and would like to learn more.",
        _sentences(
            c_(m.availability).rstrip(".") + "." if m.availability else "",
            c_(m.notice).rstrip(".") + "." if m.notice else "",
        ),
        "My CV is attached. Please let me know the next step.",
        f"Best regards,\n{sign}",
    )
    confirm = _letter(
        greeting,
        _sentences(
            "Thank you for the invitation.",
            f"I confirm our interview for {about}" + (f" on {c_(m.when)}." if m.when else "."),
        ),
        "Please tell me if I should prepare or bring anything.",
        f"Best regards,\n{sign}",
    )
    offer = _letter(
        greeting,
        f"Thank you for offering me {about}. I'm delighted and appreciate the time the team invested.",
        _sentences(
            "Could you send the offer details in writing?",
            f"I will reply by {c_(m.deadline)}." if m.deadline else "",
        ),
        f"Best regards,\n{sign}",
    )
    decline = _letter(
        greeting,
        f"Thank you for considering me for {about} and for your time.",
        _sentences(
            "After careful thought, I have decided not to continue.",
            c_(m.reason).rstrip(".") + "." if m.reason else "",
        ),
        "I would be glad to stay in touch.",
        f"Kind regards,\n{sign}",
    )
    rejected = _letter(
        greeting,
        f"Thank you for letting me know about {about}, and for the time you spent on my application.",
        "If it is possible, I would value one or two lines of feedback. "
        "I would also like to be considered for future openings.",
        f"Best regards,\n{sign}",
    )
    accepted = _letter(
        f"Hi {who}," if who else "Hi,",
        f"Thanks for connecting. I'm interested in {about}.",
        "Would you be open to a short chat about what the team looks for?",
        name,
    )
    return {
        "referral_request": Email(f"Referral request{tag}"[:SUBJECT_MAX], referral),
        "recruiter_reply": Email(f"Re: {role or 'Your message'} - {name}"[:SUBJECT_MAX], reply),
        "interview_confirmation": Email(f"Interview confirmation{tag} - {name}"[:SUBJECT_MAX], confirm),
        "offer_acknowledgement": Email(f"Thank you for the offer{tag}"[:SUBJECT_MAX], offer),
        "decline": Email(f"Withdrawing my application{tag}"[:SUBJECT_MAX], decline),
        "after_rejection": Email(f"Thank you{tag}"[:SUBJECT_MAX], rejected),
        "linkedin_accepted": Email("", accepted[:NOTE_LIMIT]),
    }


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
        "cold_email": Email((f"{role} application - {name}" if role else f"Introduction - {name}")[:SUBJECT_MAX], cold),
        "follow_up_1": Email(f"Following up{tag} - {name}"[:SUBJECT_MAX], follow1),
        "follow_up_2": Email(f"Final follow-up{tag} - {name}"[:SUBJECT_MAX], follow2),
        "thank_you": Email(f"Thank you{tag}"[:SUBJECT_MAX], thanks),
        "linkedin_note": Email("", note[:NOTE_LIMIT]),
    }
