"""One-file portfolio website: static HTML + inline CSS, no JavaScript, no external fonts, scripts or images.

Safe to host anywhere (GitHub Pages, Netlify, Cloudflare Pages, a plain web server). Everything shown comes from the
confirmed profile; nothing is written on the user's behalf. The only numbers on the page are computed from the
profile's own dates and project data.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator

from careerforge.ats.match import experience_months
from careerforge.models import Profile
from careerforge.readiness import NotReady, Readiness, check
from careerforge.render.cv import CSP, _env
from careerforge.render.options import RenderOptions
from careerforge.render.themes import THEMES, with_accent
from careerforge.render.view import build_blocks, contact_items, meta_description
from careerforge.text import normalize_url

PORTFOLIO_SECTIONS = ("about", "projects", "experience", "skills", "education", "certifications", "languages")
_TITLES = {
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
    site_url: str = ""  # the address you will publish at; enables the canonical link
    show_email: bool = True
    show_phone: bool = False  # a public phone number invites spam, so it is opt-in
    show_stats: bool = True
    hidden: frozenset[str] = frozenset()
    lang: str = "en"

    @field_validator("theme")
    @classmethod
    def _theme(cls, v: str) -> str:
        if v not in THEMES:
            raise ValueError(f"Unknown theme '{v}'. Choose one of: {', '.join(THEMES)}")
        return v

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

    def zip_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, content in (("index.html", self.html), ("README.md", self.readme), (".nojekyll", "")):
                info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))  # fixed timestamp: identical input, identical zip
                info.external_attr = 0o644 << 16
                z.writestr(info, content.encode("utf-8"))
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


def build_portfolio(
    profile: Profile, options: PortfolioOptions | None = None, *, today: date | None = None
) -> Portfolio:
    options = options or PortfolioOptions()
    today = today or date.today()
    gate = blockers(profile, options)
    if not gate.ready:
        raise NotReady(gate)
    p = profile.exportable()
    theme = THEMES[options.theme]
    if options.accent:
        theme = with_accent(theme, options.accent)

    shown = [s for s in PORTFOLIO_SECTIONS if s not in options.hidden]
    blocks = {b.name: b for b in build_blocks(p, RenderOptions())}
    sections = [s for s in shown if _CV_NAME.get(s, s) in blocks]

    kinds = {"linkedin", "github", "website"} | ({"email"} if options.show_email else set())
    kinds |= {"phone"} if options.show_phone else set()
    contact = [] if "contact" in options.hidden else contact_items(p.contact, include=frozenset(kinds))

    description = meta_description(p.summary, p.headline, p.name)
    title = f"{p.name} - {p.headline}" if p.headline else p.name
    sameas = [c.href for c in contact if c.kind in ("linkedin", "github", "website")]
    html = (
        _env()
        .get_template("portfolio.html.j2")
        .render(
            p=p,
            theme=theme,
            options=options,
            title=title,
            description=description,
            csp=CSP,
            blocks=blocks,
            sections=sections,
            titles=_TITLES,
            cv_name=_CV_NAME,
            contact=contact,
            stats=_stats(p, today) if options.show_stats else [],
            sameas=sameas,
            today=today.isoformat(),
        )
    )
    warnings = []
    if not p.summary and "about" not in options.hidden:
        warnings.append("There is no summary, so the About section is left out. Add one in your profile if you want it")
    if not p.projects and not p.experience:
        warnings.append("A portfolio with no projects or experience looks empty; add your best project")
    return Portfolio(html, _readme(p, options), tuple(warnings))


def _readme(p: Profile, options: PortfolioOptions) -> str:
    user = p.contact.github.rstrip("/").rsplit("/", 1)[-1] if p.contact.github else "your-username"
    shown = ["the links, projects and experience from your profile"]
    shown.append("your email address" if options.show_email else "no email address")
    if options.show_phone:
        shown.append("your phone number")
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
        "2. Upload `index.html` and `.nojekyll` to the repository root.",
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
    if options.site_url:
        lines += ["", f"The site address is set to {options.site_url} (used for the canonical link)."]
    return "\n".join(lines) + "\n"
