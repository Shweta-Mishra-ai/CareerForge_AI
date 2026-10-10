"""Input normalisation shared by every model field.

Rules:
* Normalise, never HTML-escape. Escaping is the renderer's job (Jinja2 autoescape / XML escape).
* Reject over-long values instead of silently truncating them.
* Strip invisible/bidi control characters that can spoof or break text.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

# C0/C1 controls (except \t \n), zero-width chars, bidi embedding/override marks, BOM.
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁠-⁤﻿]")
_BULLET_GLYPH = re.compile(r"^\s*(?:[•·▪▫◦‣∙●○■□►▶*]|[-–—])\s+")


def clean_text(value: object, *, multiline: bool = False) -> str:
    """NFC-normalise, drop control chars, collapse whitespace. `None` becomes ''."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    text = _CONTROL.sub("", text).replace("\t", " ").replace("\r\n", "\n").replace("\r", "\n")
    if multiline:
        lines = [re.sub(r"[ ]+", " ", ln).strip() for ln in text.split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return re.sub(r"\s+", " ", text).strip()


def clean_bullet(value: object) -> str:
    """Single-line text with any leading bullet glyph removed ('• Built X' -> 'Built X')."""
    text = clean_text(value)
    return _BULLET_GLYPH.sub("", text).strip() if text else ""


# ── contact fields ──────────────────────────────────────────────────────────

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_HAS_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


def normalize_email(value: object) -> str:
    text = clean_text(value)
    if text.lower().startswith("mailto:"):
        text = text[7:]
    if not text:
        return ""
    if len(text) > 254 or not _EMAIL.fullmatch(text):
        raise ValueError("Not a valid email address")
    local, _, domain = text.rpartition("@")
    return f"{local}@{domain.lower()}"


def normalize_phone(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if not re.fullmatch(r"\+?[\d\s().\-]+", text):
        raise ValueError("Phone may only contain digits, spaces and + ( ) . -")
    digits = re.sub(r"\D", "", text)
    if not 7 <= len(digits) <= 15:
        raise ValueError("Phone must have 7-15 digits")
    return text


def normalize_url(value: object, host_suffixes: tuple[str, ...] | None = None) -> str:
    """Return a safe absolute http(s) URL, or '' for empty input. Raises ValueError otherwise.

    Bare domains get https://. Anything else (javascript:, data:, userinfo, spaces, quotes) is rejected, so
    a URL is always safe to put in an href. If `host_suffixes` is given the host must match one of them.
    """
    text = clean_text(value)
    if not text:
        return ""
    if re.search(r"""[\s<>"'`\\]""", text):
        raise ValueError("Link contains invalid characters")
    if not _HAS_SCHEME.match(text):
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("Only http(s) links are allowed")
    if parts.username or parts.password:
        raise ValueError("Links must not contain credentials")
    try:
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError as exc:
        raise ValueError("Malformed link") from exc
    if not host or "." not in host:
        raise ValueError("Link needs a valid domain")
    if host_suffixes and not any(host == s or host.endswith("." + s) for s in host_suffixes):
        raise ValueError(f"Expected a link on {' or '.join(host_suffixes)}")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


# ── partial dates: stored as "YYYY" or "YYYY-MM" ────────────────────────────

_MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
_PRESENT = {"present", "current", "now", "ongoing", "today", "till date", "to date", "till now"}
MIN_YEAR, MAX_YEAR = 1950, 2100


def _month_from_name(name: str) -> int | None:
    name = name.lower().rstrip(".")
    if len(name) < 3:
        return None
    for i, full in enumerate(_MONTHS, 1):
        if full == name or (len(name) == 3 and full.startswith(name)) or (name == "sept" and i == 9):
            return i
    return None


def _fmt(year: int, month: int | None) -> str:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValueError(f"Year must be between {MIN_YEAR} and {MAX_YEAR}")
    if month is None:
        return f"{year:04d}"
    if not 1 <= month <= 12:
        raise ValueError("Month must be 1-12")
    return f"{year:04d}-{month:02d}"


def normalize_partial_date(value: object) -> str:
    """'Mar 2021' / '03/2021' / '2021-3' / '2021' -> '2021-03' or '2021'. '' stays ''."""
    text = clean_text(value).lower()
    if not text:
        return ""
    if m := re.fullmatch(r"(\d{4})", text):
        return _fmt(int(m[1]), None)
    if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})", text):
        return _fmt(int(m[1]), int(m[2]))
    if m := re.fullmatch(r"(\d{1,2})[-/.](\d{4})", text):
        return _fmt(int(m[2]), int(m[1]))
    if m := re.fullmatch(r"([a-z]{3,9})\.?,?\s+(\d{4})", text):
        month = _month_from_name(m[1])
        if month:
            return _fmt(int(m[2]), month)
    raise ValueError(f"Unrecognised date: {value!r}")


def date_key(iso: str, *, end: bool = False) -> int:
    """Sortable month index. Year-only values count as Jan (start) or Dec (end)."""
    year, _, month = iso.partition("-")
    return int(year) * 12 + (int(month) if month else (12 if end else 1)) - 1


def display_date(iso: str) -> str:
    """'2021-03' -> 'Mar 2021'; '2021' -> '2021'."""
    if not iso:
        return ""
    year, _, month = iso.partition("-")
    return f"{_MONTHS[int(month) - 1][:3].title()} {year}" if month else year


def parse_date_range(text: object) -> tuple[str, str, bool]:
    """Parse free text like 'Jan 2020 – Present' or '2019-2023' into (start, end, current).

    A single date is returned as start. Raises ValueError when nothing parses.
    """
    raw = clean_text(text).strip("()[] ")
    if not raw:
        return "", "", False
    parts = re.split(r"\s*[–—]\s*|\s+(?:-|to|until)\s+", raw, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 1 and (m := re.fullmatch(r"(\d{4})\s*-\s*(\d{4}|present|current|now)", raw, re.I)):
        parts = [m[1], m[2]]
    if len(parts) == 1:
        if raw.lower() in _PRESENT:
            return "", "", True
        return normalize_partial_date(parts[0]), "", False
    left, right = (p.strip() for p in parts)
    start = normalize_partial_date(left)
    if right.lower() in _PRESENT:
        return start, "", True
    return start, normalize_partial_date(right), False
