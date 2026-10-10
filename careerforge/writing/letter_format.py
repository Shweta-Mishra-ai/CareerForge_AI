"""The shape of a business cover letter, assembled by code so that no model can get the format wrong.

Conventions encoded here (widely taught; they are conventions, not laws):
* sender block, date, recipient block, subject line, salutation, 3-5 short paragraphs, closing, name, enclosure line;
* a named salutation when the recipient is known, "Dear Hiring Manager" otherwise (never "To whom it may concern");
* "Yours sincerely" (named) / "Yours faithfully" (unnamed) in British style, "Sincerely" in US style;
* the date written the way the reader's country writes it.
Nothing here invents content: every field is either the candidate's own data or something they typed in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from careerforge.models import Profile
from careerforge.text import clean_text

DateStyle = Literal["us", "uk", "iso"]
Tone = Literal["standard", "concise", "warm"]
_NAME = re.compile(r"[^\W\d_](?:[^\W\d_]|[ .'\-]){0,59}", re.UNICODE)  # letters, spaces and . ' - only; at most 60


@dataclass(frozen=True)
class LetterDetails:
    company: str = ""
    role: str = ""
    recipient_name: str = ""  # as the candidate would write it: "Ms. Rao", "Priya Rao"
    recipient_title: str = ""  # "Head of Engineering"
    company_city: str = ""
    job_ref: str = ""  # requisition / reference number from the posting
    source: str = ""  # where the posting was found: "LinkedIn", "your careers page", "a referral from Asha Menon"
    availability: str = ""  # the candidate's own words: "I can start on 1 November."
    hook: str = ""  # the candidate's own reason for wanting this company (one sentence)
    date_style: DateStyle = "us"
    tone: Tone = "standard"
    enclosure: bool = True

    def cleaned(self) -> LetterDetails:
        def c(value: str, limit: int) -> str:
            return clean_text(value)[:limit]

        name = c(self.recipient_name, 60)
        if name and not _NAME.fullmatch(name):
            raise ValueError("The recipient's name may only contain letters, spaces and . ' -")
        return LetterDetails(
            company=c(self.company, 80),
            role=c(self.role, 100),
            recipient_name=name,
            recipient_title=c(self.recipient_title, 80),
            company_city=c(self.company_city, 60),
            job_ref=c(self.job_ref, 40),
            source=c(self.source, 80),
            availability=c(self.availability, 160),
            hook=c(self.hook, 240),
            date_style=self.date_style,
            tone=self.tone,
            enclosure=self.enclosure,
        )


@dataclass(frozen=True)
class Letter:
    sender_name: str
    sender_lines: tuple[str, ...]
    date_text: str
    recipient_lines: tuple[str, ...]
    subject: str
    salutation: str
    paragraphs: tuple[str, ...]
    closing: str
    enclosure: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def body(self) -> str:
        return "\n\n".join(self.paragraphs)

    def text(self) -> str:
        parts = [self.sender_name, *self.sender_lines, "", self.date_text]
        if self.recipient_lines:
            parts += ["", *self.recipient_lines]
        if self.subject:
            parts += ["", self.subject]
        parts += ["", self.salutation, "", self.body, "", self.closing, self.sender_name]
        if self.enclosure:
            parts += ["", self.enclosure]
        return "\n".join(parts).strip() + "\n"


def format_date(day: date, style: DateStyle) -> str:
    if style == "uk":
        return f"{day.day} {day:%B %Y}"
    if style == "iso":
        return day.isoformat()
    return f"{day:%B} {day.day}, {day.year}"


def closing_for(details: LetterDetails) -> str:
    named = bool(details.recipient_name)
    if details.tone == "warm":
        return "Kind regards,"
    if details.date_style == "uk":
        return "Yours sincerely," if named else "Yours faithfully,"
    return "Sincerely,"


def assemble_letter(profile: Profile, paragraphs: list[str], details: LetterDetails, today: date) -> Letter:
    """Wrap body paragraphs in the standard format. The candidate's availability, if given, joins the last paragraph."""
    d = details.cleaned()
    c = profile.contact
    sender = tuple(x for x in (" | ".join(y for y in (c.email, c.phone) if y), c.location, c.linkedin) if x)
    recipient = tuple(x for x in (d.recipient_name, d.recipient_title, d.company, d.company_city) if x)
    ref = f" (Ref: {d.job_ref})" if d.job_ref else ""
    subject = f"Re: Application for {d.role}{ref}" if d.role else (f"Re: Application{ref}" if d.job_ref else "")
    body = list(paragraphs)
    if d.availability and body:
        sentence = d.availability if re.search(r"[.!?]$", d.availability) else d.availability + "."
        body[-1] = f"{body[-1]} {sentence}"
    return Letter(
        sender_name=profile.name,
        sender_lines=sender,
        date_text=format_date(today, d.date_style),
        recipient_lines=recipient,
        subject=subject,
        salutation=f"Dear {d.recipient_name}," if d.recipient_name else "Dear Hiring Manager,",
        paragraphs=tuple(body),
        closing=closing_for(d),
        enclosure="Enclosure: Curriculum Vitae" if d.enclosure else "",
    )
