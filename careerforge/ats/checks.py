"""Profile- and file-level checks that do not need a job description: structure, content quality, PDF parseability.

Each check is a named, visible rule with points, so the resulting number can be explained line by line.
"""

from __future__ import annotations

import difflib
import io
import re
from dataclasses import dataclass, field

import pdfplumber

from careerforge.ats.match import FIRST_PERSON, starts_with_action_verb
from careerforge.ingest.pdf import extract_pdf
from careerforge.models import Profile
from careerforge.nlp import normalize
from careerforge.text import date_key


@dataclass(frozen=True)
class Check:
    label: str
    passed: bool
    points: float
    detail: str = ""


def score_checks(checks: list[Check]) -> int:
    total = sum(c.points for c in checks)
    return round(100 * sum(c.points for c in checks if c.passed) / total) if total else 0


# ── structure (profile-level) ───────────────────────────────────────────────


def structure_checks(p: Profile) -> list[Check]:
    c = p.contact
    dated = [e for e in p.experience if e.dates.start]
    in_order = all(date_key(a.dates.start) >= date_key(b.dates.start) for a, b in zip(dated, dated[1:], strict=False))
    has_content = bool(p.experience or p.projects)
    return [
        Check("Full name present", bool(p.name), 2),
        Check("Email address present", bool(c.email), 2, "Recruiters and ATS forms need a reachable email"),
        Check("Phone number present", bool(c.phone), 1),
        Check("Location present", bool(c.location), 1, "Many ATS filter candidates by location"),
        Check("Work experience or projects listed", has_content, 3),
        Check(
            "Every role has a start date",
            all(e.dates.start for e in p.experience) and has_content,
            2,
            "ATS parsers compute tenure from dates",
        ),
        Check("Roles are in reverse-chronological order", in_order, 1),
        Check("Education listed", bool(p.education), 1),
        Check("Skills section present", bool(p.skills), 2),
        Check("Professional summary present", bool(p.summary), 1),
        Check("LinkedIn or GitHub link present", bool(c.linkedin or c.github), 1),
    ]


# ── content quality (bullets) ───────────────────────────────────────────────


@dataclass(frozen=True)
class QualityResult:
    score: int | None
    checks: tuple[Check, ...] = ()
    weak_bullets: tuple[tuple[str, str], ...] = ()  # (path, text) lacking a measurable result


def _bullets(p: Profile) -> list[tuple[str, str]]:
    out = [(f"experience[{i}].bullets[{j}]", b) for i, e in enumerate(p.experience) for j, b in enumerate(e.bullets)]
    for i, pr in enumerate(p.projects):
        items = pr.bullets or ([pr.description] if pr.description else [])
        out += [(f"projects[{i}].bullets[{j}]", b) for j, b in enumerate(items)]
    return out


def quality(p: Profile) -> QualityResult:
    bullets = _bullets(p)
    if not bullets:
        return QualityResult(None)
    n = len(bullets)
    with_numbers = [x for x in bullets if re.search(r"\d", x[1])]
    verbs = sum(starts_with_action_verb(b) for _, b in bullets)
    sized = sum(40 <= len(b) <= 220 for _, b in bullets)
    pronouns = sum(bool(FIRST_PERSON.search(b)) for _, b in bullets)
    summary_ok = 60 <= len(p.summary) <= 600
    summary_msg = "summary is 60-600 characters" if summary_ok else "summary missing or not 60-600 characters"
    parts = [
        (0.35, min(1.0, len(with_numbers) / n / 0.5), f"{len(with_numbers)}/{n} bullets contain a number (aim: half)"),
        (0.25, min(1.0, verbs / n / 0.7), f"{verbs}/{n} bullets start with an action verb (aim: 70%)"),
        (0.15, min(1.0, sized / n / 0.8), f"{sized}/{n} bullets are 40-220 characters (aim: 80%)"),
        (0.15, 1.0 - min(1.0, pronouns / n * 4), f"{pronouns}/{n} bullets use first person (aim: none)"),
        (0.10, 1.0 if summary_ok else 0.0, summary_msg),
    ]
    score = round(100 * sum(w * v for w, v, _ in parts))
    checks = tuple(Check(text, v >= 0.99, w * 100, f"{v:.0%}") for w, v, text in parts)
    weak = tuple(x for x in bullets if not re.search(r"\d", x[1]))
    return QualityResult(score, checks, weak)


# ── PDF parseability (file-level) ───────────────────────────────────────────

_SECTION_NAMES = {
    "experience": r"(?:work |professional |employment )?(?:experience|history)|employment|career",
    "education": r"education|academic.*|qualifications?",
    "skills": r"(?:technical |key |core )?(?:skills|competencies)|technologies|expertise",
}


@dataclass(frozen=True)
class ParseResult:
    score: int
    checks: tuple[Check, ...] = ()
    findings: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


def _linear_text(data: bytes, max_pages: int = 20) -> tuple[str, int, int, int]:
    """Stream-order text as a simple ATS would read it, plus (pages, tables, images)."""
    texts, tables, images = [], 0, 0
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = len(pdf.pages)
        for page in pdf.pages[:max_pages]:
            texts.append(page.extract_text() or "")
            tables += len(page.find_tables())
            images += len(page.images)
    return "\n".join(texts), pages, tables, images


def check_pdf(data: bytes, p: Profile) -> ParseResult:
    """How well would a simple, linear PDF text extractor read this file? Evidence comes from the file itself."""
    try:
        linear, pages, tables, images = _linear_text(data)
        smart, *_ = extract_pdf(data)
    except Exception:  # unreadable PDFs are reported as such rather than raised into the UI
        return ParseResult(0, (Check("PDF can be read", False, 100),), ("The PDF could not be read at all",))
    findings: list[str] = []
    checks: list[Check] = []

    readable = len(linear.strip()) >= 200
    checks.append(Check("Text can be extracted from the PDF", readable, 30, f"{len(linear.strip())} characters"))
    if not readable:
        findings.append("The PDF has (almost) no extractable text: it is probably an image. ATS cannot read images")
        return ParseResult(0, tuple(checks), tuple(findings))

    garbled = "(cid:" in linear
    checks.append(Check("Characters decode properly", not garbled, 10))
    if garbled:
        findings.append("Some characters are unreadable (broken font encoding). Re-export the PDF with standard fonts")

    a, b = linear.split(), smart.split()
    same_order = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if len(a) < 4000 else 1.0
    in_order = same_order >= 0.9
    checks.append(
        Check(
            "Reading order is the same in simple and layout-aware extraction", in_order, 25, f"{same_order:.0%} similar"
        )
    )
    if not in_order:
        findings.append(
            "Side-by-side columns: a simple ATS reads across the columns and mixes sections together. "
            "Use a single column, or put the sidebar content in the main flow"
        )

    flat = normalize(linear)
    squashed = flat.replace(" ", "")
    wanted = [
        p.name,
        *[e.company for e in p.experience],
        *[e.title for e in p.experience],
        *[e.institution for e in p.education],
    ]
    wanted = [w for w in wanted if w]
    found = [w for w in wanted if normalize(w) in flat or normalize(w).replace(" ", "") in squashed]
    coverage = (len(found) / len(wanted)) if wanted else 1.0
    checks.append(
        Check(
            "Your name, employers, titles and schools appear in the extracted text",
            coverage >= 0.9,
            20,
            f"{coverage:.0%}",
        )
    )
    if coverage < 0.9:
        lost = [w for w in wanted if w not in found][:4]
        findings.append(f"These details could not be found in the extracted text: {', '.join(lost)}")

    head = "\n".join(linear.splitlines()[:15])
    head_digits = re.sub(r"\D", "", head)
    contact_on_top = bool(
        (p.contact.email and p.contact.email.lower() in head.lower())
        or (p.contact.phone and re.sub(r"\D", "", p.contact.phone)[-7:] in head_digits)
    )
    if p.contact.email or p.contact.phone:
        checks.append(Check("Contact details are near the top of the page", contact_on_top, 5))
        if not contact_on_top:
            findings.append(
                "Put your email/phone in the first lines of the page (not only in a header/footer or the sidebar)"
            )

    lines = [ln.strip().rstrip(":").lower() for ln in linear.splitlines() if 2 < len(ln.strip()) <= 40]
    missing = [k for k, pat in _SECTION_NAMES.items() if not any(re.fullmatch(pat, ln) for ln in lines)]
    checks.append(
        Check("Standard section headings (Experience, Education, Skills)", not missing, 10, ", ".join(missing))
    )
    if missing:
        findings.append(
            f"Use standard headings that ATS recognise; not found: {', '.join(missing)} "
            "(for example 'Work Experience', 'Education', 'Skills')"
        )

    # Only tables with visible ruling lines are detectable. Borderless layout tables are covered indirectly by the
    # reading-order comparison above (columns that read out of order), not by this check.
    checks.append(Check("No bordered tables", tables == 0, 5, f"{tables} found"))
    if tables:
        findings.append("Tables can be read cell by cell in the wrong order; use plain paragraphs and bullets")
    checks.append(Check("No decorative images", images <= 2, 3, f"{images} found"))
    if images > 2:
        findings.append("Several images found: any text inside images is invisible to ATS")

    notes = ()
    if pages > 2:
        notes = (f"The CV is {pages} pages; most recruiters expect 1-2",)
    return ParseResult(score_checks(checks), tuple(checks), tuple(findings), notes)
