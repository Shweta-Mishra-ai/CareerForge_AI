"""PDF -> text with column-aware reading order.

pdfplumber's own extract_text() (and layout=True) merge text from side-by-side columns line by line, which
scrambles sidebar-style CVs. Here we take word *positions* and apply a recursive XY-cut: split the page at
whitespace gutters (vertical first, so a sidebar stays one unit; horizontal when a full-width block such as a
header prevents that), then read each leaf region top-to-bottom. Geometry-based, so it does not depend on how
the PDF generator ordered its content stream. Uses only MIT-licensed libraries (pdfplumber/pdfminer).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from statistics import median

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException

from careerforge.ingest.errors import EncryptedDocument, UnreadableDocument
from careerforge.text import clean_text

MAX_PAGES = 20
MIN_GUTTER_PT = 14.0  # smallest blank vertical strip treated as a column gutter
MIN_SIDE_SHARE = 0.12  # each side of a column split must hold at least this share of the words
MIN_COLUMN_ROWS = 2  # a real column has at least this many text rows
MIN_LONGEST_COLUMN = 3  # ... and at least one of the two columns has this many
MAX_ROW_JUMP = 4.0  # ... and no jump between its consecutive rows larger than this many text heights
DATE_SIDE = 0.8  # a side made (almost) only of date tokens is a "role ... dates" column, not a real column
_BULLET_ONLY = re.compile(r"^[•·▪▫◦‣∙●○■□►▶*\-–—]+$")


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


def _gaps(intervals: list[tuple[float, float]], lo: float, hi: float, min_gap: float) -> list[tuple[float, float]]:
    """Blank stretches >= min_gap inside [lo, hi] given occupied intervals."""
    merged: list[list[float]] = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    gaps = []
    for (_, end), (start, _) in zip(merged, merged[1:], strict=False):
        if start - end >= min_gap:
            gaps.append((end, start))
    return gaps


def _best_cut(words: list[Word], axis: str, min_gap: float, *, strict: bool = False) -> float | None:
    """Midpoint of the widest usable gap along x ('v') or y ('h'), or None.

    `strict` (used only when about to split columns) also rejects sides that are sparse right-aligned metadata."""
    if axis == "v":
        spans = [(w.x0, w.x1) for w in words]
        lo, hi = min(w.x0 for w in words), max(w.x1 for w in words)
    else:
        spans = [(w.top, w.bottom) for w in words]
        lo, hi = min(w.top for w in words), max(w.bottom for w in words)
    best = None
    for a, b in sorted(_gaps(spans, lo, hi, min_gap), key=lambda g: g[0] - g[1]):  # widest first
        cut = (a + b) / 2
        left = [w for w in words if (w.x1 if axis == "v" else w.bottom) <= cut]
        right = [w for w in words if (w.x0 if axis == "v" else w.top) >= cut]
        if axis == "v":
            if (
                min(len(left), len(right)) / len(words) < MIN_SIDE_SHARE
                or any(_is_date_column(x) for x in (left, right))
                or (strict and (any(_is_sparse(x) for x in (left, right)) or _too_small_for_columns(left, right)))
            ):
                continue
        best = cut
        break
    return best


_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_TOKEN = re.compile(
    rf"^(?:\(?\d{{1,4}}[)/.,-]*|{_MONTH}|[-–—]+|present|current|now|to|till|date|\d{{1,2}}[/.-]\d{{2,4}})$", re.I
)


def _is_date_column(words: list[Word]) -> bool:
    """True for a side made almost only of dates ('Mar 2021 - Present'): right-aligned dates beside role titles.

    Reading such a side as its own column would separate every role from its date, so it is kept in the row.
    """
    return sum(bool(_DATE_TOKEN.match(w.text)) for w in words) / len(words) >= DATE_SIDE


def _row_tops(words: list[Word]) -> tuple[list[float], float]:
    """Distinct text rows (top coordinates) of a set of words, and the typical text height."""
    height = median(w.bottom - w.top for w in words) or 10.0
    tops = sorted({round(w.top / (height * 0.5)) * (height * 0.5) for w in words})
    rows: list[float] = []
    for t in tops:
        if not rows or t - rows[-1] > height * 0.75:  # rows closer than that are the same row
            rows.append(t)
    return rows, height


def _is_sparse(words: list[Word]) -> bool:
    """True when the words sit on a few, far-apart rows (right-aligned dates, URLs, locations) rather than forming a
    text column. A column's rows are contiguous; metadata rows are separated by many lines of other text."""
    rows, height = _row_tops(words)
    if len(rows) < MIN_COLUMN_ROWS:
        return True
    return max(b - a for a, b in zip(rows, rows[1:], strict=False)) > height * MAX_ROW_JUMP


def _too_small_for_columns(left: list[Word], right: list[Word]) -> bool:
    """Two columns of two rows each are far more often a heading plus a right-aligned date than real columns."""
    return max(len(_row_tops(left)[0]), len(_row_tops(right)[0])) < MIN_LONGEST_COLUMN


def _lines(words: list[Word]) -> list[str]:
    """Words of one leaf region -> text lines (top-to-bottom, left-to-right), blank line between paragraphs."""
    if not words:
        return []
    height = median(w.bottom - w.top for w in words) or 10.0
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.top, w.x0)):
        if rows and abs(w.top - rows[-1][0].top) <= height * 0.5:
            rows[-1].append(w)
        else:
            rows.append([w])
    out: list[str] = []
    prev_bottom: float | None = None
    for row in rows:
        row.sort(key=lambda w: w.x0)
        text = " ".join(w.text for w in row)
        if _BULLET_ONLY.match(text):
            continue  # a lone list marker rendered as its own line
        top = min(w.top for w in row)
        if prev_bottom is not None and top - prev_bottom > height * 0.9:
            out.append("")
        out.append(text)
        prev_bottom = max(w.bottom for w in row)
    return out


def _split_y(words: list[Word], cut: float) -> tuple[list[Word], list[Word]]:
    return [w for w in words if w.bottom <= cut], [w for w in words if w.top >= cut]


def _header_cut(words: list[Word], line_h: float) -> float | None:
    """A y-cut that isolates a header which has no column gutter of its own while the rest does.

    Without this, a centred name above a sidebar layout would let the vertical cut put the whole sidebar first.
    There is deliberately no footer counterpart: the tail of the longer column also "has no gutter", and unequal
    column lengths are far more common in CVs than true footers.
    """
    spans = [(w.top, w.bottom) for w in words]
    gaps = _gaps(spans, min(w.top for w in words), max(w.bottom for w in words), line_h * 1.3)
    for a, b in gaps:  # top-down: header candidates
        top, bottom = _split_y(words, (a + b) / 2)
        if top and bottom and not _best_cut(top, "v", MIN_GUTTER_PT) and _best_cut(bottom, "v", MIN_GUTTER_PT):
            return (a + b) / 2
    return None


def _xy_cut(words: list[Word], page_height: float, depth: int = 0) -> list[str]:
    if len(words) < 2 or depth > 8:
        return _lines(words)
    line_h = median(w.bottom - w.top for w in words) or 10.0
    if _best_cut(words, "v", MIN_GUTTER_PT) and (cut := _header_cut(words, line_h)):
        top, bottom = _split_y(words, cut)
        return [*_xy_cut(top, page_height, depth + 1), "", *_xy_cut(bottom, page_height, depth + 1)]
    if cut := _best_cut(words, "v", MIN_GUTTER_PT, strict=True):
        left = [w for w in words if w.x1 <= cut]
        right = [w for w in words if w.x0 >= cut]
        if len(left) + len(right) == len(words):
            return [*_xy_cut(left, page_height, depth + 1), "", *_xy_cut(right, page_height, depth + 1)]
    height = median(w.bottom - w.top for w in words) or 10.0
    if cut := _best_cut(words, "h", height * 1.3):
        top = [w for w in words if w.bottom <= cut]
        bottom = [w for w in words if w.top >= cut]
        if top and bottom and len(top) + len(bottom) == len(words):
            return [*_xy_cut(top, page_height, depth + 1), "", *_xy_cut(bottom, page_height, depth + 1)]
    return _lines(words)


def extract_pdf(data: bytes, *, max_pages: int = MAX_PAGES) -> tuple[str, int, list[str], list[str]]:
    """Return (text, page_count, warnings, hyperlinks). Raises EncryptedDocument / UnreadableDocument."""
    warnings: list[str] = []
    links: list[str] = []
    pages_text: list[str] = []
    total = 0
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            total = len(pdf.pages)
            if total > max_pages:
                warnings.append(f"The PDF has {total} pages; only the first {max_pages} were read")
            for page in pdf.pages[:max_pages]:
                words = [
                    Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"])
                    for w in page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
                    if w["text"].strip()
                ]
                pages_text.append("\n".join(_xy_cut(words, float(page.height))))
                for link in page.hyperlinks or []:
                    uri = str(link.get("uri") or "")
                    if uri.lower().startswith(("http://", "https://")) and uri not in links:
                        links.append(uri)
    except PdfminerException as exc:  # pdfplumber wraps pdfminer errors; the original is in args[0]
        inner = exc.args[0] if exc.args else exc
        if isinstance(inner, PDFPasswordIncorrect) or "password" in str(inner).lower():
            raise EncryptedDocument("This PDF is password-protected; remove the password and upload it again") from exc
        raise UnreadableDocument("This PDF could not be read; it may be damaged. Try re-exporting it") from exc
    except PDFPasswordIncorrect as exc:
        raise EncryptedDocument("This PDF is password-protected; remove the password and upload it again") from exc
    except (PDFSyntaxError, ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        message = str(exc).lower()
        if "password" in message or "encrypt" in message:
            raise EncryptedDocument("This PDF is password-protected; remove the password and upload it again") from exc
        raise UnreadableDocument("This PDF could not be read; it may be damaged. Try re-exporting it") from exc
    text = clean_text("\n\n".join(pages_text), multiline=True)
    return text, min(total, max_pages), warnings, links[:20]
