"""Deterministic quality checks for a cover letter, based on widely repeated recruiter guidance.

These are conventions, not laws, and no check here claims to predict whether a given employer will respond. Each check
says what it looked at, so the candidate can decide. Sources and confidence are listed in docs/STANDARDS.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from careerforge.ats.jd import parse_job_description
from careerforge.models import Profile
from careerforge.nlp import content_tokens
from careerforge.writing.letter_format import Letter

Severity = Literal["fix", "improve", "tip"]
WORDS_IDEAL = (250, 400)  # the commonly given range for one page: 3-5 paragraphs
WORDS_HARD = (150, 450)
PARAGRAPHS = (3, 5)
I_START_MAX = 0.5

# phrases hiring managers routinely name as filler (the list is deliberately short and uncontroversial)
CLICHES = (
    "i am writing to apply",
    "i am writing to express my interest",
    "to whom it may concern",
    "team player",
    "hard-working",
    "hardworking",
    "hard working",
    "go-getter",
    "self-starter",
    "think outside the box",
    "results-driven",
    "results driven",
    "detail-oriented",
    "detail oriented",
    "dynamic professional",
    "fast learner",
    "quick learner",
    "perfect candidate",
    "ideal candidate",
    "i am passionate",
    "passionate about",
    "synergy",
    "proven track record",
)
_CTA = re.compile(
    r"\b(?:discuss|conversation|interview|speak|talk|meet|connect|call|hear from you|chance to|opportunity to)\b", re.I
)
_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")


@dataclass(frozen=True)
class LetterCheck:
    key: str
    label: str
    passed: bool
    severity: Severity
    detail: str = ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")) if s.strip()]


def lint_letter(
    letter: Letter, profile: Profile, job_text: str, *, company: str = "", role: str = "", pages: int | None = None
) -> list[LetterCheck]:
    body = letter.body
    low = body.lower()
    words = len(body.split())
    out: list[LetterCheck] = []

    def add(key: str, label: str, ok: bool, severity: Severity, detail: str = "") -> None:
        out.append(LetterCheck(key, label, ok, severity, detail))

    lo, hi = WORDS_IDEAL
    hard_lo, hard_hi = WORDS_HARD
    add(
        "length",
        f"Length is {lo}-{hi} words",
        lo <= words <= hi,
        "fix" if not hard_lo <= words <= hard_hi else "improve",
        f"{words} words. Recruiters skim: one page, about {lo}-{hi} words.",
    )
    n = len(letter.paragraphs)
    add(
        "paragraphs",
        f"{PARAGRAPHS[0]}-{PARAGRAPHS[1]} short paragraphs",
        PARAGRAPHS[0] <= n <= PARAGRAPHS[1],
        "improve",
        f"{n} paragraph(s).",
    )
    if pages is not None:
        add("one_page", "Fits on one page", pages <= 1, "fix", f"The PDF is {pages} page(s). Shorten it.")

    if company:
        add("company", "Names the company", company.lower() in low, "fix", f"'{company}' is not mentioned in the body.")
    if role:
        role_words = content_tokens(role)
        hit = bool(role_words) and sum(w in low for w in role_words) >= max(1, len(role_words) // 2)
        add("role", "Names the role", hit, "improve", f"The title '{role}' is not clearly mentioned.")

    jd = parse_job_description(job_text) if job_text.strip() else None
    if jd is not None:
        wanted = [r.term for r in jd.requirements if r.kind == "skill" and r.importance != "preferred"]
        have = {r for r in wanted if r.lower() in low}
        need = min(2, len(wanted))
        if wanted:
            add(
                "tailored",
                "Addresses what the posting asks for",
                len(have) >= need,
                "improve",
                f"Mentions {len(have)} of the {len(wanted)} required skills ({', '.join(sorted(have)) or 'none'}). "
                "Answer at least two with a real example.",
            )
    has_number = bool(re.search(r"\d", body))
    add("evidence", "Backs a claim with a number", has_number, "improve", "Add one measurable result from your CV.")

    found = [c for c in CLICHES if c in low]
    add("cliches", "Avoids filler phrases", not found, "improve", "Found: " + ", ".join(f"'{c}'" for c in found))

    sentences = _sentences(body)
    starts = sum(bool(re.match(r"I(?:'m|'ve|'d|'ll)?\b", s)) for s in sentences)
    ratio = starts / len(sentences) if sentences else 0.0
    add(
        "variety",
        "Varies how sentences begin",
        ratio <= I_START_MAX,
        "tip",
        f"{starts} of {len(sentences)} sentences start with 'I'. Lead with the employer's need or your result.",
    )
    closing_para = letter.paragraphs[-1] if letter.paragraphs else ""
    add("cta", "Ends with a clear next step", bool(_CTA.search(closing_para)), "improve", "Invite a conversation.")
    add(
        "tone",
        "Professional tone",
        not _EMOJI.search(body) and body.count("!") <= 1 and not re.search(r"\b[A-Z]{5,}\b", body),
        "tip",
        "No emoji, at most one exclamation mark, no shouting.",
    )
    add(
        "no_placeholders",
        "No placeholders left",
        not re.search(r"\[[^\]]*\]|\{[^}]*\}|<[^>]+>|\bTODO\b|\bXXX\b", letter.text()),
        "fix",
        "Replace everything in brackets.",
    )
    return out


def summary(checks: list[LetterCheck]) -> tuple[int, int]:
    """(passed, total)"""
    return sum(c.passed for c in checks), len(checks)
