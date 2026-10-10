"""One entry point for every kind of upload: bytes in, reviewable Profile out.

  profile JSON      -> loaded as-is
  LinkedIn .zip     -> deterministic CSV mapping (no AI)
  PDF / DOCX / TXT  -> text -> AI extraction -> grounding (or a clearly-labelled heuristic when no AI is set up)

The result is a DRAFT for the review step; nothing here marks anything ready to submit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from careerforge import skills as taxonomy
from careerforge.ai.client import AIClient
from careerforge.ai.extract import extract_profile
from careerforge.ai.grounding import GroundingReport
from careerforge.ingest.files import Document, read_document
from careerforge.ingest.linkedin import profile_from_linkedin_export
from careerforge.models import Contact, Profile
from careerforge.text import normalize_email, normalize_phone, normalize_url

LINKEDIN_PDF_HINT = (
    "Document type: a LinkedIn profile exported with 'Save to PDF'. Typical layout: a sidebar with Contact, Top "
    "Skills, Languages and Certifications, then Summary, Experience (company name, then job title, then dates and "
    "location) and Education."
)


@dataclass(frozen=True)
class IngestResult:
    profile: Profile
    source: str  # pdf | docx | txt | profile_json | linkedin_export | heuristic
    warnings: tuple[str, ...] = ()
    grounding: GroundingReport | None = None
    removed_instruction_lines: tuple[str, ...] = ()


def looks_like_linkedin_pdf(text: str) -> bool:
    return (
        bool(re.search(r"linkedin\.com/in/", text, re.I))
        and sum(h in text for h in ("Top Skills", "Languages", "Certifications", "Contact")) >= 2
    )


def with_links(text: str, links: tuple[str, ...]) -> str:
    """Hyperlink targets are invisible in extracted text; add them so they can be used (and grounded)."""
    return f"{text}\n\nLinks found in the document:\n" + "\n".join(f"- {u}" for u in links) if links else text


_PHONE = re.compile(r"\+?\d[\d\s().\-]{8,}\d")
_LINKEDIN = re.compile(r"(?:https?://)?(?:[\w-]+\.)?linkedin\.com/in/[\w\-%]+", re.I)
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9][A-Za-z0-9\-]*", re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")


def heuristic_profile(text: str) -> tuple[Profile, list[str]]:
    """No-AI fallback. Finds only what can be read reliably: contact details and known skills. Everything else (name,
    jobs, education) is left empty on purpose - guessing those is how fake CVs happen."""
    warnings = ["AI is not configured: only contact details and skills were detected. Fill in the rest manually"]
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
    return Profile(contact=Contact(**fields), skills=taxonomy.find_skills(text)), warnings


def ingest_upload(name: str, data: bytes, client: AIClient | None) -> IngestResult:
    """Read any supported upload. Raises IngestError / AIError subclasses with user-presentable messages."""
    doc: Document = read_document(name, data)

    if doc.kind == "profile_json":
        return IngestResult(Profile.from_json(doc.raw), "profile_json")
    if doc.kind == "linkedin_export":
        imported = profile_from_linkedin_export(doc.raw)
        return IngestResult(imported.profile, "linkedin_export", imported.warnings)

    text = with_links(doc.text, doc.links)
    if client is None:
        profile, notes = heuristic_profile(text)
        return IngestResult(profile, "heuristic", (*doc.warnings, *notes))

    hint = LINKEDIN_PDF_HINT if doc.kind == "pdf" and looks_like_linkedin_pdf(doc.text) else ""
    result = extract_profile(client, text, hint=hint)
    return IngestResult(
        result.profile,
        doc.kind,
        (*doc.warnings, *result.warnings),
        result.grounding,
        result.removed_instruction_lines,
    )
