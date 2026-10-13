"""Rule-based CV reader: the "basic" path when no AI is set up (or when the AI is down).

Principles
* It only copies text that exists in the document, from recognised section headings. It never infers a job, a
  degree, a date or a skill that is not written there.
* Where a split is a judgement call (is "Acme - Engineer" title-company or company-title?) it picks the most common
  layout and says so in the notes, so the review step can point the user at it.
* Whatever it produces is passed through the same grounding check as AI output by the caller.

It understands the usual layouts: a header (name, headline, contact), then headed sections with entries such as
"Title - Company (Mar 2021 - Present)" followed by bullets. It does NOT try to understand free-form paragraphs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from careerforge import skills as taxonomy
from careerforge.models import Certification, Contact, DateRange, Education, Experience, Profile, Project
from careerforge.text import normalize_email, normalize_phone, normalize_url, parse_date_range

HEADINGS: dict[str, tuple[str, ...]] = {
    "summary": (
        "summary", "professional summary", "profile", "professional profile", "about", "about me", "objective",
        "career objective", "personal statement", "executive summary",
    ),
    "experience": (
        "experience", "work experience", "professional experience", "employment", "employment history",
        "work history", "career history", "internships", "internship experience", "relevant experience",
    ),
    "education": (
        "education", "academic background", "academics", "qualifications", "academic qualifications",
        "education and training", "education & training",
    ),
    "skills": (
        "skills", "technical skills", "core competencies", "key skills", "skills and tools", "skills & tools",
        "technologies", "tools", "expertise", "areas of expertise", "technical expertise", "core skills",
        "top skills",
    ),
    "projects": ("projects", "personal projects", "academic projects", "selected projects", "key projects"),
    "certifications": (
        "certifications", "certificates", "licenses", "licenses & certifications", "licenses and certifications",
        "courses", "training", "certifications & courses", "certifications and courses",
    ),
    "languages": ("languages", "spoken languages", "language skills"),
    "contact": ("contact", "contact details", "contact information", "contact me", "get in touch"),
    "ignore": (
        "references", "hobbies", "interests", "declaration", "achievements", "awards", "publications",
        "volunteering", "extracurricular", "extracurricular activities", "personal details", "personal information",
        "awards and achievements", "honors", "honours", "links found in the document", "honors awards",
        "organizations", "volunteer experience", "recommendations", "patents", "test scores", "causes",
    ),
}  # fmt: skip
_HEADING_LOOKUP = {alias: section for section, aliases in HEADINGS.items() for alias in aliases}

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE = rf"(?:{_MONTH}\.?,?\s+(?:19|20)\d{{2}}|\d{{1,2}}/(?:19|20)\d{{2}}|(?:19|20)\d{{2}}-\d{{2}}|(?:19|20)\d{{2}})"
_NOW = r"(?:Present|Current|Now|Ongoing|Till\s+date|To\s+date|Today)"
_RANGE = re.compile(rf"{_DATE}\s*(?:-|–|—|to|until)\s*(?:{_DATE}|{_NOW})(?![\w])", re.I)
_DURATION = re.compile(r"\(\s*\d+\s*(?:years?|yrs?|months?|mos?)(?:\s+\d+\s*(?:months?|mos?))?\s*\)", re.I)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_BULLET = re.compile(r"^\s*(?:[-•*▪‣◦●·–—➢►]|•)\s+(.*\S)\s*$")
_URL = re.compile(r"(?:https?://|www\.)[^\s,;)]+|\b(?:github|gitlab)\.com/[^\s,;)]+", re.I)
_GRADE = re.compile(
    r"(?:\b(?:CGPA|GPA|CPI|Grade|Percentage|Marks)\b\s*[:\-]?\s*[\d.]+(?:\s*/\s*\d+(?:\.\d+)?)?|"
    r"[\d.]+\s*(?:CGPA|GPA|CPI)\b|\b\d{2}(?:\.\d+)?\s*%)",
    re.I,
)
_DEGREE = re.compile(
    r"\b(?:b\.?\s?des|m\.?\s?des|bfa|mfa|b\.?\s?pharm|m\.?\s?pharm|b\.?\s?ed|m\.?\s?ed|pgdm|pg diploma|post ?graduate|"
    r"b\.?\s?tech|m\.?\s?tech|b\.?\s?e\.?|m\.?\s?e\.?|b\.?\s?sc|m\.?\s?sc|b\.?\s?a\.?|m\.?\s?a\.?|b\.?\s?com|"
    r"m\.?\s?com|bca|mca|bba|mba|llb|llm|mbbs|b\.?\s?arch|bachelor|master|ph\.?\s?d|doctorate|diploma|associate "
    r"degree|high school|secondary school|senior secondary|hsc|ssc|class (?:x|xii|10|12)|10th|12th|intermediate)\b",
    re.I,
)
_INSTITUTION = re.compile(
    r"\b(?:university|institute|college|school|academy|polytechnic|iit|nit|iiit|bits|faculty|universit[àäé])\b", re.I
)
_TITLE = re.compile(
    r"\b(?:engineer|developer|manager|intern|analyst|lead|consultant|designer|director|associate|specialist|"
    r"architect|officer|executive|administrator|scientist|researcher|assistant|coordinator|head|vp|president|founder|"
    r"programmer|technician|trainee|apprentice|teacher|lecturer|professor|accountant|marketer|strategist|"
    r"representative|supervisor|recruiter|writer|editor|nurse|clerk)\b",
    re.I,
)
_TECH_LABEL = re.compile(
    r"^\s*(?:tech(?:nologies)?|tech stack|stack|tools|built with|skills used)\s*[:\-]\s*(.*\S)", re.I
)
_NOT_NAMES = {"curriculum vitae", "resume", "résumé", "cv", "profile", "contact", "summary", "page"}
_SPACED = re.compile(r"^(?:\S\s){2,}\S$")
_CONTACT_SPLIT = re.compile(r"[|•·▪]")  # (no \s* around it: that is quadratic on long whitespace runs)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w/])\+?\d[\d\s().-]{8,}\d(?![\w/])")
_LINKEDIN = re.compile(r"(?:https?://)?(?:[\w]+\.)?linkedin\.com/in/[\w\-%]+/?", re.I)
_GITHUB = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[\w\-]+(?![\w\-])", re.I
)  # the whole username, never a prefix
MAX_SUMMARY = 1500


@dataclass
class _Notes:
    items: list[str] = field(default_factory=list)
    ambiguous: int = 0

    def add(self, text: str) -> None:
        if text not in self.items:
            self.items.append(text)


# ── lines and headings ──────────────────────────────────────────────────────


def collapse_spaced(line: str) -> str:
    """'S K I L L S' -> 'SKILLS', 'W O R K  E X P E R I E N C E' -> 'WORK EXPERIENCE' (letter-spaced headings)."""
    stripped = line.strip()
    words = re.split(r"\s{2,}", stripped)
    if all(_SPACED.fullmatch(w) or len(w) <= 1 for w in words) and sum(len(w) for w in words) >= 4:
        return " ".join(w.replace(" ", "") for w in words)
    return stripped


def heading_of(line: str) -> str | None:
    """The section a line is a heading for, or None. Headings stand alone on a short line."""
    text = collapse_spaced(line)
    if not text or len(text) > 45 or _BULLET.match(line):
        return None
    key = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z&\s]", " ", text)).strip().lower()
    return _HEADING_LOOKUP.get(key)


def _merge_wrapped_dates(lines: list[str]) -> list[str]:
    """'... 2014 –' followed by '2018' on the next line is one date range that the PDF happened to wrap."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if re.search(r"[–—-]\s*$", line) and re.match(rf"(?:{_DATE}|{_NOW})\b", nxt, re.I) and _has_year(line):
            out.append(f"{line.rstrip()} {nxt}")
            i += 2
        else:
            out.append(line)
            i += 1
    return out


def _has_year(text: str) -> bool:
    return bool(_YEAR.search(text))


def _split_sections(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    head: list[str] = []
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        section = heading_of(line)
        if section:
            current = sections.setdefault(section, [])
        elif current is None:
            head.append(line)
        else:
            current.append(line)
    return head, sections


def _bullet_text(line: str) -> str | None:
    m = _BULLET.match(line)
    return m.group(1).strip() if m else None


def _has_range(line: str) -> bool:
    return bool(_RANGE.search(line))


def _join_wrapped(parts: list[str]) -> list[str]:
    """Bullets wrapped over several lines become one bullet each (a line continues the previous one when the
    previous one did not end a sentence, or the new one starts lower case)."""
    out: list[str] = []
    for text, is_new in _marked(parts):
        if is_new or not out:
            out.append(text)
        else:
            out[-1] = f"{out[-1]} {text}"
    return out


def _marked(parts: list[str]) -> list[tuple[str, bool]]:
    result: list[tuple[str, bool]] = []
    prev = ""
    for raw in parts:
        text = raw.strip()
        if not text:
            prev = ""
            continue
        bullet = _bullet_text(raw)
        if bullet is not None:
            result.append((bullet, True))
            prev = bullet
        else:
            continues = bool(prev) and (not re.search(r"[.!?:]$", prev) or text[0].islower())
            result.append((text, not continues))
            prev = text
    return result


# ── header: name, headline, contact ─────────────────────────────────────────


def _looks_like_name(line: str) -> bool:
    text = line.strip()
    if not text or text.lower() in _NOT_NAMES or any(ch.isdigit() or ch in "@:/|" for ch in text):
        return False
    words = text.split()
    return 2 <= len(words) <= 4 and all(re.fullmatch(r"[^\W\d_](?:[^\W\d_]|['.\-])*", w) for w in words)


def _tidy_name(name: str, notes: _Notes) -> str:
    if name.isupper() and len(name) > 3:
        notes.add("The name was written in capitals and was converted to normal capitalisation. Check the spelling.")
        return name.title()
    return name


def _contact_parts(line: str) -> list[str]:
    return [p.strip() for p in _CONTACT_SPLIT.split(line) if p.strip()]


def _is_contact_text(part: str) -> bool:
    return bool(
        _EMAIL.search(part)
        or _LINKEDIN.search(part)
        or _GITHUB.search(part)
        or _URL.search(part)
        or re.search(r"\d{4,}", part)
        or re.match(
            r"^(?:email|e-mail|phone|mobile|tel|linkedin|github|website|portfolio|address)\b", part.strip(), re.I
        )
    )


def _rescue_name(sections: dict[str, list[str]], notes: _Notes, headline: str) -> tuple[str, str, str]:
    """Two-column CVs (and LinkedIn PDFs) are read sidebar first, so the name ends up at the end of the last sidebar
    section, followed by the headline and often a place. Take a name-like line plus one headline-like line (plus an
    optional place) that close a section, and remove them from it. Returns (name, headline, location)."""
    for key, body in sections.items():
        if key in ("experience", "projects", "education", "summary"):
            continue  # long-form sections never hold a stray name
        entries = [(i, ln.strip()) for i, ln in enumerate(body) if ln.strip()]
        for pos in range(len(entries) - 1):
            i, text = entries[pos]
            tail = [t for _, t in entries[pos + 1 :]]
            if len(tail) > 2 or not _name_candidate(text):
                continue
            nxt = tail[0]
            place = tail[1] if len(tail) == 2 else ""
            if not (_TITLE.search(nxt) or len(nxt.split()) >= 2) or len(nxt) > 80 or not _plausible_headline(nxt):
                continue
            if place and not (_looks_like_place(place) or _looks_like_city(place)):
                continue
            last = entries[pos + len(tail)][0]
            del body[i : last + 1]
            notes.add("The name was found after the sidebar (two-column layout). Check the order of your details.")
            return _tidy_name(text, notes), headline or nxt, place
    return "", headline, ""


def _name_candidate(text: str) -> bool:
    return (
        _looks_like_name(text) and not _TITLE.search(text) and not taxonomy.lookup(text)
    )  # "Spanish Teacher" is a job


def _parse_header(head: list[str], notes: _Notes) -> tuple[str, str, str]:
    """(name, headline, location) from the lines above the first section heading."""
    lines = [re.split(r"\s{3,}", ln.strip())[0] for ln in head if ln.strip()]  # a 2-column page: first column only
    name = headline = location = ""
    rest = lines
    if lines and _looks_like_name(lines[0]):
        name, rest = _tidy_name(lines[0], notes), lines[1:]
    for line in rest:
        parts = _contact_parts(line)
        if any(_is_contact_text(p) for p in parts) and len(parts) > 1:
            for part in parts:
                if _is_contact_text(part):
                    continue
                if not location and (_looks_like_place(part) or _looks_like_city(part)):
                    location = part.strip()
                elif not headline and _plausible_headline(part):
                    headline = part.strip()  # "Data Analyst | me@mail.com | Pune": the first cell is the headline
            continue
        if _is_contact_text(line):
            continue
        if _looks_like_place(line) and not _TITLE.search(line):
            location = location or line.strip()
        elif not headline and _plausible_headline(line):
            headline = line
    return name, headline, location


def _plausible_headline(text: str) -> bool:
    t = text.strip()
    return (
        0 < len(t) <= 80
        and not re.search(r"[.!?:]$", t)
        and not re.search(r"[<>{}\[\]]", t)  # markup or template syntax is not a headline
        and not _looks_like_name_only_place(t)
    )


def _looks_like_name_only_place(text: str) -> bool:
    return _looks_like_place(text) or (_looks_like_city(text) and not _TITLE.search(text))


def _looks_like_city(text: str) -> bool:
    """One capitalised word (Pune, Delhi) or two (New York) in a contact line is a city."""
    t = text.strip()
    return bool(re.fullmatch(r"[A-Z][a-z]{2,20}(?: [A-Z][a-z]{2,20})?", t)) and not _TITLE.search(t)


def _looks_like_place(text: str) -> bool:
    t = text.strip()
    return bool(re.fullmatch(r"[^\W\d_][^\d@:/|]{1,60}", t)) and "," in t and not _TITLE.search(t)


def _contact(text: str) -> Contact:
    fields: dict[str, str] = {}
    for key, pattern, norm in (
        ("email", _EMAIL, normalize_email),
        ("linkedin", _LINKEDIN, lambda v: normalize_url(v, ("linkedin.com",))),
        ("github", _GITHUB, lambda v: normalize_url(v, ("github.com",))),
    ):
        if m := pattern.search(text):
            try:
                fields[key] = norm(m.group(0))
            except ValueError:
                continue
    for m in _PHONE.finditer(text):
        if len(re.sub(r"\D", "", m.group(0))) >= 10:  # shorter digit runs are usually year ranges
            try:
                fields["phone"] = normalize_phone(m.group(0))
                break
            except ValueError:
                continue
    return Contact(**fields)


# ── dates ───────────────────────────────────────────────────────────────────


def _take_dates(text: str) -> tuple[str, DateRange]:
    """Remove the first date range (or, failing that, a lone year) from `text`; return the rest and the dates."""
    text = _DURATION.sub(" ", text).strip()
    if m := _RANGE.search(text):
        try:
            start, end, current = parse_date_range(m.group(0))
            rest = (text[: m.start()] + " " + text[m.end() :]).strip()
            return _clean_edges(rest), DateRange(start=start, end=end, current=current)
        except ValueError:
            pass
    return text, DateRange()


def _take_year(text: str) -> tuple[str, str]:
    years = list(_YEAR.finditer(text))
    if not years:
        return text, ""
    m = years[-1]
    return _clean_edges((text[: m.start()] + " " + text[m.end() :]).strip()), m.group(0)


def _clean_edges(text: str) -> str:
    text = re.sub(r"\(\s*\)|\[\s*\]", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" ,;|–—-·•()[]:")


# ── entries ─────────────────────────────────────────────────────────────────

_SEPARATORS = (r"\s+\|\s+", r"\s+[–—]\s+", r"\s+-\s+", r"\s+(?:at|@)\s+", r",\s+")


def _split_parts(text: str) -> list[str]:
    for pattern in _SEPARATORS:
        parts = [p.strip() for p in re.split(pattern, text, maxsplit=2, flags=re.I) if p.strip()]
        if len(parts) > 1:
            return parts
    return [text.strip()] if text.strip() else []


def _title_company(parts: list[str], notes: _Notes) -> tuple[str, str, str]:
    """(title, company, location) from the pieces of a job header line."""
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return (parts[0], "", "") if _TITLE.search(parts[0]) else ("", parts[0], "")
    a, b, *more = parts
    location = more[0] if more else ""
    a_title, b_title = bool(_TITLE.search(a)), bool(_TITLE.search(b))
    if a_title and not b_title:
        return a, b, location
    if b_title and not a_title:
        return b, a, location
    notes.ambiguous += 1
    return a, b, location


def _split_company_place(company: str, location: str) -> tuple[str, str]:
    """'Globex Corporation - Delhi, India' -> ('Globex Corporation', 'Delhi, India')."""
    if location:
        return company, location
    parts = re.split(r"\s+[–—|-]\s+", company, maxsplit=1)
    if len(parts) == 2 and (_looks_like_place(parts[1]) or _looks_like_city(parts[1])) and not _TITLE.search(parts[1]):
        return parts[0].strip(), parts[1].strip()
    return company, location


def _is_detail_line(text: str) -> bool:
    return len(text) <= 90 and not re.search(r"[.!?]$", text) and len(text.split()) <= 12


def _fill_missing(entry: dict, text: str) -> None:
    """The line under a job header names the other half (company or title), optionally with a location."""
    pieces = [p.strip() for p in re.split(r"\s+[·•|]\s+", text) if p.strip()]
    first, rest = pieces[0], pieces[1:]
    if not entry["company"] and (entry["title"] or not _TITLE.search(first)):
        entry["company"] = first
    elif not entry["title"]:
        entry["title"] = first
    else:
        entry["location"] = entry["location"] or first
    if rest and not entry["location"]:
        entry["location"] = rest[0]


def _parse_experience(lines: list[str], notes: _Notes) -> list[Experience]:
    items = _marked_with_headers(lines)
    entries: list[Experience] = []
    pending: list[str] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            current["bullets"] = _join_wrapped(current.pop("raw"))
            entries.append(Experience(**current))
        current = None

    for text, kind in items:
        if kind == "prefix":
            pending.append(text)
            continue
        if kind == "header":
            flush()
            rest, dates = _take_dates(text)
            parts = _split_parts(rest)
            if pending and len(parts) <= 1:
                parts = [*pending, *parts]
            pending = []
            title, company, location = _title_company(parts, notes)
            company, location = _split_company_place(company, location)
            current = {"title": title, "company": company, "location": location, "dates": dates, "raw": []}
        elif current is not None:
            if (
                kind == "text"
                and not current["raw"]
                and not current["location"]
                and (_looks_like_place(text) or _looks_like_city(text))
            ):
                current["location"] = text  # LinkedIn prints the job's place on the line after the dates
            elif (
                kind == "text"
                and not current["raw"]
                and _is_detail_line(text)
                and not (current["title"] and current["company"])
            ):
                _fill_missing(current, text)  # "Title   dates" then "Company · Location" on the next line
            else:
                current["raw"].append(text if kind == "text" else "• " + text)
    flush()
    return entries


def _marked_with_headers(lines: list[str]) -> list[tuple[str, str]]:
    """Classify each non-empty line: header (has a date range), prefix (short lines right before a header: the
    company, or company + title as LinkedIn writes them), bullet, or text."""
    cleaned = [ln.strip() for ln in lines]
    kinds: list[tuple[str, str]] = []  # (text, kind) for non-empty lines
    for raw, text in zip(lines, cleaned, strict=True):
        if not text:
            continue
        if _bullet_text(raw) is not None:
            kinds.append((_bullet_text(raw) or text, "bullet"))
        elif _has_range(text):
            kinds.append((text, "header"))
        else:
            kinds.append((text, "text"))

    def short(text: str) -> bool:
        return len(text) <= 80 and not re.search(r"[.!?]$", text)

    for h, (_, kind) in enumerate(kinds):
        if kind != "header":
            continue
        one = kinds[h - 1] if h >= 1 else None
        two = kinds[h - 2] if h >= 2 else None
        if one and one[1] == "text" and short(one[0]) and not _has_range(one[0]):
            if two and two[1] == "text" and short(two[0]) and (_TITLE.search(one[0]) or _TITLE.search(two[0])):
                kinds[h - 2] = (two[0], "prefix")  # LinkedIn: company line, then title line, then the dates
            kinds[h - 1] = (one[0], "prefix")
    return kinds


def _parse_education(lines: list[str]) -> list[Education]:
    blocks: list[list[str]] = []
    block: list[str] = []
    for raw in lines:
        text = raw.strip()
        if not text:
            if block:
                blocks.append(block)
                block = []
            continue
        starts_new = block and _DEGREE.search(text) and any(_DEGREE.search(b) for b in block) and _complete(block)
        if starts_new:
            blocks.append(block)
            block = []
        block.append(raw)
    if block:
        blocks.append(block)
    merged: list[list[str]] = []
    for blk in blocks:
        text = " ".join(blk)
        previous = " ".join(merged[-1]) if merged else ""
        institution_only = bool(previous) and _INSTITUTION.search(previous) and not _DEGREE.search(previous)
        if institution_only and _DEGREE.search(text) and not _INSTITUTION.search(text) and not _YEAR.search(previous):
            merged[-1] = [*merged[-1], *blk]  # "State University" on one line, "BSc - Physics · (2015 - 2018)" next
        else:
            merged.append(blk)
    out: list[Education] = []
    for blk in merged:
        entry = _education_entry(blk)
        if entry:
            out.append(entry)
    return out


def _complete(block: list[str]) -> bool:
    text = " ".join(block)
    return bool(_DEGREE.search(text) and (_INSTITUTION.search(text) or len(block) > 1 or _YEAR.search(text)))


def _education_entry(block: list[str]) -> Education | None:
    details: list[str] = []
    head: list[str] = []
    for raw in block:
        bullet = _bullet_text(raw)
        (details if bullet is not None else head).append(bullet if bullet is not None else raw.strip())
    degree_kept = ""
    for k, line in enumerate(head):
        left, dot, right = line.partition(" · ")
        if dot and _DEGREE.search(left) and not _INSTITUTION.search(left):
            degree_kept = left.strip()  # LinkedIn: "Bachelor of Science - BS, Statistics · (2015 - 2018)"
            head[k] = right
    text = " | ".join(head)
    grade = ""
    if m := _GRADE.search(text):
        grade = m.group(0).strip()
        text = _clean_edges(text[: m.start()] + " " + text[m.end() :])
    text, dates = _take_dates(text)
    if dates.is_empty():
        text, year = _take_year(text)
        dates = DateRange(end=year) if year else DateRange()
    degree, institution, location = degree_kept, "", ""
    leftovers: list[str] = []
    for part in [p for chunk in text.split("|") for p in _split_parts(chunk.strip())]:
        part = _clean_edges(part)
        if not part:
            continue
        if _DEGREE.search(part) and not degree:
            degree = part
        elif _INSTITUTION.search(part) and not institution:
            institution = part
        else:
            leftovers.append(part)
    for part in leftovers:  # "Degree, Institution, Place" is the usual order when nothing was recognised
        if not degree and not institution:
            degree = part
        elif not institution:
            institution = part
        elif not degree:
            degree = part
        elif not location:
            location = part
    if not (degree or institution):
        return None
    return Education(
        degree=degree, institution=institution, location=location, dates=dates, grade=grade, details=details
    )


def _parse_projects(lines: list[str]) -> list[Project]:
    projects: list[Project] = []
    cur: dict | None = None
    after_blank = True
    for raw in lines:
        text = raw.strip()
        if not text:
            after_blank = True
            continue
        bullet = _bullet_text(raw)
        label = _TECH_LABEL.match(text)
        if cur is not None and label:
            cur["tech"] = _tech_list(label.group(1)) or cur["tech"]
        elif bullet is None and (after_blank or cur is None or (cur["bullets"] and not _continues(cur, text))):
            if cur:
                projects.append(_project(cur))
            cur = _project_header(text)
        elif cur is not None:
            if bullet is not None:
                cur["bullets"].append(bullet)
            elif cur["bullets"]:
                cur["bullets"][-1] = f"{cur['bullets'][-1]} {text}"
            elif not cur["tech"] and not cur["bullets"] and not cur["description"] and _is_tech_line(text):
                cur["tech"] = _tech_list(text)
            elif not cur["description"]:
                cur["description"] = text
            else:
                cur["description"] = f"{cur['description']} {text}"
        after_blank = False
    if cur:
        projects.append(_project(cur))
    return projects


def _continues(cur: dict, text: str) -> bool:
    return bool(cur["bullets"]) and not re.search(r"[.!?]$", cur["bullets"][-1]) and text[:1].islower()


def _tech_list(text: str) -> list[str]:
    tokens = [t.strip() for t in re.split(r"[,;/|]", text) if t.strip()]
    ok = 1 <= len(tokens) <= 10 and all(
        len(t) <= 30 and len(t.split()) <= 3 and not re.search(r"[.!?]$", t) for t in tokens
    )
    return tokens if ok else []


def _is_tech_line(text: str) -> bool:
    return bool(_tech_list(text)) and ("," in text or bool(taxonomy.find_skills(text)))


def _project_header(text: str) -> dict:
    url = ""
    if m := _URL.search(text):
        try:
            url = normalize_url(m.group(0).rstrip(".,"))
        except ValueError:
            url = ""
        text = (text[: m.start()] + " " + text[m.end() :]).strip(" ,;|–—-·•:")
    tech: list[str] = []
    if m := re.search(r"\(([^()]+)\)\s*$", text):
        tech = _tech_list(m.group(1))
        if tech:
            text = text[: m.start()].strip()
    name, description = text, ""
    for pattern in (r"\s+[–—]\s+", r"\s+-\s+", r"\s+\|\s+", r":\s+"):
        parts = re.split(pattern, text, maxsplit=1)
        if len(parts) == 2:
            name, right = parts[0].strip(), parts[1].strip()
            as_tech = _tech_list(right)
            if as_tech and not tech:
                tech = as_tech
            else:
                description = right
            break
    return {"name": name, "description": description, "tech": tech, "bullets": [], "url": url}


def _project(cur: dict) -> Project:
    return Project(
        name=cur["name"], description=cur["description"], tech=cur["tech"], bullets=cur["bullets"], url=cur["url"]
    )


def _parse_certifications(lines: list[str]) -> list[Certification]:
    out = []
    for raw in lines:
        text = _bullet_text(raw) or raw.strip()
        if not text:
            continue
        text, year = _take_year(text)
        text = _clean_edges(text)
        if text:
            out.append(Certification(name=text, date=year))
    return out


def _parse_skills(lines: list[str]) -> list[str]:
    tokens: list[str] = []
    for raw in lines:
        text = _bullet_text(raw) or raw.strip()
        text = re.sub(r"^[A-Za-z][A-Za-z &/+#.-]{1,30}:\s*", "", text)  # "Languages: Python, Go" -> "Python, Go"
        tokens += [t.strip() for t in re.split(r"[,;|•·▪\n]", text)]
    plain = re.compile(r"[\w+#.&/() '\-]+")  # no markup, braces or quotes: a skill is a short plain name
    return [
        t
        for t in tokens
        if 1 <= len(t) <= 40 and len(t.split()) <= 4 and plain.fullmatch(t) and not t.endswith((".", "!", "?"))
    ][:80]


def _parse_languages(lines: list[str]) -> list[str]:
    tokens = [t.strip() for raw in lines for t in re.split(r"[,;|•·]", _bullet_text(raw) or raw)]
    return [t for t in tokens if 1 <= len(t) <= 40][:20]


def _experience_text(sections: dict[str, list[str]]) -> list[str]:
    return [ln for key in ("summary", "experience", "projects") for ln in sections.get(key, [])]


def _parse_summary(lines: list[str], notes: _Notes) -> str:
    text = " ".join(ln.strip() for ln in lines if ln.strip())
    if len(text) > MAX_SUMMARY:
        cut = text[:MAX_SUMMARY]
        text = cut[: cut.rfind(". ") + 1] if ". " in cut else cut.rsplit(" ", 1)[0]
        notes.add("The summary was longer than the limit and was shortened at a sentence end. Check it.")
    return text


# ── entry point ─────────────────────────────────────────────────────────────


MAX_CHARS = 200_000  # far more than any CV; beyond this the rest is ignored
MAX_LINES = 5000  # a CV has a few hundred lines
MAX_LINE = 400  # a real CV line is shorter; longer runs are split so regex cost stays linear in the document size


def _bounded_lines(text: str, notes: _Notes) -> list[str]:
    """Lines of at most MAX_LINE characters (split at a space where possible). Without this, a hostile one-line
    document makes the contact regexes quadratic: 16,000 characters took 6 seconds, 60,000 over a minute."""
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        notes.add("The document is very long: only the first part was read.")
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line and (not out or not out[-1]):
            continue  # one blank line is a separator; a run of them is noise (and costs time per line)
        if len(out) >= MAX_LINES:
            notes.add("The document is very long: only the first part was read.")
            break
        while len(line) > MAX_LINE:
            cut = line.rfind(" ", MAX_LINE // 2, MAX_LINE)
            cut = cut if cut > 0 else MAX_LINE
            out.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
        out.append(line)
    return out


def read_cv(text: str) -> tuple[Profile, list[str]]:
    """Text of a CV -> (draft Profile, notes for the user). Never raises on odd content; it just finds less."""
    notes = _Notes()
    lines = _merge_wrapped_dates(_bounded_lines(text, notes))
    text = "\n".join(lines)  # every regex below runs on bounded lines (see _bounded_lines)
    head, sections = _split_sections(lines)
    name, headline, location = _parse_header(head, notes)
    if not name:
        name, headline, place = _rescue_name(sections, notes, headline)
        location = location or place
    contact = _contact(text)
    for line in sections.get("contact", []):
        if not location and (_looks_like_place(line.strip()) or _looks_like_city(line.strip())):
            location = line.strip()
    if location and not contact.location:
        contact = contact.model_copy(update={"location": location})

    def safe(label: str, fn, default):  # one malformed section must not lose the others
        try:
            return fn()
        except ValueError:
            notes.add(f"The {label} section could not be read automatically. Add it by hand.")
            return default

    experience = safe("experience", lambda: _parse_experience(sections.get("experience", []), notes), [])
    education = safe("education", lambda: _parse_education(sections.get("education", [])), [])
    projects = safe("projects", lambda: _parse_projects(sections.get("projects", [])), [])
    certs = safe("certifications", lambda: _parse_certifications(sections.get("certifications", [])), [])
    skills = _parse_skills(sections.get("skills", [])) or taxonomy.find_skills(text)
    if re.search(r"^\s*top skills\s*$", text, re.I | re.M):  # LinkedIn lists only the top three
        used = taxonomy.find_skills(" ".join(_experience_text(sections)))
        skills = [*skills, *[k for k in used if k.lower() not in {x.lower() for x in skills}]]
    profile = Profile(
        name=name,
        headline=headline,
        summary=_parse_summary(sections.get("summary", []), notes),
        contact=contact,
        skills=skills,
        languages=_parse_languages(sections.get("languages", [])),
        experience=experience,
        education=education,
        projects=projects,
        certifications=certs,
    )
    found = [
        s for s in ("summary", "experience", "education", "skills", "projects", "certifications") if sections.get(s)
    ]
    notes.items.insert(
        0,
        "Read with the basic (rule-based) reader: it copies what it recognises under standard headings. "
        "Check every section carefully, especially job titles, companies and dates.",
    )
    if not found:
        notes.add(
            "No standard section headings (Experience, Education, Skills...) were found, "
            "so only contact details and skills were read."
        )
    if notes.ambiguous:
        notes.add(
            f"{notes.ambiguous} job header(s) could not be told apart (title vs company). "
            "They were split by position: check them."
        )
    if sections.get("ignore"):
        notes.add("Sections such as awards, interests or references were not imported. Add anything important by hand.")
    return profile, notes.items
