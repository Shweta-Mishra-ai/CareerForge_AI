"""One-file portfolio website: static HTML + inline CSS, no JavaScript, no external fonts, scripts or images.

Safe to host anywhere (GitHub Pages, Netlify, Cloudflare Pages, a plain web server). Everything shown comes from the
confirmed profile; nothing is written on the user's behalf. The only numbers on the page are computed from the
profile's own dates and project data.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, get_args
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from careerforge.ats.match import experience_months
from careerforge.models import Profile
from careerforge.outreach import attachment_name
from careerforge.readiness import NotReady, Readiness, check
from careerforge.render.cv import CSP, _env
from careerforge.render.options import RenderOptions
from careerforge.render.photo import data_uri, prepare_photo
from careerforge.render.portfolio_art import cover_svg, monogram
from careerforge.render.themes import PRESETS, THEMES, with_accent, with_preset
from careerforge.render.view import build_blocks, contact_items, meta_description
from careerforge.text import normalize_url

Layout = Literal["profile", "spotlight", "hero", "bento", "editorial"]
_HOSTNAME = re.compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
LAYOUTS: dict[str, tuple[str, str]] = {
    "profile": (
        "Profile",
        "A profile card stays beside your work as the visitor scrolls. The most familiar portfolio look.",
    ),
    "spotlight": (
        "Spotlight",
        "Dark-friendly landing page: a big gradient headline, your photo in a glowing ring, floating info cards. "
        "Looks like a modern tech or agency site.",
    ),
    "hero": (
        "Hero",
        "A big introduction at the top, then your work in a wide centred column. Feels like a landing page.",
    ),
    "bento": (
        "Bento",
        "Everything at a glance in a grid of rounded tiles (intro, figures, contact), then your work below. Clean and "
        "current, like a product page.",
    ),
    "editorial": (
        "Editorial",
        "Serif typography with section labels in the margin. Calm and print-like; suits writing-heavy CVs.",
    ),
}
LAYOUT_KEYS: list[Layout] = list(get_args(Layout))
SUMMARY_IN_HERO = {"spotlight", "bento"}  # these show the summary in the introduction instead of an About section
PORTFOLIO_SECTIONS = ("about", "projects", "experience", "skills", "education", "certifications", "languages")
PORTFOLIO_TITLES = {
    "about": "About",
    "projects": "Projects",
    "experience": "Experience",
    "skills": "Skills",
    "education": "Education",
    "certifications": "Certifications",
    "languages": "Languages",
}
_CV_NAME = {"about": "summary"}


class PortfolioOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    theme: str = "dark"
    accent: str | None = None
    preset: str | None = None  # a named colour (themes.PRESETS); unlike `accent`, fine on the automatic theme
    site_url: str = ""  # the address you will publish at; enables the canonical link
    show_email: bool = True
    show_phone: bool = False  # a public phone number invites spam, so it is opt-in
    show_stats: bool = True
    hidden: frozenset[str] = frozenset()
    order: tuple[str, ...] = ()  # sections in the order you want; any you leave out follow in the default order
    lang: str = "en"
    layout: Layout = "profile"
    show_location: bool = False  # a city on a public page is a privacy choice, so it is opt-in
    custom_domain: str = ""  # e.g. "jane.dev": writes the CNAME file GitHub Pages uses and sets the site address
    noindex: bool = False  # ask search engines not to list the page (robots.txt and a meta tag)
    include_cv: bool = False  # add the CV PDF to the download and link to it from the top of the page
    open_to_work: bool = False  # an "Open to opportunities" badge: your statement, so it is off unless you turn it on

    @field_validator("custom_domain")
    @classmethod
    def _domain(cls, v: str) -> str:
        v = v.strip().lower()
        if v and not _HOSTNAME.fullmatch(v):
            raise ValueError("The custom domain must look like jane.dev (no https://, no path)")
        return v

    @field_validator("theme")
    @classmethod
    def _theme(cls, v: str) -> str:
        if v not in THEMES:
            raise ValueError(f"Unknown theme '{v}'. Choose one of: {', '.join(THEMES)}")
        return v

    @field_validator("preset")
    @classmethod
    def _preset(cls, v: str | None) -> str | None:
        if v is not None and v not in PRESETS:
            raise ValueError(f"Unknown colour '{v}'. Choose one of: {', '.join(PRESETS)}")
        return v

    @model_validator(mode="after")
    def _one_colour(self) -> PortfolioOptions:
        if self.preset and self.accent:
            raise ValueError("Choose either a named colour or your own accent colour, not both")
        return self

    @field_validator("accent")
    @classmethod
    def _accent(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            raise ValueError("Accent colour must look like #1f4e79")
        return v.lower() if v else v

    @field_validator("site_url")
    @classmethod
    def _site(cls, v: str) -> str:
        return normalize_url(v)

    @field_validator("hidden")
    @classmethod
    def _hidden(cls, v: frozenset[str]) -> frozenset[str]:
        unknown = v - set(PORTFOLIO_SECTIONS) - {"contact"}
        if unknown:
            raise ValueError(f"Unknown sections: {', '.join(sorted(unknown))}")
        return v

    @field_validator("order")
    @classmethod
    def _order(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        unknown = set(v) - set(PORTFOLIO_SECTIONS)
        if unknown:
            raise ValueError(f"Unknown sections: {', '.join(sorted(unknown))}")
        if len(set(v)) != len(v):
            raise ValueError("A section can only appear once in the order")
        return v

    @field_validator("lang")
    @classmethod
    def _lang(cls, v: str) -> str:
        return RenderOptions(lang=v).lang


@dataclass(frozen=True)
class Stat:
    value: str
    label: str


@dataclass(frozen=True)
class Portfolio:
    html: str
    readme: str
    warnings: tuple[str, ...] = ()
    extra: dict[str, str | bytes] = field(default_factory=dict)  # robots.txt, sitemap.xml, 404.html, CNAME, the CV

    def files(self) -> dict[str, bytes]:
        """Every file of the site, in a fixed order."""
        base = {"index.html": self.html, "README.md": self.readme, ".nojekyll": ""}
        merged = base | dict(sorted(self.extra.items()))
        return {k: v.encode("utf-8") if isinstance(v, str) else v for k, v in merged.items()}

    def zip_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, content in self.files().items():
                info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))  # fixed timestamp: identical input, identical zip
                info.external_attr = 0o644 << 16
                z.writestr(info, content)
        return buf.getvalue()


def blockers(profile: Profile, options: PortfolioOptions) -> Readiness:
    """A portfolio needs a real name and something to show. An email is only required if it will be displayed."""
    kept = []
    for issue in check(profile).blockers:
        if issue.code == "R002":
            continue
        if issue.code == "R007" and not options.show_email:
            continue
        kept.append(issue)
    return Readiness(tuple(kept))


def _stats(p: Profile, today: date) -> list[Stat]:
    stats = []
    years = experience_months(p, today) // 12
    if years >= 1:
        stats.append(Stat(str(years), "year of experience" if years == 1 else "years of experience"))
    if p.projects:
        stats.append(Stat(str(len(p.projects)), "project" if len(p.projects) == 1 else "projects"))
    stars = sum(pr.stars for pr in p.projects)
    if stars:
        stats.append(Stat(str(stars), "GitHub star" if stars == 1 else "GitHub stars"))
    return stats


_PAIRABLE = ("education", "certifications", "languages")


def _rows(sections: list[str], *, pair: bool) -> list[list[str]]:
    """Section rows. Short sections that sit next to each other (education, certifications, languages) share a row of
    two, so the page has no half-empty bands; everything else is a row of its own."""
    rows: list[list[str]] = []
    for name in sections:
        if pair and name in _PAIRABLE and rows and rows[-1][0] in _PAIRABLE and len(rows[-1]) == 1:
            rows[-1].append(name)
        else:
            rows.append([name])
    return rows


def _current_role(p: Profile):
    """The role marked as current, for the introduction card; None when no role is marked current."""
    return next((e for e in p.experience if e.dates.current and (e.title or e.company)), None)


def _initials(name: str) -> str:
    """First letters of the first and last name ("PN"); one letter for a single name; a dot if there is no letter."""
    words = [w for w in re.split(r"\s+", name.strip()) if any(c.isalpha() for c in w)]
    letters = [next(c for c in w if c.isalpha()).upper() for w in (words[:1] + words[-1:] if len(words) > 1 else words)]
    return "".join(letters) or "•"


def _favicon(name: str, theme) -> str:
    """A data: URI for a round SVG icon with the person's initials (no image file, no request)."""
    initials = _initials(name)
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
        f"<circle cx='32' cy='32' r='32' fill='{theme.accent}'/>"
        f"<text x='32' y='42' font-size='28' text-anchor='middle' font-family='sans-serif' font-weight='700' "
        f"fill='{theme.accent_text}'>{initials}</text></svg>"
    )
    return "data:image/svg+xml," + quote(svg, safe="")


def _structured_data(p: Profile, description: str, site_url: str, sameas: list[str]) -> dict:
    person: dict = {"@context": "https://schema.org", "@type": "Person", "name": p.name}
    if p.headline:
        person["jobTitle"] = p.headline
    if description:
        person["description"] = description
    if site_url:
        person["url"] = site_url
    if sameas:
        person["sameAs"] = sameas
    if p.skills:
        person["knowsAbout"] = p.skills[:20]
    current = next((e for e in p.experience if e.dates.current and e.company), None)
    if current:  # only a role the person marked as current
        person["worksFor"] = {"@type": "Organization", "name": current.company}
    schools = list(dict.fromkeys(e.institution for e in p.education if e.institution))[:5]
    if schools:
        person["alumniOf"] = [{"@type": "EducationalOrganization", "name": n} for n in schools]
    return person


def _extra_files(
    p: Profile, options: PortfolioOptions, site_url: str, theme, today: date, cv: bytes | None, cv_name: str
) -> dict[str, str | bytes]:
    extra: dict[str, str | bytes] = {}
    if options.noindex:
        extra["robots.txt"] = "User-agent: *\nDisallow: /\n"
    else:
        extra["robots.txt"] = "User-agent: *\nAllow: /\n" + (
            f"\nSitemap: {site_url.rstrip('/')}/sitemap.xml\n" if site_url else ""
        )
        if site_url:
            extra["sitemap.xml"] = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"  <url><loc>{xml_escape(site_url)}</loc><lastmod>{today.isoformat()}</lastmod></url>\n"
                "</urlset>\n"
            )
    extra["404.html"] = (
        _env()
        .get_template("portfolio_404.html.j2")
        .render(p=p, theme=theme, options=options, csp=CSP, home=site_url or "/", favicon=_favicon(p.name, theme))
    )
    if options.custom_domain:
        extra["CNAME"] = options.custom_domain + "\n"
    if cv is not None:
        extra[cv_name] = cv
    return extra


def build_portfolio(
    profile: Profile,
    options: PortfolioOptions | None = None,
    *,
    today: date | None = None,
    cv_pdf: bytes | None = None,
    photo: bytes | None = None,
) -> Portfolio:
    """The site. `photo` is the raw upload: it is re-saved here (see render.photo), never embedded as given."""
    options = options or PortfolioOptions()
    today = today or date.today()
    gate = blockers(profile, options)
    if not gate.ready:
        raise NotReady(gate)
    p = profile.exportable()
    photo_uri = data_uri(prepare_photo(photo)) if photo else ""
    theme = THEMES[options.theme]
    if options.preset:
        theme = with_preset(theme, options.preset)
    elif options.accent:
        theme = with_accent(theme, options.accent)

    site_url = options.site_url or (f"https://{options.custom_domain}/" if options.custom_domain else "")
    options = options.model_copy(update={"site_url": site_url})
    cv_name = attachment_name(p, "CV", "pdf")
    cv_link = cv_name if options.include_cv and cv_pdf else ""

    ordered = [*options.order, *(s for s in PORTFOLIO_SECTIONS if s not in options.order)]
    shown = [s for s in ordered if s not in options.hidden]
    blocks = {b.name: b for b in build_blocks(p, RenderOptions())}
    sections = [s for s in shown if _CV_NAME.get(s, s) in blocks]

    kinds = {"linkedin", "github", "website"} | ({"email"} if options.show_email else set())
    kinds |= {"phone"} if options.show_phone else set()
    contact = [] if "contact" in options.hidden else contact_items(p.contact, include=frozenset(kinds))

    description = meta_description(p.summary, p.headline, p.name)
    title = f"{p.name} - {p.headline}" if p.headline else p.name
    sameas = [c.href for c in contact if c.kind in ("linkedin", "github", "website")]
    current = _current_role(p) if "experience" in sections else None
    html = (
        _env()
        .get_template(f"portfolio_{options.layout}.html.j2")
        .render(
            p=p,
            theme=theme,
            options=options,
            title=title,
            description=description,
            csp=CSP,
            blocks=blocks,
            sections=sections,
            rows=_rows(
                [s for s in sections if not (s == "about" and options.layout in SUMMARY_IN_HERO)],
                pair=options.layout != "editorial",
            ),
            top_skills=p.skills[:4] if "skills" in sections else [],
            current=current,
            current_mono=monogram(current.company or current.title) if current else "",
            photo=photo_uri,
            titles=PORTFOLIO_TITLES,
            cv_name=_CV_NAME,
            contact=contact,
            stats=_stats(p, today) if options.show_stats else [],
            sameas=sameas,
            person=_structured_data(p, description, site_url, sameas),
            favicon=_favicon(p.name, theme),
            cover=cover_svg,
            monos=[monogram(e.company or e.title) for e in p.experience],
            initials=_initials(p.name),
            where=p.contact.location if options.show_location else "",
            mail=next((c for c in contact if c.kind == "email"), None),
            cv_link=cv_link,
            featured=[pr for pr in p.projects if pr.featured],
            others=[pr for pr in p.projects if not pr.featured],
            today=today.isoformat(),
        )
    )
    warnings = []
    if options.include_cv and not cv_pdf:
        warnings.append("The CV PDF could not be made, so the page has no CV download link")
    if (
        options.custom_domain
        and options.site_url
        and not options.site_url.startswith(f"https://{options.custom_domain}")
    ):
        warnings.append(f"The site address and the custom domain ({options.custom_domain}) are different")
    if not p.summary and "about" not in options.hidden:
        warnings.append("There is no summary, so the About section is left out. Add one in your profile if you want it")
    if not p.projects and not p.experience:
        warnings.append("A portfolio with no projects or experience looks empty; add your best project")
    extra = _extra_files(p, options, site_url, theme, today, cv_pdf if cv_link else None, cv_name)
    return Portfolio(html, _readme(p, options, cv_link), tuple(warnings), extra)


def _readme(p: Profile, options: PortfolioOptions, cv_link: str = "") -> str:
    user = p.contact.github.rstrip("/").rsplit("/", 1)[-1] if p.contact.github else "your-username"
    shown = ["the links, projects and experience from your profile"]
    shown.append("your email address" if options.show_email else "no email address")
    if options.show_phone:
        shown.append("your phone number")
    if cv_link:
        shown.append(f"a link to your CV (`{cv_link}`, which is also in this folder)")
    lines = [
        f"# {p.name} - portfolio website",
        "",
        "This folder is a complete website: `index.html` is the whole site (the styles are inside it). It uses no",
        "JavaScript, no external fonts and no tracking, so it works on any static host.",
        "",
        "## Before you publish",
        "",
        f"The page is public. It shows: {'; '.join(shown)}.",
        "Open `index.html` in a browser once and remove anything you do not want strangers to see: generate the",
        "portfolio again with that section hidden.",
        "",
        "## Publish for free (pick one)",
        "",
        "**GitHub Pages**",
        f"1. Create a public repository. For a site at `https://{user}.github.io`, name it exactly `{user}.github.io`.",
        "2. Upload every file in this folder to the repository root (at least `index.html` and `.nojekyll`).",
        "3. In the repository's Settings, open Pages and publish from the main branch (root folder).",
        "",
        "**Netlify Drop**: drag this unzipped folder onto the drop area at app.netlify.com/drop.",
        "",
        "**Cloudflare Pages / Vercel**: create a project, choose direct upload (or connect the repository) and use",
        "this folder as the output. There is no build step.",
        "",
        "Menu names on these services change from time to time. If a step does not match what you see, search for",
        'the service\'s "deploy a static site" guide.',
        "",
        "## Updating",
        "",
        "Change your profile in CareerForge, generate the portfolio again and upload the new `index.html`.",
    ]
    lines += [
        "",
        "## What else is in this folder",
        "",
        "* `robots.txt`: "
        + ("asks search engines NOT to list the page." if options.noindex else "lets search engines list the page."),
        "* `404.html`: the page shown for a wrong address (GitHub Pages and Netlify use it automatically).",
    ]
    if not options.noindex and options.site_url:
        lines.append("* `sitemap.xml`: tells search engines the address of the page.")
    if options.custom_domain:
        lines += [
            f"* `CNAME`: tells GitHub Pages to serve the site at {options.custom_domain}. You still have to point the",
            "  domain's DNS at GitHub Pages in your domain provider's settings (see GitHub's custom-domain guide).",
        ]
    lines += [
        "",
        "The page has no preview image, so links shared on social media show text only.",
    ]
    if options.site_url:
        lines += ["", f"The site address is set to {options.site_url} (used for the canonical link)."]
    return "\n".join(lines) + "\n"
