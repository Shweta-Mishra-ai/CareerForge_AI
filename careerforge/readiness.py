"""Submission-readiness gate: is this profile safe to send to an employer?

Deterministic and offline: no LLM, no network. It judges the content that would actually be exported
(`Profile.exportable()`), so unconfirmed AI suggestions can never make a CV look more ready than it is.

Severity
* blocker  - must be fixed before export (missing name/email, leftover placeholders, nothing to show)
* warning  - likely to cost interviews (no dates, first-person bullets, long gaps)
* tip      - polish (quantify results, weak verbs)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from careerforge.models import Profile
from careerforge.text import date_key, display_date

Severity = Literal["blocker", "warning", "tip"]
_ORDER = {"blocker": 0, "warning": 1, "tip": 2}

_PLACEHOLDER_NAMES = {"candidate", "professional", "name not found", "your name", "full name", "john doe"}
_FAKE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "test.com", "domain.com", "yourdomain.com"}
# [ ... ] that reads like fill-in-the-blank text blocks export; other bracketed words ([ISO 27001]) only warn.
_BRACKET = re.compile(r"\[(?=[^\]\n]{4,}\])[^\]\n]*[A-Za-z][^\]\n]*\]")
_FILL_IN_WORDS = re.compile(
    r"\b(?:your|mention|specific|insert|enter|add|describe|achievement|topic|company|name|"
    r"fill|relevant|example|here|xxx)\b",
    re.I,
)
_PLACEHOLDER_PATTERNS = (
    (re.compile(r"\{\{?[^}\n]{2,}\}\}?"), "template braces"),
    (re.compile(r"<[A-Za-z/][^>\n]{0,40}>"), "HTML-like markup"),
    (
        re.compile(
            r"\b(?:lorem ipsum|tbd|todo|xxx+|your[ _](?:name|email|company|role)|insert [a-z ]{3,30} here)\b", re.I
        ),
        "placeholder wording",
    ),
)
_FIRST_PERSON = re.compile(r"\b(?:I|[Mm]y|[Mm]e|[Mm]yself)\b")
_WEAK_START = re.compile(
    r"^(?:responsible for|worked on|helped|assisted|involved in|participated in|duties included)\b", re.I
)
_HAS_NUMBER = re.compile(r"\d")


@dataclass(frozen=True)
class Issue:
    severity: Severity
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class Readiness:
    issues: tuple[Issue, ...]

    @property
    def blockers(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == "blocker")

    @property
    def ready(self) -> bool:
        return not self.blockers

    def of(self, severity: Severity) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == severity)


class NotReady(ValueError):
    def __init__(self, readiness: Readiness):
        self.readiness = readiness
        super().__init__("; ".join(f"{i.path}: {i.message}" for i in readiness.blockers))


def require_ready(profile: Profile) -> Profile:
    """Return the exportable view, or raise NotReady. Exporters call this - never export `profile` directly."""
    result = check(profile)
    if not result.ready:
        raise NotReady(result)
    return profile.exportable()


def _strings(node: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(node, str):
        return [(path, node)]
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in _strings(v, f"{path}.{k}" if path else k)]
    if isinstance(node, list):
        return [s for i, v in enumerate(node) for s in _strings(v, f"{path}[{i}]")]
    return []


def check(profile: Profile, *, today: date | None = None) -> Readiness:
    today = today or date.today()
    now_key = today.year * 12 + today.month - 1
    out: list[Issue] = []

    def add(sev: Severity, code: str, path: str, msg: str) -> None:
        out.append(Issue(sev, code, path, msg))

    for section, idx, label in profile.pending_items():
        add(
            "warning",
            "R006",
            f"{section}[{idx}]",
            f"'{label}' is an unconfirmed AI suggestion and will be left out of the export until you confirm it",
        )

    p = profile.exportable()
    c = p.contact

    # identity & contact
    if not p.name or p.name.lower() in _PLACEHOLDER_NAMES:
        add("blocker", "R001", "name", "Add your real full name")
    if not c.email:
        add("blocker", "R002", "contact.email", "Add an email address recruiters can reply to")
    elif c.email.rpartition("@")[2] in _FAKE_EMAIL_DOMAINS:
        add("blocker", "R007", "contact.email", "This looks like a sample email address; use your real one")
    if not c.phone:
        add("warning", "R003", "contact.phone", "Add a phone number; many recruiters call first")
    if not c.location:
        add("tip", "R017", "contact.location", "Add your city/country; ATS filters often use location")

    # content
    if not (p.experience or p.projects or p.education):
        add("blocker", "R004", "profile", "Add at least one experience, project or education entry")

    for path, text in _strings(p.model_dump(mode="json")):
        if m := _BRACKET.search(text):
            if _FILL_IN_WORDS.search(m.group(0)):
                add("blocker", "R005", path, f"Contains bracketed placeholder text: '{m.group(0)}'")
                continue
            add("warning", "R005", path, f"Contains bracketed text '{m.group(0)}'; remove it if it is a leftover")
        for pattern, what in _PLACEHOLDER_PATTERNS:
            if pattern.search(text):
                add("blocker", "R005", path, f"Contains {what}: '{pattern.search(text).group(0)}'")
                break

    if not p.summary:
        add("warning", "R014", "summary", "Add a 2-3 sentence professional summary")
    elif len(p.summary) > 600:
        add("tip", "R014", "summary", "Summary is long; aim for under 600 characters")
    if not p.skills:
        add("warning", "R016", "skills", "List your key skills; ATS keyword matching relies on them")
    elif len(p.skills) > 25:
        add("tip", "R016", "skills", "Lists over 25 skills dilute the important ones; keep the most relevant")

    # experience quality
    all_bullets: list[tuple[str, str]] = []
    for i, e in enumerate(p.experience):
        base = f"experience[{i}]"
        if not e.title:
            add("warning", "R018", f"{base}.title", "Add the job title")
        if not e.company:
            add("warning", "R018", f"{base}.company", "Add the company name")
        if e.dates.is_empty():
            add("warning", "R018", f"{base}.dates", "Add dates; ATS parsers and recruiters expect them")
        elif e.dates.start and date_key(e.dates.start) > now_key + 1:
            add("warning", "R008", f"{base}.dates", "Start date is in the future")
        if not e.bullets:
            add("warning", "R009", f"{base}.bullets", "Describe what you achieved in this role")
        all_bullets += [(f"{base}.bullets[{j}]", b) for j, b in enumerate(e.bullets)]
    for i, pr in enumerate(p.projects):
        all_bullets += [(f"projects[{i}].bullets[{j}]", b) for j, b in enumerate(pr.bullets)]

    seen: set[str] = set()
    for path, b in all_bullets:
        if len(b) > 300:
            add("warning", "R010", path, "Bullet is over 300 characters; split or tighten it")
        elif len(b) < 25:
            add("tip", "R010", path, "Bullet is very short; add the action and result")
        if _FIRST_PERSON.search(b):
            add("warning", "R012", path, "Avoid first person (I/my/me) in bullets")
        if _WEAK_START.match(b):
            add("tip", "R019", path, "Start with a strong action verb instead of a passive phrase")
        if b.lower() in seen:
            add("warning", "R013", path, "Duplicate bullet")
        seen.add(b.lower())
    if _FIRST_PERSON.search(p.summary):
        add("warning", "R012", "summary", "Avoid first person (I/my/me) in the summary")
    if len(all_bullets) >= 3 and sum(bool(_HAS_NUMBER.search(b)) for _, b in all_bullets) / len(all_bullets) < 0.3:
        add("tip", "R011", "experience", "Few bullets contain numbers; quantify results (%, users, time saved)")

    # gaps between consecutive roles
    dated = sorted((e for e in p.experience if e.dates.start), key=lambda e: date_key(e.dates.start))
    for prev, nxt in zip(dated, dated[1:], strict=False):
        if prev.dates.current or not prev.dates.end:
            continue
        gap = date_key(nxt.dates.start) - date_key(prev.dates.end, end=True)
        if gap > 12:
            add(
                "warning",
                "R015",
                "experience",
                f"{gap // 12}+ year gap between {display_date(prev.dates.end)} and {display_date(nxt.dates.start)}"
                " - consider a one-line explanation",
            )

    out.sort(key=lambda i: (_ORDER[i.severity], i.code, i.path))
    return Readiness(tuple(out))
