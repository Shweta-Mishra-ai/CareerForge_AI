"""Render a Profile as a CV: HTML, PDF, DOCX or plain text.

Every export goes through `require_ready`, so a CV with a missing name/email, leftover placeholders or nothing to
show is refused, and unconfirmed AI suggestions are never printed. `preview_html` is the only ungated path: it is for
showing a draft on screen and says so in a banner.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from careerforge.ats.checks import ParseResult, check_pdf
from careerforge.models import Profile
from careerforge.readiness import require_ready
from careerforge.render.options import DENSITY, FONT_STACKS, RenderOptions
from careerforge.render.view import build_blocks, contact_items, meta_description, short_url

TEMPLATE_DIR = Path(__file__).parent / "templates"
# The CV needs inline CSS and nothing else: no scripts, images, fonts or network. Also protects the Streamlit page
# that embeds the preview if an escaping bug ever let markup through.
CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
SIDEBAR_SECTIONS = frozenset({"skills", "languages", "certifications"})


@lru_cache(maxsize=1)
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,  # every {{ value }} is HTML-escaped; there is no |safe on user data anywhere
        undefined=StrictUndefined,  # a typo in a template fails loudly instead of printing nothing
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["short_url"] = short_url
    return env


def _render(profile: Profile, options: RenderOptions, *, draft: bool) -> str:
    fs, lh, gap, margin = DENSITY[options.density]
    return (
        _env()
        .get_template("cv.html.j2")
        .render(
            p=profile,
            o=options,
            template=options.template,
            lang=options.lang,
            accent=options.accent,
            font_stack=FONT_STACKS[options.font_key],
            fs=fs,
            lh=lh,
            gap=gap,
            margin=margin,
            paper=options.paper,
            blocks=build_blocks(profile, options),
            side=SIDEBAR_SECTIONS,
            contact=contact_items(profile.contact),
            description=meta_description(profile.summary, profile.headline, profile.name),
            draft=draft,
            csp=CSP,
        )
    )


def preview_html(profile: Profile, options: RenderOptions | None = None) -> str:
    """On-screen preview of whatever would be exported, even when the profile is not ready to submit yet."""
    from careerforge.readiness import check

    ready = check(profile).ready
    return _render(profile.exportable(), options or RenderOptions(), draft=not ready)


def render_cv_html(profile: Profile, options: RenderOptions | None = None) -> str:
    """Final HTML. Raises NotReady if the profile has blockers."""
    return _render(require_ready(profile), options or RenderOptions(), draft=False)


class PdfEngineUnavailable(RuntimeError):
    """The PDF engine (WeasyPrint and the Pango library it needs) cannot be loaded on this machine."""


@lru_cache(maxsize=1)
def _pdf_engine():
    """(HTML class, a fetcher that allows no protocol at all). A CV never needs an external image, stylesheet or
    font, so none is ever fetched. Imported lazily: without Pango the import fails, and that must only disable the
    PDF export, not the app."""
    try:
        from weasyprint import HTML, URLFetcher
    except (OSError, ImportError) as exc:
        raise PdfEngineUnavailable(
            "PDF export needs the Pango text library, which is not available on this machine. Word, text and "
            "HTML exports still work. See docs/DEPLOY.md (hosting) or the README (installing locally)."
        ) from exc
    return HTML, URLFetcher(allowed_protocols=())


@dataclass(frozen=True)
class PdfExport:
    data: bytes
    pages: int
    parse: ParseResult  # how a simple ATS text extractor reads this very file
    warnings: tuple[str, ...] = ()


def render_cv_pdf(profile: Profile, options: RenderOptions | None = None) -> PdfExport:
    """PDF via WeasyPrint, then re-read with the ATS parser so the user sees how it extracts."""
    options = options or RenderOptions()
    exportable = require_ready(profile)
    html_class, no_fetch = _pdf_engine()
    html = _render(exportable, options, draft=False)
    document = html_class(string=html, url_fetcher=no_fetch).render()
    data = document.write_pdf()
    parse = check_pdf(data, exportable)
    warnings = []
    if len(document.pages) > 2:
        warnings.append(
            f"The CV is {len(document.pages)} pages. Most recruiters expect 1-2: "
            "try 'compact' density or hide a section"
        )
    if not options.info.ats_safe:
        warnings.append(options.info.description)
    return PdfExport(data, len(document.pages), parse, tuple(warnings))
