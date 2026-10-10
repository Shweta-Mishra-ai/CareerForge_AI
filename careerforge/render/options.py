"""What the user can change about a rendered CV. Everything here is an allowlist or a validated value,
so an option can never inject markup or CSS into the output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from markupsafe import Markup
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from careerforge.models import Profile

SectionName = Literal["summary", "experience", "projects", "education", "skills", "certifications", "languages"]
SECTIONS: tuple[SectionName, ...] = (
    "summary",
    "experience",
    "projects",
    "education",
    "skills",
    "certifications",
    "languages",
)
# Headings are the plain names ATS parsers look for; they are deliberately not customisable.
SECTION_TITLES: dict[str, str] = {
    "summary": "Summary",
    "experience": "Work Experience",
    "projects": "Projects",
    "education": "Education",
    "skills": "Skills",
    "certifications": "Certifications",
    "languages": "Languages",
}


@dataclass(frozen=True)
class TemplateInfo:
    key: str
    label: str
    description: str
    ats_safe: bool
    columns: int


TEMPLATES: dict[str, TemplateInfo] = {
    "ats-classic": TemplateInfo(
        "ats-classic", "ATS Classic", "Single column, serif-free, black on white. The safest choice.", True, 1
    ),
    "ats-modern": TemplateInfo(
        "ats-modern", "ATS Modern", "Single column with an accent colour for headings and rules.", True, 1
    ),
    "executive": TemplateInfo(
        "executive", "Executive", "Single column, centred header and a serif body. Suits senior profiles.", True, 1
    ),
    "sidebar": TemplateInfo(
        "sidebar",
        "Designed Sidebar",
        "Two columns with a coloured sidebar. Looks distinctive but simple ATS parsers may mix the columns: "
        "check the ATS parse result before sending it through an online application form.",
        False,
        2,
    ),
}

# Font stacks come from this table only; the values are trusted constants, never user input.
# The first families are metric-compatible with Arial/Times/Calibri and come from packages.txt on Streamlit Cloud.
FONT_STACKS: dict[str, Markup] = {
    "sans": Markup("'Liberation Sans', Arial, Helvetica, sans-serif"),
    "serif": Markup("'Liberation Serif', 'Times New Roman', Times, serif"),
    "humanist": Markup("Carlito, Calibri, 'Liberation Sans', Arial, sans-serif"),
}

# (base font size pt, line height, section gap pt, page margin mm)
DENSITY: dict[str, tuple[float, float, float, float]] = {
    "compact": (9.5, 1.28, 8, 12),
    "normal": (10.5, 1.38, 11, 15),
    "relaxed": (11, 1.5, 14, 18),
}
PAPER_SIZES = ("A4", "Letter")
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
DEFAULT_ACCENT = "#1f4e79"


def _luminance(hex_colour: str) -> float:
    def channel(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 2 contrast ratio between two #rrggbb colours (1.0 - 21.0)."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class RenderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    template: str = "ats-classic"
    accent: str = DEFAULT_ACCENT
    font: Literal["sans", "serif", "humanist"] | None = None  # None = the template's own default
    paper: Literal["A4", "Letter"] = "A4"
    density: Literal["compact", "normal", "relaxed"] = "normal"
    order: tuple[SectionName, ...] | None = None  # None = chosen from the profile (see `section_order`)
    hidden: frozenset[SectionName] = frozenset()
    group_skills: bool = True
    lang: str = "en"

    @field_validator("template")
    @classmethod
    def _template(cls, v: str) -> str:
        if v not in TEMPLATES:
            raise ValueError(f"Unknown template '{v}'. Choose one of: {', '.join(TEMPLATES)}")
        return v

    @field_validator("accent")
    @classmethod
    def _accent(cls, v: str) -> str:
        if not _HEX.fullmatch(v):
            raise ValueError("Accent colour must look like #1f4e79")
        return v.lower()

    @field_validator("lang")
    @classmethod
    def _lang(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", v):
            raise ValueError("Language must be a code such as 'en' or 'en-GB'")
        return v

    @field_validator("order")
    @classmethod
    def _order(cls, v: tuple[SectionName, ...] | None) -> tuple[SectionName, ...] | None:
        if v is not None and len(set(v)) != len(v):
            raise ValueError("A section can only appear once in the order")
        return v

    @model_validator(mode="after")
    def _accent_is_readable(self) -> RenderOptions:
        # Accent is used for headings and (in the sidebar template) as a background behind white text.
        if contrast_ratio(self.accent, "#ffffff") < 4.5:
            raise ValueError("Accent colour is too light to read on white; choose a darker one")
        return self

    @property
    def info(self) -> TemplateInfo:
        return TEMPLATES[self.template]

    @property
    def font_key(self) -> str:
        return self.font or {"executive": "serif"}.get(self.template, "sans")

    def section_order(self, profile: Profile) -> list[str]:
        """Sections to show, in order. Empty sections and hidden ones are dropped.

        Default order: people with work experience lead with it; students and career starters lead with education
        and projects (that is what recruiters look at first for them).
        """
        if self.order is not None:
            order = list(self.order) + [s for s in SECTIONS if s not in self.order]
        elif profile.experience:
            order = ["summary", "experience", "projects", "education", "skills", "certifications", "languages"]
        else:
            order = ["summary", "education", "projects", "skills", "certifications", "languages", "experience"]
        return [s for s in order if s not in self.hidden and has_content(profile, s)]


def has_content(profile: Profile, section: str) -> bool:
    return bool(getattr(profile, section))
