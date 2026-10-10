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


def pdf_with_ruled_table(lines: list[str], cells: list[list[str]]) -> bytes:
    """Hand-written PDF: body text lines + a 2-column table drawn with real ruling lines (as Word does)."""
    content = ["BT /F1 11 Tf 40 780 Td 14 TL"]
    content += [f"({t.replace('(', '[').replace(')', ']')}) Tj T*" for t in lines] + ["ET"]
    top, row_h, col_w, x0 = 600, 24, 200, 40
    rows, cols = len(cells), len(cells[0])
    for r in range(rows + 1):
        y = top - r * row_h
        content.append(f"{x0} {y} m {x0 + cols * col_w} {y} l S")
    for c in range(cols + 1):
        x = x0 + c * col_w
        content.append(f"{x} {top} m {x} {top - rows * row_h} l S")
    for r, row in enumerate(cells):
        for c, text in enumerate(row):
            content.append(f"BT /F1 10 Tf {x0 + c * col_w + 6} {top - r * row_h - 16} Td ({text}) Tj ET")
    stream = "\n".join(content).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)
