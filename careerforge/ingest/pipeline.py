"""One entry point for every kind of upload: bytes in, reviewable Profile out.

  profile JSON      -> loaded as-is
  LinkedIn .zip     -> deterministic CSV mapping (no AI)
  PDF / DOCX / TXT  -> text -> AI extraction -> grounding (or a clearly-labelled heuristic when no AI is set up)

The result is a DRAFT for the review step; nothing here marks anything ready to submit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from careerforge.ai.client import AIClient
from careerforge.ai.extract import extract_profile
from careerforge.ai.grounding import GroundingReport, ground_profile
from careerforge.ingest.files import Document, read_document
from careerforge.ingest.linkedin import profile_from_linkedin_export
from careerforge.ingest.rules import read_cv
from careerforge.models import Profile

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
    """The no-AI reader: rule-based, copies only what is written under standard headings (see ingest.rules)."""
    return read_cv(text)


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
        draft, notes = heuristic_profile(text)
        profile, report = ground_profile(draft, text)  # same safety net as AI output
        return IngestResult(profile, "heuristic", (*doc.warnings, *notes), report)

    hint = LINKEDIN_PDF_HINT if doc.kind == "pdf" and looks_like_linkedin_pdf(doc.text) else ""
    result = extract_profile(client, text, hint=hint)
    return IngestResult(
        result.profile,
        doc.kind,
        (*doc.warnings, *result.warnings),
        result.grounding,
        result.removed_instruction_lines,
    )
