"""LinkedIn "Get a copy of your data" export (.zip of CSV files) -> Profile.

Deterministic: LinkedIn already structured this data, so there is no LLM guessing and nothing to hallucinate.

PRIVACY: a real export also contains private messages, connections, and more. Only the explicit allow-list in
READ_FILES is ever opened; everything else in the archive is ignored unread (tested).

CAVEAT: the column names below follow LinkedIn's export as we understand it, and were written WITHOUT access to a
real export. Matching is tolerant (case, spacing, a few aliases, notes lines above the header), and unknown
columns are ignored, but verify against a real export before relying on it.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from careerforge.ingest.errors import IngestError, UnreadableDocument
from careerforge.models import (
    Certification,
    Contact,
    DateRange,
    Education,
    Experience,
    Profile,
    Project,
)
from careerforge.text import clean_text, normalize_email, normalize_partial_date, normalize_phone, normalize_url

READ_FILES = {
    "profile.csv",
    "positions.csv",
    "education.csv",
    "skills.csv",
    "certifications.csv",
    "languages.csv",
    "projects.csv",
    "email addresses.csv",
    "phonenumbers.csv",
}
MAX_ENTRY_BYTES = 5_000_000
MAX_ENTRIES = 500
_BULLET_SPLIT = re.compile(r"\n+|\s+[•▪●◦]\s+|^[•▪●◦]\s*")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class LinkedInImport:
    profile: Profile
    warnings: tuple[str, ...]
    files_used: tuple[str, ...]


def _open_zip(data: bytes) -> dict[str, bytes]:
    """Read ONLY allow-listed CSVs, with per-entry size caps. Returns {lower-case basename: bytes}."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnreadableDocument("That .zip file could not be opened; it may be damaged") from exc
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRIES:
            raise UnreadableDocument("That archive has too many files to be a LinkedIn export")
        found: dict[str, bytes] = {}
        for info in infos:
            base = PurePosixPath(info.filename.replace("\\", "/")).name.lower()
            if base not in READ_FILES or info.is_dir():
                continue  # never opened: messages, connections, etc.
            if info.file_size > MAX_ENTRY_BYTES:
                raise UnreadableDocument(f"{info.filename} is unusually large; the export was not read")
            with z.open(info) as fh:
                body = fh.read(MAX_ENTRY_BYTES + 1)
            if len(body) > MAX_ENTRY_BYTES:
                raise UnreadableDocument(f"{info.filename} is unusually large; the export was not read")
            found.setdefault(base, body)
        return found


def _rows(body: bytes, expected: set[str]) -> list[dict[str, str]]:
    """CSV -> dict rows. Tolerates UTF-8 BOM and 'Notes:' lines above the real header."""
    text = body.decode("utf-8-sig", errors="replace")
    reader = list(csv.reader(io.StringIO(text)))
    header_at = next((i for i, row in enumerate(reader) if {c.strip().lower() for c in row} & expected), None)
    if header_at is None:
        return []
    header = [c.strip().lower() for c in reader[header_at]]
    return [
        {h: clean_text(v, multiline=True) for h, v in zip(header, row, strict=False)}
        for row in reader[header_at + 1 :]
        if any(c.strip() for c in row)
    ]


def _get(row: dict[str, str], *names: str) -> str:
    for n in names:
        if row.get(n):
            return row[n]
    return ""


def _bullets(text: str) -> list[str]:
    """Free text -> bullets of <= 600 chars. Long paragraphs are split at sentences, never cut off."""
    out: list[str] = []
    for piece in (p.strip() for p in _BULLET_SPLIT.split(text) if p and p.strip()):
        current = ""
        for sentence in _SENTENCE.split(piece):
            if current and len(current) + 1 + len(sentence) > 600:
                out.append(current)
                current = ""
            while len(sentence) > 600:  # a single enormous sentence: break at a space
                cut = sentence.rfind(" ", 0, 600)
                if cut <= 0:  # no space to break at (a long URL, or text written without spaces): cut at the limit
                    cut = 600
                out.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            current = f"{current} {sentence}".strip()
        if current:
            out.append(current)
    return out


def _dates(start: str, end: str, warnings: list[str], label: str) -> DateRange:
    try:
        s = normalize_partial_date(start)
        e = normalize_partial_date(end)
        return DateRange(start=s, end=e, current=bool(s and not e))  # LinkedIn leaves "Finished On" empty if ongoing
    except ValueError:
        warnings.append(f"{label}: could not read the dates '{start}' – '{end}'")
        return DateRange()


def profile_from_linkedin_export(data: bytes) -> LinkedInImport:
    files = _open_zip(data)
    if not files:
        raise IngestError(
            "This .zip does not look like a LinkedIn data export (no Profile.csv / Positions.csv / Education.csv found)"
        )
    w: list[str] = []

    def cap(value: str, limit: int) -> str:
        if len(value) > limit:
            w.append(
                f"A value starting '{value[:30]}…' was longer than {limit} characters and was shortened; please review"
            )
        return value[:limit]

    def cap_list(items: list, limit: int, what: str) -> list:
        if len(items) > limit:
            w.append(f"{len(items)} {what} found; only the first {limit} were kept")
        return items[:limit]

    prof_rows = _rows(files.get("profile.csv", b""), {"first name", "last name", "headline", "summary"})
    p = prof_rows[0] if prof_rows else {}
    name = " ".join(x for x in (_get(p, "first name"), _get(p, "last name")) if x)

    contact: dict[str, str] = {"location": _get(p, "geo location", "location")}
    for row in _rows(files.get("email addresses.csv", b""), {"email address"}):
        primary = _get(row, "primary").lower() in ("yes", "true", "1")
        if primary or not contact.get("email"):
            try:
                contact["email"] = normalize_email(_get(row, "email address"))
            except ValueError:
                w.append("An email address in the export could not be read")
            if primary:
                break
    for row in _rows(files.get("phonenumbers.csv", b""), {"number"}):
        try:
            contact["phone"] = normalize_phone(_get(row, "number"))
            break
        except ValueError:
            w.append("A phone number in the export could not be read")
    for url in re.findall(r"https?://[^\s,\]\[]+", _get(p, "websites")):
        try:
            contact.setdefault("website", normalize_url(url))
        except ValueError:
            continue

    experience = []
    for i, r in enumerate(_rows(files.get("positions.csv", b""), {"company name", "title"}), 1):
        item = Experience(
            title=cap(_get(r, "title"), 150),
            company=cap(_get(r, "company name"), 150),
            location=cap(_get(r, "location"), 100),
            bullets=_bullets(_get(r, "description")),
            dates=_dates(_get(r, "started on"), _get(r, "finished on"), w, f"position #{i}"),
        )
        if item.title or item.company:
            experience.append(item)

    education = []
    for i, r in enumerate(_rows(files.get("education.csv", b""), {"school name", "degree name"}), 1):
        details = _bullets(_get(r, "notes"))
        if _get(r, "activities"):
            details.append(cap(f"Activities: {_get(r, 'activities')}", 600))
        item = Education(
            degree=cap(_get(r, "degree name"), 200),
            institution=cap(_get(r, "school name"), 200),
            details=cap_list(details, 15, "education notes"),
            dates=_dates(_get(r, "start date"), _get(r, "end date"), w, f"education #{i}"),
        )
        if item.dates.current:  # a missing end date on a degree means unknown/ongoing study, not a job
            item = item.model_copy(update={"dates": DateRange(start=item.dates.start)})
        if item.degree or item.institution:
            education.append(item)

    certs = []
    for i, r in enumerate(_rows(files.get("certifications.csv", b""), {"name", "authority"}), 1):
        date = ""
        try:
            date = normalize_partial_date(_get(r, "started on"))
        except ValueError:
            w.append(f"certification #{i}: could not read the date")
        try:
            url = normalize_url(_get(r, "url"))
        except ValueError:
            url = ""
        if _get(r, "name"):
            certs.append(
                Certification(name=cap(_get(r, "name"), 200), issuer=cap(_get(r, "authority"), 150), date=date, url=url)
            )

    projects = []
    for r in _rows(files.get("projects.csv", b""), {"title", "description"}):
        try:
            url = normalize_url(_get(r, "url"))
        except ValueError:
            url = ""
        if _get(r, "title"):
            projects.append(
                Project(
                    name=cap(_get(r, "title"), 150),
                    bullets=cap_list(_bullets(_get(r, "description")), 15, "project bullets"),
                    url=url,
                )
            )

    skills = [_get(r, "name") for r in _rows(files.get("skills.csv", b""), {"name"}) if _get(r, "name")]
    languages = [_get(r, "name") for r in _rows(files.get("languages.csv", b""), {"name"}) if _get(r, "name")]

    profile = Profile(
        name=cap(name, 120),
        headline=cap(_get(p, "headline"), 200),
        summary=cap(_get(p, "summary"), 1500),
        contact=Contact(**{k: v for k, v in contact.items() if v}) if contact else Contact(),
        skills=cap_list(skills, 80, "skills"),
        languages=cap_list(languages, 20, "languages"),
        experience=experience,
        education=education,
        projects=projects,
        certifications=certs,
    )
    if len(_get(p, "summary")) > 1500:
        w.append("Your LinkedIn summary is longer than 1,500 characters and was shortened; please review it")
    return LinkedInImport(profile, tuple(w), tuple(sorted(files)))
