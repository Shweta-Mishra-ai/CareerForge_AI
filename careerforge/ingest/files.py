"""Uploaded file bytes -> a Document (text + metadata), with type sniffing and size limits.

The extension is only a hint: content is sniffed (PDF magic bytes, ZIP/DOCX structure, JSON profile envelope),
and a mismatch is an error rather than a guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Literal

from careerforge.ingest.docx_reader import extract_docx
from careerforge.ingest.errors import (
    EmptyDocument,
    FileTooLarge,
    UnreadableDocument,
    UnsupportedFormat,
)
from careerforge.ingest.pdf import extract_pdf
from careerforge.models import FILE_KIND
from careerforge.text import clean_text

MAX_FILE_BYTES = 10_000_000
MIN_TEXT_CHARS = 40

Kind = Literal["pdf", "docx", "txt", "profile_json", "linkedin_export"]


@dataclass(frozen=True)
class Document:
    text: str
    kind: Kind
    pages: int = 1
    warnings: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    raw: bytes = field(default=b"", repr=False)  # only set for kinds that are parsed structurally later


def sniff(name: str, data: bytes) -> Kind:
    head = data[:8]
    ext = PurePath(name or "").suffix.lower()
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK"):
        if ext == ".zip":
            return "linkedin_export"
        if ext in (".docx", ""):
            return "docx"
        if ext == ".docm":
            raise UnsupportedFormat("Macro-enabled Word files are not accepted; save a plain .docx instead")
        if ext == ".xlsx" or ext == ".pptx":
            raise UnsupportedFormat(f"{ext} files are not supported; upload a PDF, DOCX or TXT CV")
        return "linkedin_export" if _zip_has_csv(data) else "docx"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise UnsupportedFormat("Old Word (.doc) files are not supported; save as .docx or PDF and upload again")
    if ext in (".pdf", ".docx"):
        raise UnsupportedFormat(f"This file is named {ext} but is not a real {ext[1:].upper()} file")
    if ext == ".json" or data.lstrip()[:1] == b"{":
        return "profile_json"
    if ext in (".txt", ".md", ".text", ""):
        return "txt"
    raise UnsupportedFormat(
        "Unsupported file type. Upload a PDF, DOCX, TXT, LinkedIn data export (.zip) or profile JSON"
    )


def _zip_has_csv(data: bytes) -> bool:
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return any(n.lower().endswith(".csv") for n in z.namelist())
    except zipfile.BadZipFile:
        return False


def _decode(data: bytes) -> tuple[str, list[str]]:
    if b"\x00" in data[:4096]:
        raise UnreadableDocument("This file looks like binary data, not text")
    try:
        return data.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), ["The file was not UTF-8; it was read as Windows-1252"]


def read_document(name: str, data: bytes) -> Document:
    """Read an uploaded file. Raises IngestError subclasses with user-presentable messages."""
    if not data:
        raise EmptyDocument("The file is empty")
    if len(data) > MAX_FILE_BYTES:
        raise FileTooLarge(f"The file is larger than {MAX_FILE_BYTES // 1_000_000} MB")
    kind = sniff(name, data)

    if kind == "pdf":
        text, pages, warnings, links = extract_pdf(data)
        if len(text) < MIN_TEXT_CHARS:
            raise EmptyDocument(
                "No text could be read from this PDF. It is probably a scanned image; OCR is not supported, so "
                "export a text-based PDF or paste the text instead"
            )
        return Document(text, "pdf", pages, tuple(warnings), tuple(links))
    if kind == "docx":
        text, links = extract_docx(data)
        if len(text) < MIN_TEXT_CHARS:
            raise EmptyDocument("No text could be read from this Word file")
        return Document(text, "docx", 1, (), tuple(links))
    if kind == "profile_json":
        try:
            envelope = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UnreadableDocument("That JSON file could not be read") from exc
        if not isinstance(envelope, dict) or envelope.get("kind") != FILE_KIND:
            raise UnsupportedFormat("That JSON file is not a CareerForge profile file")
        return Document("", "profile_json", 1, (), (), raw=data)
    if kind == "linkedin_export":
        return Document("", "linkedin_export", 1, (), (), raw=data)

    text, warnings = _decode(data)
    text = clean_text(text, multiline=True)
    if len(text) < MIN_TEXT_CHARS:
        raise EmptyDocument("There is not enough text in this file to build a profile from")
    return Document(text, "txt", 1, tuple(warnings))
