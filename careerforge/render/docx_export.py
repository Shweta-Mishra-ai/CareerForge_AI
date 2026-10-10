"""Word CV. Built from real Word styles (Heading 1, List Bullet) and right-aligned tab stops, with no tables, text
boxes or images, so both Word's navigation pane and ATS parsers read it in order."""

from __future__ import annotations

import io
from datetime import datetime

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from docx.text.paragraph import Paragraph

from careerforge.models import Profile
from careerforge.readiness import require_ready
from careerforge.render.options import DENSITY, RenderOptions
from careerforge.render.view import build_blocks, contact_items

PAGE_MM = {"A4": (210, 297), "Letter": (215.9, 279.4)}
# Word resolves these by name on the reader's machine; they are the fonts the PDF fonts are metric-compatible with.
DOCX_FONT = {"sans": "Arial", "serif": "Times New Roman", "humanist": "Calibri"}


def _rgb(hex_colour: str) -> RGBColor:
    return RGBColor(int(hex_colour[1:3], 16), int(hex_colour[3:5], 16), int(hex_colour[5:7], 16))


def _font(style, name: str, size: float, *, bold: bool = False, colour: RGBColor | None = None) -> None:
    style.font.name = name
    style.font.size = Pt(size)
    style.font.bold = bold
    if colour is not None:
        style.font.color.rgb = colour
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), name)


def render_cv_docx(profile: Profile, options: RenderOptions | None = None) -> bytes:
    options = options or RenderOptions()
    p = require_ready(profile)
    size, line_height, gap, margin = DENSITY[options.density]
    font = DOCX_FONT[options.font_key]
    accent = _rgb(options.accent) if options.template != "ats-classic" else RGBColor(0, 0, 0)

    doc = Document()
    section = doc.sections[0]
    width, height = PAGE_MM[options.paper]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Mm(width), Mm(height)
    section.left_margin = section.right_margin = section.top_margin = section.bottom_margin = Mm(margin)
    text_width = Mm(width - 2 * margin)

    styles = doc.styles
    normal = styles["Normal"]
    _font(normal, font, size)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = line_height
    h1 = styles["Heading 1"]
    _font(h1, font, size + 1, bold=True, colour=accent)
    h1.paragraph_format.space_before = Pt(gap)
    h1.paragraph_format.space_after = Pt(3)
    h1.paragraph_format.keep_with_next = True
    bullet = styles["List Bullet"]
    _font(bullet, font, size)
    bullet.paragraph_format.space_after = Pt(1)
    name_style = styles.add_style("CV Name", WD_STYLE_TYPE.PARAGRAPH)
    name_style.base_style = normal
    _font(name_style, font, size + 10, bold=True, colour=accent)
    entry_style = styles.add_style("CV Entry", WD_STYLE_TYPE.PARAGRAPH)
    entry_style.base_style = normal
    _font(entry_style, font, size, bold=True)
    entry_style.paragraph_format.space_before = Pt(gap * 0.5)
    entry_style.paragraph_format.keep_with_next = True
    entry_style.paragraph_format.tab_stops.add_tab_stop(text_width, WD_TAB_ALIGNMENT.RIGHT)

    def para(text: str, style: str = "Normal") -> Paragraph:
        return doc.add_paragraph(text, style=style)

    centred = options.template == "executive"
    head = para(p.name, "CV Name")
    if centred:
        head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if p.headline:
        sub = para(p.headline)
        sub.alignment = head.alignment
    contact = "  |  ".join(c.text for c in contact_items(p.contact))
    if contact:
        line = para(contact)
        line.alignment = head.alignment

    for block in build_blocks(p, options):
        para(block.title.upper(), "Heading 1")
        if block.paragraph:
            para(block.paragraph)
        for label, names in block.skills:
            line = doc.add_paragraph()
            if label:
                line.add_run(f"{label}: ").bold = True
            line.add_run(names)
        for e in block.entries:
            row = para(f"{e.head}\t{e.when}" if e.when else e.head, "CV Entry")
            row.paragraph_format.keep_with_next = bool(e.sub or e.text or e.bullets)
            if e.sub:
                para(e.sub)
            if e.text:
                para(e.text)
            for b in e.bullets:
                para(b, "List Bullet")

    props = doc.core_properties
    now = datetime.now()  # noqa: DTZ005 - a local timestamp in the file properties is what Word itself writes
    props.title = f"{p.name} - CV"
    props.author = p.name
    props.last_modified_by = p.name
    props.subject = ""
    props.comments = ""
    props.keywords = ""
    props.created = props.modified = now
    props.language = options.lang

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
