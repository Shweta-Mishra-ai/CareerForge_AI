import io

import pytest
from helpers import assert_order, pdf_from_html
from pypdf import PdfReader, PdfWriter

from careerforge.ingest.errors import EmptyDocument, EncryptedDocument, UnreadableDocument
from careerforge.ingest.files import read_document
from careerforge.ingest.pdf import extract_pdf

SIDEBAR_LEFT = """<div style="display:flex">
<div style="width:30%;background:#eee;padding:8px"><h3>CONTACT</h3><p>sameer@example.com<br>Pune, India</p><h3>SKILLS</h3><p>SQL, Power BI<br>Excel, Python</p></div>
<div style="width:70%;padding:8px"><h1>SAMEER KHAN</h1><h3>EXPERIENCE</h3><p><b>Data Analyst, RetailCo</b> (2022 - Present)</p>
<ul><li>Built 12 Power BI dashboards for sales.</li><li>Automated weekly reports in Python.</li></ul><h3>EDUCATION</h3><p>B.Sc Statistics, Pune University, 2021</p></div></div>"""


def text_of(pdf: bytes) -> str:
    return extract_pdf(pdf)[0]


def test_regression_two_column_is_not_interleaved_like_the_old_extractor():
    t = text_of(pdf_from_html(SIDEBAR_LEFT))
    assert_order(
        t, ["CONTACT", "Pune, India", "SKILLS", "Excel, Python", "SAMEER KHAN", "EXPERIENCE", "RetailCo", "EDUCATION"]
    )
    assert "Pune, India EXPERIENCE" not in t and "SKILLS Data Analyst" not in t  # the old failure signatures


def test_sidebar_on_the_right():
    body = SIDEBAR_LEFT.replace('style="display:flex"', 'style="display:flex;flex-direction:row-reverse"')
    t = text_of(pdf_from_html(body))
    assert_order(t, ["SAMEER KHAN", "EXPERIENCE", "RetailCo", "EDUCATION", "CONTACT", "SKILLS", "Excel, Python"])


def test_full_width_header_then_two_columns():
    body = """<div style="text-align:center;padding:8px"><h1>PRIYA NAIR</h1><p>priya@example.com | Bengaluru</p></div>
    <div style="display:flex"><div style="width:35%;padding:8px"><h3>SKILLS</h3><p>Python, Go</p><h3>LANGUAGES</h3><p>English, Hindi</p></div>
    <div style="width:65%;padding:8px"><h3>EXPERIENCE</h3><p>Engineer at Acme</p><h3>PROJECTS</h3><p>Tracker app</p></div></div>"""
    assert_order(text_of(pdf_from_html(body)),
                 ["PRIYA NAIR", "priya@example.com", "SKILLS", "Python, Go", "LANGUAGES", "Hindi", "EXPERIENCE", "Acme", "PROJECTS", "Tracker"])  # fmt: skip


def test_three_columns():
    cols = "".join(
        f'<div style="width:33%;padding:8px"><h3>COL{i}</h3><p>alpha{i}<br>beta{i}</p></div>' for i in (1, 2, 3)
    )
    assert_order(text_of(pdf_from_html(f'<div style="display:flex">{cols}</div>')),
                 ["COL1", "beta1", "COL2", "beta2", "COL3", "beta3"])  # fmt: skip


def test_single_column_with_right_aligned_dates_is_not_split_into_columns():
    rows = "".join(
        f'<div style="display:flex;justify-content:space-between"><b>Role {i}, Company {i}</b><span>20{10 + i} - 20{11 + i}</span></div>'
        f"<p>Did important work number {i} for the team.</p>"
        for i in range(1, 6)
    )
    t = text_of(pdf_from_html(f"<h2>EXPERIENCE</h2>{rows}"))
    assert_order(t, ["EXPERIENCE", "Role 1", "work number 1", "Role 2", "work number 2", "Role 5", "work number 5"])
    assert "Role 3, Company 3 2013 - 2014" in t.replace("\n", " ")  # title and its dates stay together


def test_table_based_layout():
    body = "<table style='width:100%'><tr><td style='width:30%;vertical-align:top'><h3>SKILLS</h3><p>SQL<br>Excel</p></td><td style='vertical-align:top'><h3>EXPERIENCE</h3><p>Analyst at RetailCo</p></td></tr></table>"
    assert_order(text_of(pdf_from_html(body)), ["SKILLS", "Excel", "EXPERIENCE", "RetailCo"])


def test_multi_page_text_is_concatenated_in_page_order():
    body = "<p>FIRSTPAGE marker</p>" + '<div style="page-break-before:always"></div><p>SECONDPAGE marker</p>'
    text, pages, _, _ = extract_pdf(pdf_from_html(body))
    assert pages == 2 and text.index("FIRSTPAGE") < text.index("SECONDPAGE")


def test_hyperlinks_hidden_behind_labels_are_captured():
    body = '<p>Profiles: <a href="https://linkedin.com/in/priya-demo">LinkedIn</a> <a href="https://github.com/priya-demo">GitHub</a> <a href="mailto:x@y.co">mail</a></p>'
    text, _, _, links = extract_pdf(pdf_from_html(body))
    assert links == ["https://linkedin.com/in/priya-demo", "https://github.com/priya-demo"]  # mailto filtered
    assert "linkedin.com" not in text  # proves the URL was only available through the link annotation


def test_page_cap_warns_instead_of_silently_truncating():
    body = "".join(f'<p style="page-break-after:always">PAGE{i} text</p>' for i in range(1, 25))
    text, pages, warnings, _ = extract_pdf(pdf_from_html(body), max_pages=3)
    assert pages == 3 and "PAGE3" in text and "PAGE4" not in text and "only the first 3" in warnings[0]


def test_unicode_is_preserved():
    assert "Zoë Müller – 张伟" in text_of(pdf_from_html("<p>Zoë Müller – 张伟 • Résumé</p>"))


def test_encrypted_pdf_gets_a_clear_error():
    w = PdfWriter()
    w.append(PdfReader(io.BytesIO(pdf_from_html("<p>secret</p>"))))
    w.encrypt("pw")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(EncryptedDocument, match="password"):
        extract_pdf(buf.getvalue())


@pytest.mark.parametrize("data", [b"%PDF-1.4 this is not really a pdf", b"%PDF-" + b"\x00" * 50])
def test_corrupt_pdf_is_unreadable_not_a_crash(data):
    with pytest.raises((UnreadableDocument, EmptyDocument)):
        read_document("cv.pdf", data)


def test_scanned_image_only_pdf_explains_ocr_limitation():
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    with pytest.raises(EmptyDocument, match="scanned"):
        read_document("scan.pdf", pdf_from_html(f'<img src="data:image/png;base64,{png}" width="300" height="300">'))


def test_read_document_returns_pdf_metadata():
    doc = read_document("cv.PDF", pdf_from_html(SIDEBAR_LEFT))
    assert doc.kind == "pdf" and doc.pages == 1 and "SAMEER KHAN" in doc.text


def test_fuzz_no_word_is_ever_lost_or_duplicated():
    """Property: whatever the geometry, the layout algorithm returns exactly the words it was given."""
    import random

    from careerforge.ingest.pdf import Word, _xy_cut

    rng = random.Random(1234)
    for trial in range(400):
        n = rng.randint(2, 60)
        words = []
        for i in range(n):
            x0 = rng.uniform(0, 500)
            top = rng.uniform(0, 780)
            words.append(Word(f"w{trial}x{i}", x0, x0 + rng.uniform(5, 90), top, top + rng.choice([8, 10, 12, 18])))
        if trial % 3 == 0:  # make structured pages too: two blocks with a clear gutter
            words = [Word(w.text, w.x0 % 200, w.x1 % 200 + 5 if w.x1 % 200 > w.x0 % 200 else w.x0 % 200 + 6, w.top, w.bottom)
                     if i % 2 else Word(w.text, 330 + w.x0 % 150, 330 + w.x0 % 150 + 20, w.top, w.bottom) for i, w in enumerate(words)]  # fmt: skip
        out = " ".join(_xy_cut(words, 842.0)).split()
        assert sorted(out) == sorted(w.text for w in words), f"trial {trial}: words changed"


def test_dates_and_sidebars_edge_cases():
    # a date column with month names and 'Present' stays attached to its roles
    rows = "".join(
        f'<div style="display:flex;justify-content:space-between"><b>Role {i}</b><span>{m} 20{10 + i} – Present</span></div><p>Short.</p>'
        for i, m in enumerate(["Jan", "Feb", "Mar", "Apr"], 1)
    )
    t = text_of(pdf_from_html(rows)).replace("\n", " ")
    assert_order(t, ["Role 1", "Short.", "Role 2", "Role 4"])
