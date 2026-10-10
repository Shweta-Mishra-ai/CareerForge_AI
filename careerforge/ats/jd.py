"""Job description -> structured requirements (deterministic; no LLM).

Recognises sections ("Requirements", "Nice to have", "Responsibilities", "About us"...), inline cues ("is a plus",
"Nice to have: ..."), tech skills via the taxonomy, years of experience, degree level, and - for non-technical
postings - a few recurring domain terms. Each requirement carries an importance that drives its weight.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from careerforge import skills as taxonomy
from careerforge.nlp import STOP, content_tokens, normalize, stem
from careerforge.text import clean_text

Importance = Literal["required", "preferred", "unspecified"]
_BASE_WEIGHT = {"required": 1.0, "unspecified": 0.8, "preferred": 0.5}
_RANK = {"required": 2, "unspecified": 1, "preferred": 0}

_SECTION = {
    "required": r"requirements?|qualifications?|must[- ]haves?|what you(?:'|’)?ll need|what we(?:'|’)?re looking for"
    r"|you have|required(?: skills| qualifications)?|minimum qualifications|skills required|who you are|about you"
    r"|key skills|skills(?: and experience)?",
    "preferred": r"nice[- ]to[- ]haves?|preferred(?: qualifications| skills)?|bonus(?: points)?|good to have|desirable"
    r"|pluses|extra credit",
    "duties": r"responsibilities|what you(?:'|’)?ll do|the role|your role|key responsibilities|duties|day[- ]to[- ]day",
    "ignore": r"about (?:us|the company|the team|[a-z]+)|benefits|perks|what we offer|compensation|salary"
    r"|equal opportunity|how to apply|our (?:culture|values|mission)|why join.*|company overview",
}
_HEADER = re.compile(
    r"^\W*(?P<name>" + "|".join(f"(?P<{k}>{v})" for k, v in _SECTION.items()) + r")\s*(?:[:\-–—]\s*(?P<rest>.*))?$",
    re.I,
)
_PREFERRED_CUE = re.compile(
    r"(nice[- ]to[- ]have|preferred|bonus|good to have|desirable|ideally|an? (?:plus|advantage)|is a plus|are a plus)",
    re.I,
)
_REQUIRED_CUE = re.compile(r"\b(required|must|essential|mandatory|minimum)\b", re.I)
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b", re.I)
_COMPANY_AGE = re.compile(r"\b(we|our|company|founded|since|established|history)\b", re.I)
_DEGREE = (
    ("phd", r"ph\.?d|doctorate"),
    ("master", r"master(?:'|’)?s|m\.?tech|m\.?sc|m\.?e\b|mba|m\.?s\b"),
    ("bachelor", r"bachelor(?:'|’)?s|b\.?tech|b\.?sc|b\.?e\b|b\.?s\b|undergraduate|degree"),
)
_BOILER = frozenset(
    """team work working experience years ability strong skills knowledge role company looking join build building
    develop development support ensure required preferred responsible responsibilities candidate opportunity position
    including related excellent great good plus must nice have hiring hire engineer engineering senior junior lead
    able willing proven demonstrated understanding environment solutions solution business high quality new
    like such well other etc across closely passion passionate fast paced collaborate collaboration communicate
    communication""".split()
)  # note: generic filler; domain words (dashboards, stakeholder...) are what we want to keep


@dataclass(frozen=True)
class Requirement:
    term: str
    kind: Literal["skill", "term"]
    importance: Importance

    @property
    def weight(self) -> float:
        return _BASE_WEIGHT[self.importance] * (1.0 if self.kind == "skill" else 0.5)


@dataclass(frozen=True)
class JobDescription:
    title: str
    requirements: tuple[Requirement, ...]
    min_years: int | None
    degree: str | None
    text: str
    has_sections: bool

    @property
    def skills(self) -> tuple[Requirement, ...]:
        return tuple(r for r in self.requirements if r.kind == "skill")


def _split_clauses(line: str) -> list[tuple[str, bool]]:
    """Sentences of a line as (text, is_preferred).

    A cue is a PREFIX when text follows it ("Nice to have: Terraform, gRPC" -> the text after is preferred) and a
    SUFFIX when nothing follows or it is a phrase like "is a plus" ("statistics preferred" -> the text before is).
    """
    out: list[tuple[str, bool]] = []
    for sentence in re.split(r"(?<=[.!?;])\s+", line):
        parts = _PREFERRED_CUE.split(sentence)
        if len(parts) == 1:
            out.append((sentence, False))
            continue
        before, cue, *tail = parts
        after = " ".join(tail).strip(" :,-–.")
        suffix_phrase = re.fullmatch(
            r"(?i)(is a plus|are a plus|a plus|an? advantage|preferred|desirable|ideally)", cue.strip()
        )
        if not after or (suffix_phrase and cue.strip().lower() not in ("preferred", "desirable", "ideally")):
            out.append((before, True))
            if after:
                out.append((after, False))
        elif (
            cue.strip().lower() in ("preferred", "desirable")
            and re.search(r"\w", before)
            and not re.match(r"^\s*:", tail[0] if tail else "")
        ):
            out.append((before, True))  # "Kubernetes experience preferred, Docker is required": cue after its subject
            out.append((after, False))
        else:
            out.append((before, False))
            out.append((after, True))
    return [(t, p) for t, p in out if t.strip()]


def _title(lines: list[str]) -> str:
    for ln in lines[:6]:
        m = re.match(r"(?i)^(?:job\s*title|position|role)\s*:\s*(.+)$", ln)
        if m:
            return clean_text(m[1])[:100]
    for ln in lines[:3]:
        if len(ln) <= 90 and not ln.endswith(".") and not _HEADER.match(ln):
            return clean_text(ln)
    return ""


# "no degree required", "without a degree", "degree is not required"
_NO_DEGREE = re.compile(
    r"(?i)\b(?:no|without)\b[^.\n]{0,20}\bdegree|\bdegree\b[^.\n]{0,20}\b(?:not|isn't)\s+(?:required|necessary|needed)"
)


def _degree(text: str) -> str | None:
    """Lowest degree level the posting accepts ('Bachelor's or Master's' -> bachelor); None if none or 'no degree'."""
    if _NO_DEGREE.search(text):
        return None
    levels = [level for level, pattern in _DEGREE if re.search(rf"(?i)\b(?:{pattern})", text)]
    order = ("bachelor", "master", "phd")
    return min(levels, key=order.index) if levels else None


def _min_years(sentences: list[str]) -> int | None:
    for s in sentences:
        if _COMPANY_AGE.search(s):
            continue
        if m := _YEARS.search(s):
            n = int(m[1])
            if 0 < n <= 30:
                return n
    return None


def parse_job_description(text: str) -> JobDescription:
    body = clean_text(text, multiline=True)
    lines = [ln.strip(" \t•·▪*-–#>") for ln in body.split("\n")]
    lines = [ln for ln in lines if ln]
    title = _title(lines)
    section = "unspecified"
    has_sections = False
    best: dict[str, Importance] = {}
    kept_sentences: list[str] = []

    def note(term: str, importance: Importance) -> None:
        if term not in best or _RANK[importance] > _RANK[best[term]]:
            best[term] = importance

    for raw in lines:
        m = _HEADER.match(raw)
        content = raw
        if m and len(m["name"]) <= 60:  # only the header NAME is bounded; the text after "Requirements:" may be long
            name = next(k for k in _SECTION if m.group(k))
            has_sections = True
            section = {"required": "required", "preferred": "preferred", "duties": "duties", "ignore": "ignore"}[name]
            content = m["rest"] or ""
            if not content:
                continue
        if section == "ignore":
            continue
        for clause, preferred_cue in _split_clauses(content):
            kept_sentences.append(clause)
            if preferred_cue or section == "preferred":
                importance: Importance = "preferred"
            elif section == "required" or _REQUIRED_CUE.search(clause):
                importance = "required"
            else:
                importance = "unspecified"
            for skill in taxonomy.find_skills(clause):
                note(skill, importance)

    skills = [Requirement(t, "skill", i) for t, i in best.items()]
    skills.sort(key=lambda r: (-_RANK[r.importance], r.term))

    # recurring domain words for non-technical postings (dashboards, stakeholder, campaigns...)
    covered = {tok for r in skills for tok in normalize(r.term).split()}
    title_tokens = set(content_tokens(title))
    counts: Counter[tuple[str, ...]] = Counter()
    surface: dict[tuple[str, ...], str] = {}
    for sentence in kept_sentences:
        toks = [t for t in content_tokens(sentence, min_len=4) if t not in _BOILER and t not in STOP]
        toks = [t for t in toks if t not in covered and t not in title_tokens]
        keys = {(stem(t),): t for t in toks} | {
            (stem(a), stem(b)): f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False)
        }
        for key, word in keys.items():
            counts[key] += 1
            surface.setdefault(key, word)
    terms = [surface[k] for k, c in counts.most_common(40) if c >= 2][:10]
    requirements = tuple(skills) + tuple(Requirement(t, "term", "unspecified") for t in terms)
    return JobDescription(
        title, requirements, _min_years(kept_sentences), _degree("\n".join(kept_sentences)), body, has_sections
    )
