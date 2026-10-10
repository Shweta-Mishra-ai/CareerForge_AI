"""Convert the two old CV shapes into a Profile.

* CareerForge v1: experience/projects/education/certificates are HTML strings the LLM wrote
  (`<p><b>Title at Company (dates)</b></p><ul><li>..</li></ul>`), skills a comma string, contact a pipe string.
* CareerBoost v1: lists of dicts (`title/company/duration/description`, `name/description/language/stars`...).

`profile_from_legacy` never drops content silently: whatever cannot be mapped is reported in the returned
warnings so the review screen can show it. Descriptions are split on newlines/bullets only - never on hyphens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from pydantic import ValidationError

from careerforge.models import (
    Certification,
    Contact,
    DateRange,
    Education,
    Experience,
    Profile,
    Project,
)
from careerforge.text import (
    clean_text,
    normalize_email,
    normalize_phone,
    normalize_url,
    parse_date_range,
)

_PLACEHOLDER_NAMES = {"candidate", "professional", "name not found", "n/a", "unknown"}
_SKIP_CONTENT = {"script", "style", "noscript"}
_BLOCK_TAGS = {"p", "div", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "section"}


# ── HTML -> blocks ──────────────────────────────────────────────────────────


@dataclass
class Block:
    header: str = ""  # leading bold text (or the whole text when `bold` is False)
    bold: bool = False  # True when the header was explicitly bold = structured data
    rest: str = ""  # text after the bold on the same line
    lines: list[str] = field(default_factory=list)  # further lines (after <br> or plain paragraphs)
    bullets: list[str] = field(default_factory=list)  # <li> items


class _BlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._cur: Block | None = None
        self._segments: list[tuple[str, bool, bool]] = []  # (text, bold, after_br)
        self._bold = 0
        self._after_br = False
        self._li: list[str] | None = None
        self._skip = 0

    # paragraph lifecycle
    def _flush_paragraph(self) -> None:
        segs, self._segments, self._after_br = self._segments, [], False
        if not any(clean_text(t) for t, _, _ in segs):
            return
        head = [t for t, b, br in segs if b and not br]
        first_line = [(t, b) for t, b, br in segs if not br]
        later = clean_text("".join(t for t, _, br in segs if br))
        starts_bold = bool(first_line) and first_line[0][1] and clean_text(first_line[0][0])
        if starts_bold:
            block = Block(
                header=clean_text("".join(head)), bold=True, rest=clean_text("".join(t for t, b in first_line if not b))
            )
            if later:
                block.lines.append(later)
            self.blocks.append(block)
            self._cur = block
            return
        text = clean_text("".join(t for t, _, _ in segs))
        if self._cur is None:
            self._cur = Block(header=text)
            self.blocks.append(self._cur)
        else:
            self._cur.lines.append(text)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_CONTENT:
            self._skip += 1
        elif tag in ("b", "strong"):
            self._bold += 1
        elif tag == "br":
            self._after_br = True
            self._segments.append((" ", False, True))
        elif tag == "li":
            self._flush_paragraph()
            self._li = []
        elif tag in _BLOCK_TAGS:
            self._flush_paragraph()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT:
            self._skip = max(0, self._skip - 1)
        elif tag in ("b", "strong"):
            self._bold = max(0, self._bold - 1)
        elif tag == "li" and self._li is not None:
            text = clean_text("".join(self._li))
            self._li = None
            if text:
                if self._cur is None:
                    self._cur = Block()
                    self.blocks.append(self._cur)
                self._cur.bullets.append(text)
        elif tag in _BLOCK_TAGS:
            self._flush_paragraph()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._li is not None:
            self._li.append(data)
        else:
            self._segments.append((data, self._bold > 0, self._after_br))

    def close(self) -> None:
        super().close()
        self._flush_paragraph()


def html_to_blocks(html: str) -> list[Block]:
    """Parse the old HTML-string format into blocks. Plain text without tags becomes a single block."""
    if not clean_text(html):
        return []
    parser = _BlockParser()
    parser.feed(html if "<" in html else f"<p>{html}</p>")
    parser.close()
    return parser.blocks


# ── field mapping helpers ───────────────────────────────────────────────────

_TITLE_AT_COMPANY = re.compile(r"^(?P<title>.+?)\s+(?:at|@)\s+(?P<company>.+?)\s*$", re.I)
_TRAILING_PAREN = re.compile(r"^(?P<head>.*?)\s*\((?P<inner>[^()]*)\)\s*$")


def _split_header(header: str) -> tuple[str, str, str]:
    """'Title at Company (Jan 2020 - Now)' -> (title, company, dates_text). Missing parts are ''."""
    dates = ""
    if m := _TRAILING_PAREN.match(header):
        inner = m["inner"]
        try:
            parse_date_range(inner)
            header, dates = m["head"], inner
        except ValueError:
            pass
    if m := _TITLE_AT_COMPANY.match(header):
        return m["title"], m["company"], dates
    if " | " in header:
        a, _, b = header.partition(" | ")
        return a.strip(), b.strip(), dates
    return header.strip(), "", dates


def _date_range(text: str, warnings: list[str], label: str) -> DateRange:
    if not text:
        return DateRange()
    try:
        start, end, current = parse_date_range(text)
        return DateRange(start=start, end=end, current=current)
    except ValueError:
        warnings.append(f"{label}: could not read dates '{text}'; please enter them manually")
        return DateRange()


def _bullets_from_description(text: str) -> list[str]:
    """Split a free-text description on newlines / bullet glyphs only (never on hyphens)."""
    parts = re.split(r"\n+|\s+[•▪●◦]\s+|^[•▪●◦]\s*", clean_text(text, multiline=True))
    return [p.strip() for p in parts if p and p.strip()]


def _try(factory: Any, warnings: list[str], label: str, **kwargs: Any) -> Any | None:
    try:
        return factory(**kwargs)
    except (ValidationError, ValueError) as exc:
        warnings.append(f"{label}: skipped ({str(exc).splitlines()[0] if str(exc) else 'invalid'})")
        return None


def _skills(value: Any) -> list[str]:
    if isinstance(value, str):
        return [s for s in re.split(r"[,;\n|•]", value) if s.strip()]
    if isinstance(value, list):
        return [str(s) for s in value if s]
    return []


# ── contact ─────────────────────────────────────────────────────────────────


def parse_contact_string(text: str, warnings: list[str] | None = None) -> Contact:
    """Parse 'a@b.com | +91 99999 99999 | linkedin.com/in/x | Delhi, India' (also newline separated)."""
    warnings = warnings if warnings is not None else []
    fields: dict[str, str] = {}
    leftovers: list[str] = []
    raw = re.sub(r"<[^>]+>", " ", text or "")
    for token in (t.strip() for t in re.split(r"[|\n•·]", raw) if t.strip()):
        low = token.lower()
        try:
            if "@" in token:
                fields.setdefault("email", normalize_email(token))
            elif "linkedin." in low:
                fields.setdefault("linkedin", normalize_url(token, ("linkedin.com",)))
            elif "github." in low:
                fields.setdefault("github", normalize_url(token, ("github.com",)))
            elif re.fullmatch(r"\+?[\d\s().\-]{7,}", token):
                fields.setdefault("phone", normalize_phone(token))
            elif low.startswith(("http", "www.")):
                fields.setdefault("website", normalize_url(token))
            else:
                leftovers.append(token)
        except ValueError as exc:
            warnings.append(f"contact '{token}': {exc}")
    if leftovers and "location" not in fields:
        fields["location"] = ", ".join(leftovers)
    return Contact(**fields)


def _contact_from_dict(data: dict[str, Any], warnings: list[str]) -> Contact:
    contact = parse_contact_string(str(data.get("contact") or ""), warnings)
    values = contact.model_dump()
    for key, norm in (
        ("email", normalize_email),
        ("phone", normalize_phone),
        ("linkedin", lambda v: normalize_url(v, ("linkedin.com",))),
        ("github", lambda v: normalize_url(v, ("github.com",))),
        ("website", normalize_url),
    ):
        raw = data.get(key)
        if raw and not values.get(key):
            try:
                values[key] = norm(raw)
            except ValueError as exc:
                warnings.append(f"{key} '{raw}': {exc}")
    if data.get("location") and not values.get("location"):
        values["location"] = clean_text(data["location"])[:100]
    return Contact(**values)


# ── sections ────────────────────────────────────────────────────────────────


def _experience(value: Any, warnings: list[str]) -> list[Experience]:
    out: list[Experience] = []
    if isinstance(value, str):
        for i, b in enumerate(html_to_blocks(value), 1):
            if b.bold:
                title, company, dates = _split_header(b.header)
                bullets = [*b.bullets, *([b.rest] if b.rest else []), *b.lines]
            else:  # unstructured prose: never guess a title/company from it, keep the words as-is
                title = company = dates = ""
                bullets = [b.header, *b.bullets, *b.lines]
            label = f"experience #{i}"
            item = _try(
                Experience,
                warnings,
                label,
                title=title,
                company=company,
                bullets=bullets,
                dates=_date_range(dates, warnings, label),
            )
            if item is not None and (title or company or bullets):
                out.append(item)
    elif isinstance(value, list):
        for i, e in enumerate(value, 1):
            if not isinstance(e, dict):
                continue
            label = f"experience #{i}"
            item = _try(
                Experience,
                warnings,
                label,
                title=e.get("title", ""),
                company=e.get("company", ""),
                location=e.get("location", ""),
                dates=_date_range(clean_text(e.get("duration") or e.get("dates")), warnings, label),
                bullets=e.get("bullets") or _bullets_from_description(str(e.get("description") or "")),
            )
            if item is not None and (item.title or item.company):
                out.append(item)
    return out


def _education(value: Any, structured: Any, warnings: list[str]) -> list[Education]:
    out: list[Education] = []
    if isinstance(structured, list) and structured:
        value = structured
    if isinstance(value, str):
        for i, b in enumerate(html_to_blocks(value), 1):
            degree, _, institution = b.header.partition(",")
            detail_text = b.rest or (b.lines[0] if b.lines else "")
            dates, grade = DateRange(), ""
            for tok in (t.strip() for t in re.split(r"\|", detail_text) if t.strip()):
                if dates.is_empty() and re.search(r"\d{4}", tok) and not re.search(r"cgpa|gpa|%|marks", tok, re.I):
                    dates = _date_range(tok, warnings, f"education #{i}")
                else:
                    grade = f"{grade}, {tok}".strip(", ")
            item = _try(
                Education,
                warnings,
                f"education #{i}",
                degree=degree.strip() or b.header,
                institution=institution.strip(),
                dates=dates,
                grade=grade[:60],
                details=b.bullets,
            )
            if item is not None and (item.degree or item.institution):
                out.append(item)
    elif isinstance(value, list):
        for i, e in enumerate(value, 1):
            if isinstance(e, dict):
                year = clean_text(e.get("year"))
                item = _try(
                    Education,
                    warnings,
                    f"education #{i}",
                    degree=e.get("degree", ""),
                    institution=e.get("institution", ""),
                    dates=_date_range(year, warnings, f"education #{i}"),
                )
            else:  # 'B.Tech — NIT (2018)'
                text = clean_text(e)
                m = _TRAILING_PAREN.match(text)
                head, year = (m["head"], m["inner"]) if m else (text, "")
                degree, _, inst = head.partition(" — ")
                item = _try(
                    Education,
                    warnings,
                    f"education #{i}",
                    degree=degree,
                    institution=inst,
                    dates=_date_range(year, warnings, f"education #{i}"),
                )
            if item is not None and (item.degree or item.institution):
                out.append(item)
    return out


def _projects(value: Any, warnings: list[str]) -> list[Project]:
    out: list[Project] = []
    if isinstance(value, str):
        for i, b in enumerate(html_to_blocks(value), 1):
            name, _, tech = b.header.partition("|")
            item = _try(
                Project,
                warnings,
                f"project #{i}",
                name=name.strip(),
                tech=[t for t in re.split(r"[,&·/]", tech) if t.strip()],
                bullets=[*b.bullets, *([b.rest] if b.rest else []), *b.lines],
            )
            if item is not None and item.name:
                out.append(item)
    elif isinstance(value, list):
        for i, p in enumerate(value, 1):
            if not isinstance(p, dict):
                continue
            tech = [p.get("language", ""), *(p.get("topics") or []), *(p.get("tech") or [])]
            item = _try(
                Project,
                warnings,
                f"project #{i}",
                name=p.get("name", ""),
                description=str(p.get("description") or "")[:600],
                tech=[t for t in tech if t],
                url=p.get("url", ""),
                stars=int(p.get("stars") or 0),
            )
            if item is not None and item.name:
                out.append(item)
    return out


_CERT_REST = re.compile(r"^[—–-]?\s*(?P<issuer>.*?)\s*(?:\((?P<year>[^()]*)\))?\s*$")


def _certifications(value: Any, warnings: list[str]) -> list[Certification]:
    out: list[Certification] = []
    if isinstance(value, str):
        for i, b in enumerate(html_to_blocks(value), 1):
            m = _CERT_REST.match(b.rest)
            issuer, year = (m["issuer"], m["year"] or "") if m else (b.rest, "")
            date = ""
            if year:
                try:
                    date = parse_date_range(year)[0]
                except ValueError:
                    warnings.append(f"certification #{i}: could not read date '{year}'")
            item = _try(Certification, warnings, f"certification #{i}", name=b.header, issuer=issuer, date=date)
            if item is not None and item.name:
                out.append(item)
    elif isinstance(value, list):
        for i, c in enumerate(value, 1):
            data = (
                {"name": c.get("name", ""), "issuer": c.get("issuer", "")}
                if isinstance(c, dict)
                else {"name": clean_text(c)}
            )
            item = _try(Certification, warnings, f"certification #{i}", **data)
            if item is not None and item.name:
                out.append(item)
    return out


# ── entry point ─────────────────────────────────────────────────────────────


def profile_from_legacy(data: dict[str, Any]) -> tuple[Profile, list[str]]:
    """Map an old cv_data dict (either app) to (Profile, warnings)."""
    warnings: list[str] = []
    name = clean_text(data.get("name"))
    headline = clean_text(data.get("headline") or data.get("current_title"))
    if name.lower() in _PLACEHOLDER_NAMES:
        name = ""
    if headline.lower() in _PLACEHOLDER_NAMES:
        headline = ""
    profile = Profile(
        name=name[:120],
        headline=headline[:200],
        summary=clean_text(data.get("summary"), multiline=True)[:1500],
        contact=_contact_from_dict(data, warnings),
        skills=_skills(data.get("skills"))[:80],
        experience=_experience(data.get("experience"), warnings),
        education=_education(data.get("education"), data.get("education_structured"), warnings),
        projects=_projects(data.get("projects"), warnings),
        certifications=_certifications(data.get("certifications") or data.get("certificates"), warnings),
    )
    return profile, warnings
