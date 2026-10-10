"""Grounding: is every claim in a Profile traceable to the source document?

This is a deterministic, offline check - the replacement for the old LLM "hallucination_check" that merely asked
the model to grade itself. Policy for EXTRACTION (profile built from a document):

  contact / name / headline / summary / dates / grade / skills / bullets that are not in the source -> removed
  an employer, school, project or certification name not in the source -> item kept but marked "suggested"
      (unconfirmed), so Profile.exportable() leaves it out until the user confirms it

Everything removed or demoted is listed in the report, so nothing disappears silently. The check is
conservative about recall: a faithful paraphrase may be flagged (the user can restore it), but an invented
employer, number, date or skill will not pass.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from careerforge import skills as taxonomy
from careerforge.models import Profile
from careerforge.text import clean_text

_LEGAL = frozenset(
    {"pvt", "ltd", "limited", "inc", "llc", "llp", "corp", "corporation", "co", "plc", "gmbh", "private"}
)
_STOP = frozenset(
    """a an and are as at be been by for from has have in into is it its of on or that the their this to was were
    with using used use via per over under across within while about also more most than then which who whom will
    our your you they them his her him she he we i my me""".split()
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # re-join words hyphenated across PDF line breaks
    return re.sub(r"[^0-9a-z]+", " ", text).strip()


def _stem(tok: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(tok) > 4 and tok.endswith(suffix):
            return tok[: -len(suffix)]
    return tok


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", _norm(text))


def _numbers(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUMBER.findall(text or "")}


class Source:
    """Pre-computed lookups over the source text."""

    def __init__(self, text: str):
        self.raw = text or ""
        self.norm = _norm(self.raw)
        self.words = set(self.norm.split())
        self.stems = {_stem(w) for w in self.words}
        self.squashed = re.sub(r"[^0-9a-z]", "", self.norm)
        self.digits = _digits(self.raw)
        self.numbers = _numbers(self.raw)
        self.lower = self.raw.casefold()
        self.known_skills = set(taxonomy.find_skills(self.raw))

    def phrase(self, phrase: str, min_ratio: float = 1.0) -> bool:
        """Fraction of the phrase's significant words that occur in the source (order-insensitive)."""
        toks = [t for t in _norm(phrase).split() if t not in _LEGAL]
        if not toks:
            return True
        if " ".join(toks) in self.norm:
            return True
        return sum(t in self.words for t in toks) / len(toks) >= min_ratio

    def coverage(self, text: str) -> float:
        """Share of a sentence's content words (light-stemmed) found in the source."""
        toks = [t for t in _norm(text).split() if len(t) >= 3 and t not in _STOP and not t.isdigit()]
        if not toks:
            return 1.0
        return sum(_stem(t) in self.stems or t in self.words for t in toks) / len(toks)

    def numbers_ok(self, text: str) -> bool:
        return _numbers(text) <= self.numbers

    def skill(self, name: str) -> bool:
        if name in self.known_skills:
            return True
        pattern = rf"(?<![\w+#.]){re.escape(name.casefold())}(?![\w+#]|\.\w)"
        return bool(re.search(pattern, self.lower))

    def year(self, iso_date: str) -> bool:
        return not iso_date or iso_date[:4] in self.numbers

    def link(self, url: str) -> bool:
        bare = re.sub(r"^https?://(www\.)?", "", url, flags=re.I).rstrip("/")
        return _squash(bare) in self.squashed

    def email(self, value: str) -> bool:
        return value.casefold() in self.lower

    def phone(self, value: str) -> bool:
        d = _digits(value)
        return bool(d) and d[-10:] in self.digits


@dataclass(frozen=True)
class Finding:
    kind: str  # contact | name | headline | summary | skill | date | grade | entity | bullet | description | link
    path: str
    text: str
    reason: str
    action: str  # "removed" | "unconfirmed"


@dataclass(frozen=True)
class GroundingReport:
    findings: tuple[Finding, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.findings

    def of(self, kind: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.kind == kind)


def ground_profile(profile: Profile, source_text: str) -> tuple[Profile, GroundingReport]:
    """Apply the extraction policy. Returns a NEW profile (the input is untouched) and a report."""
    src = Source(source_text)
    data: dict[str, Any] = profile.model_dump()
    findings: list[Finding] = []

    def flag(kind: str, path: str, text: str, reason: str, action: str = "removed") -> None:
        findings.append(Finding(kind, path, text, reason, action))

    def demote(item: dict[str, Any]) -> None:
        item["origin"], item["confirmed"] = "suggested", False

    def keep_skills(path: str, names: list[str]) -> list[str]:
        kept = []
        for n in names:
            if src.skill(n):
                kept.append(n)
            else:
                flag("skill", path, n, "not mentioned in the document")
        return kept

    def keep_bullets(path: str, bullets: list[str]) -> list[str]:
        kept = []
        for i, b in enumerate(bullets):
            if not src.numbers_ok(b):
                flag("bullet", f"{path}[{i}]", b, "contains a number that is not in the document")
            elif src.coverage(b) < 0.6:
                flag("bullet", f"{path}[{i}]", b, "wording cannot be traced to the document")
            else:
                kept.append(b)
        return kept

    def check_dates(path: str, dates: dict[str, Any]) -> None:
        for edge in ("start", "end"):
            if dates[edge] and not src.year(dates[edge]):
                flag("date", f"{path}.{edge}", dates[edge], "year not found in the document")
                dates["start"] = dates["end"] = ""
                dates["current"] = False
                return

    # identity & contact -----------------------------------------------------------------------------------
    if data["name"] and not src.phrase(data["name"]):
        flag("name", "name", data["name"], "name not found in the document")
        data["name"] = ""
    if data["headline"] and not src.phrase(data["headline"], 0.5):
        flag("headline", "headline", data["headline"], "headline not found in the document")
        data["headline"] = ""
    if data["summary"] and src.coverage(data["summary"]) < 0.6:
        flag("summary", "summary", data["summary"], "summary was written by the AI, not found in the document")
        data["summary"] = ""
    c = data["contact"]
    checks = {"email": src.email, "phone": src.phone, "linkedin": src.link, "github": src.link, "website": src.link}
    for key, check in checks.items():
        if c[key] and not check(c[key]):
            flag("contact", f"contact.{key}", c[key], "not found in the document")
            c[key] = ""
    if c["location"] and not src.phrase(c["location"]):
        flag("contact", "contact.location", c["location"], "not found in the document")
        c["location"] = ""

    data["skills"] = keep_skills("skills", data["skills"])
    data["languages"] = [x for x in data["languages"] if src.phrase(x)]

    # experience ---------------------------------------------------------------------------------------------
    for i, e in enumerate(data["experience"]):
        p = f"experience[{i}]"
        if e["company"] and not src.phrase(e["company"]):
            flag("entity", f"{p}.company", e["company"], "employer not found in the document", "unconfirmed")
            demote(e)
        if e["title"] and not src.phrase(e["title"], 0.7):
            flag("entity", f"{p}.title", e["title"], "job title not found in the document", "unconfirmed")
            demote(e)
        check_dates(f"{p}.dates", e["dates"])
        e["bullets"] = keep_bullets(f"{p}.bullets", e["bullets"])

    # education ---------------------------------------------------------------------------------------------
    for i, e in enumerate(data["education"]):
        p = f"education[{i}]"
        if e["institution"] and not src.phrase(e["institution"]):
            flag("entity", f"{p}.institution", e["institution"], "institution not found in the document", "unconfirmed")
            demote(e)
        if e["degree"] and not src.phrase(e["degree"], 0.7):
            flag("entity", f"{p}.degree", e["degree"], "degree not found in the document", "unconfirmed")
            demote(e)
        check_dates(f"{p}.dates", e["dates"])
        if e["grade"] and not src.numbers_ok(e["grade"]):
            flag("grade", f"{p}.grade", e["grade"], "grade value not in the document")
            e["grade"] = ""
        e["details"] = keep_bullets(f"{p}.details", e["details"])

    # projects ------------------------------------------------------------------------------------------------
    for i, pr in enumerate(data["projects"]):
        p = f"projects[{i}]"
        if pr["name"] and not src.phrase(pr["name"]):
            flag("entity", f"{p}.name", pr["name"], "project not found in the document", "unconfirmed")
            demote(pr)
        if pr["description"] and (src.coverage(pr["description"]) < 0.6 or not src.numbers_ok(pr["description"])):
            flag("description", f"{p}.description", pr["description"], "description cannot be traced to the document")
            pr["description"] = ""
        if pr["url"] and not src.link(pr["url"]):
            flag("link", f"{p}.url", pr["url"], "link not found in the document")
            pr["url"] = ""
        pr["tech"] = keep_skills(f"{p}.tech", pr["tech"])
        pr["bullets"] = keep_bullets(f"{p}.bullets", pr["bullets"])

    # certifications -----------------------------------------------------------------------------------------
    for i, ce in enumerate(data["certifications"]):
        p = f"certifications[{i}]"
        if ce["name"] and not src.phrase(ce["name"], 0.8):
            flag("entity", f"{p}.name", ce["name"], "certification not found in the document", "unconfirmed")
            demote(ce)
        if ce["issuer"] and not src.phrase(ce["issuer"]):
            flag("entity", f"{p}.issuer", ce["issuer"], "issuer not found in the document")
            ce["issuer"] = ""
        if ce["date"] and not src.year(ce["date"]):
            flag("date", f"{p}.date", ce["date"], "year not found in the document")
            ce["date"] = ""
        if ce["url"] and not src.link(ce["url"]):
            flag("link", f"{p}.url", ce["url"], "link not found in the document")
            ce["url"] = ""

    return Profile.model_validate(data), GroundingReport(tuple(findings))


def profile_text(profile: Profile) -> str:
    """Flatten a profile to plain text, to use as the 'source' when grounding AI *rewrites* of it (Phase 4)."""
    d = profile.model_dump()
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            for k, v in node.items():
                if k not in ("origin", "confirmed", "current"):
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(d)
    return clean_text("\n".join(p for p in parts if p), multiline=True)
