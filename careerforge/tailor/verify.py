"""Deterministic rules deciding whether an AI rewrite of a bullet/summary is safe. No LLM involved.

Outcomes:  unchanged | ok (safe to apply) | needs_review (introduces a posting term the original lacked, so only the
user can confirm it is true) | rejected (adds facts or drifts in meaning).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from careerforge import skills as taxonomy
from careerforge.ai.grounding import Source
from careerforge.ats.match import FIRST_PERSON
from careerforge.nlp import normalize, stem
from careerforge.text import clean_text

Status = Literal["unchanged", "ok", "needs_review", "rejected"]
MAX_BULLET_CHARS = 260
MIN_COVERAGE = 0.55  # share of the new text's content words that the original already contained (and vice versa)
JD_COPY_RUN = 8  # a run of this many consecutive words copied from the posting looks like keyword stuffing
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CAPITALISED = re.compile(r"\b[A-Z][A-Za-z0-9&+#.\-]{2,}\b")
_PLACEHOLDER = re.compile(r"\[[^\]]{2,}\]|\{[^}]*\}|<[^>]+>|lorem ipsum|\bTODO\b", re.I)


@dataclass(frozen=True)
class Verdict:
    status: Status
    reasons: tuple[str, ...] = ()
    new_terms: tuple[str, ...] = ()


def _numbers(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUMBER.findall(text)}


def _words(text: str) -> list[str]:
    return normalize(text).split()


def _longest_shared_run(a: list[str], b: list[str], at_least: int) -> int:
    grams = {tuple(b[i : i + at_least]) for i in range(len(b) - at_least + 1)}
    return at_least if any(tuple(a[i : i + at_least]) in grams for i in range(len(a) - at_least + 1)) else 0


def _starts_sentence(text: str, pos: int) -> bool:
    """True if the word at `pos` opens the text, a sentence, a line or a bullet (capitalised for grammar only)."""
    return not text[:pos].strip() or bool(re.search(r"(?:[.!?:;•\-–—]|\n)\s*$", text[:pos]))


def _new_names(new: str, known_text: str) -> list[str]:
    """Capitalised words (not the first word) that the known text never mentions: product/company names, acronyms.

    Words that are part of a recognised skill ("REST API") or merely a plural/variant of a known word ("APIs") are
    not names; skills are judged separately, with the posting as context.
    """
    known = {stem(w) for w in _words(known_text)}
    in_skills = {stem(w) for s in taxonomy.find_skills(new) for w in normalize(s).split()}
    out = []
    for m in _CAPITALISED.finditer(new):
        word = m.group(0)
        if _starts_sentence(new, m.start()):
            continue
        key = stem(normalize(word).replace(" ", ""))
        if key in known or key in in_skills or taxonomy.lookup(word):
            continue
        out.append(word)
    return out


def check_bullet(original: str, new: str, *, role_text: str, jd_text: str = "") -> Verdict:
    """Is `new` an acceptable rewording of `original`? `role_text` is everything the user wrote about that role."""
    new = clean_text(new)
    original = clean_text(original)
    if not new:
        return Verdict("rejected", ("empty rewrite",))
    if normalize(new) == normalize(original):
        return Verdict("unchanged")

    reasons: list[str] = []
    limit = min(max(len(original) * 1.5, len(original) + 60), MAX_BULLET_CHARS)
    if len(new) > limit:
        reasons.append(f"much longer than the original ({len(new)} vs {len(original)} characters)")
    if _PLACEHOLDER.search(new):
        reasons.append("contains placeholder or markup text")
    if FIRST_PERSON.search(new):
        reasons.append("uses first person")

    before, after = _numbers(original), _numbers(new)
    if after - before:
        reasons.append(f"adds number(s) not in the original: {', '.join(sorted(after - before))}")
    if before - after:
        reasons.append(f"drops number(s) from the original: {', '.join(sorted(before - after))}")

    if names := _new_names(new, f"{role_text}\n{original}"):
        reasons.append(f"introduces name(s) not in your role: {', '.join(names[:4])}")

    known = set(taxonomy.find_skills(f"{role_text}\n{original}"))
    added = [s for s in taxonomy.find_skills(new) if s not in known and not taxonomy.implied_by(s, known)]
    in_posting = set(taxonomy.find_skills(jd_text)) if jd_text else set()
    unsupported = [s for s in added if s not in in_posting]
    if unsupported:
        reasons.append(f"introduces skill(s) found neither in your role nor in the posting: {', '.join(unsupported)}")

    if Source(original).coverage(new) < MIN_COVERAGE:
        reasons.append("the meaning drifts from the original")
    elif Source(new).coverage(original) < MIN_COVERAGE:
        reasons.append("drops too much of the original")

    if jd_text and _longest_shared_run(_words(new), _words(jd_text), JD_COPY_RUN):
        if not _longest_shared_run(_words(original), _words(jd_text), JD_COPY_RUN):
            reasons.append("copies a long phrase from the posting")

    if reasons:
        return Verdict("rejected", tuple(reasons))
    if added:
        return Verdict(
            "needs_review", ("uses posting term(s) your original did not mention; confirm they are true",), tuple(added)
        )
    return Verdict("ok")


def check_summary(original: str, new: str, *, profile_text: str, years: int, jd_text: str = "") -> Verdict:
    """Summaries make bigger claims, so the rules are stricter: nothing new at all, not even posting terms."""
    new = clean_text(new, multiline=True)
    original = clean_text(original, multiline=True)
    if not new:
        return Verdict("rejected", ("empty summary",))
    if normalize(new) == normalize(original):
        return Verdict("unchanged")
    reasons: list[str] = []
    if not 60 <= len(new) <= 600:
        reasons.append("summary must be 60-600 characters")
    if _PLACEHOLDER.search(new):
        reasons.append("contains placeholder or markup text")
    if FIRST_PERSON.search(new):
        reasons.append("uses first person")
    allowed_numbers = _numbers(profile_text) | {str(y) for y in (years - 1, years, years + 1) if y > 0}
    if extra := _numbers(new) - allowed_numbers:
        reasons.append(f"claims number(s) not supported by your CV: {', '.join(sorted(extra))}")
    if names := _new_names(new, profile_text):
        reasons.append(f"introduces name(s) not in your CV: {', '.join(names[:4])}")
    have = set(taxonomy.find_skills(profile_text))
    if bad := [s for s in taxonomy.find_skills(new) if s not in have and not taxonomy.implied_by(s, have)]:
        reasons.append(f"claims skill(s) not shown in your CV: {', '.join(bad)}")
    if Source(profile_text).coverage(new) < MIN_COVERAGE:
        reasons.append("contains statements that cannot be traced to your CV")
    if jd_text and _longest_shared_run(_words(new), _words(jd_text), JD_COPY_RUN):
        reasons.append("copies a long phrase from the posting")
    if reasons:
        return Verdict("rejected", tuple(reasons))
    # a brand-new summary (none existed) is AI-authored text, so the user must approve it
    return Verdict(
        "ok" if original else "needs_review", () if original else ("new AI-written summary; read it and confirm",)
    )
