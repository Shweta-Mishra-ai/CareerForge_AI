"""Test helpers: build real PDFs/DOCX in memory so extraction is tested on genuine files."""

import io
import zipfile

from weasyprint import HTML


def pdf_from_html(body: str, css: str = "") -> bytes:
    page = f"<html><head><style>body{{font:12px sans-serif;margin:0}} @page{{size:A4;margin:12mm}} {css}</style></head><body>{body}</body></html>"
    return HTML(string=page).write_pdf()


def assert_order(text: str, markers: list[str]) -> None:
    """Every marker is present and they appear in the given order."""
    pos = []
    for m in markers:
        assert m in text, f"{m!r} missing from extracted text:\n{text}"
        pos.append(text.index(m))
    assert pos == sorted(pos), f"wrong reading order {dict(zip(markers, pos, strict=True))}:\n{text}"


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()
