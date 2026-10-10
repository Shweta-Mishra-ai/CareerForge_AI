"""The Profile model: single source of truth for a candidate's CV/portfolio content.

Design rules
* Draft-friendly: every field is optional so a half-filled profile can be edited. Whether it is good enough to
  *submit* is decided by `careerforge.readiness`, not by validation.
* Safe by construction: text is normalised, over-long values are rejected (never silently truncated), links are
  http(s)-only. Nothing is HTML-escaped here - renderers escape at output time.
* Honest provenance: items carry `origin` and `confirmed`. AI-suggested items are unconfirmed until the user
  accepts them, and `Profile.exportable()` drops unconfirmed items so they can never reach a submitted CV.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from careerforge import skills as skill_taxonomy
from careerforge.text import (
    clean_bullet,
    clean_text,
    date_key,
    display_date,
    normalize_email,
    normalize_partial_date,
    normalize_phone,
    normalize_url,
)

SCHEMA_VERSION = 1
FILE_KIND = "careerforge.profile"
MAX_FILE_BYTES = 2_000_000

Origin = Literal["user", "extracted", "suggested"]


class ProfileError(ValueError):
    """A profile file/dict could not be loaded. The message is safe to show to the user."""


# ── field types ─────────────────────────────────────────────────────────────


def _cap(limit: int) -> Callable[[str], str]:
    def check(value: str) -> str:
        if len(value) > limit:
            raise ValueError(f"Too long ({len(value)} characters; limit is {limit})")
        return value

    return check


def line(limit: int) -> Any:
    return Annotated[str, BeforeValidator(clean_text), AfterValidator(_cap(limit))]


def paragraph(limit: int) -> Any:
    return Annotated[str, BeforeValidator(lambda v: clean_text(v, multiline=True)), AfterValidator(_cap(limit))]


Bullet = Annotated[str, BeforeValidator(clean_bullet), AfterValidator(_cap(600))]
Email = Annotated[str, BeforeValidator(normalize_email)]
Phone = Annotated[str, BeforeValidator(normalize_phone)]
Link = Annotated[str, BeforeValidator(normalize_url)]
LinkedInLink = Annotated[str, BeforeValidator(lambda v: normalize_url(v, ("linkedin.com",)))]
GitHubLink = Annotated[str, BeforeValidator(lambda v: normalize_url(v, ("github.com",)))]
PartialDate = Annotated[str, BeforeValidator(normalize_partial_date)]


def _drop_empty(items: list[str]) -> list[str]:
    return [i for i in items if i]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ── building blocks ─────────────────────────────────────────────────────────


class DateRange(_Model):
    start: PartialDate = ""
    end: PartialDate = ""
    current: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> DateRange:
        if self.current and self.end:
            raise ValueError("A role marked current cannot also have an end date")
        if self.start and self.end and date_key(self.end, end=True) < date_key(self.start):
            raise ValueError("End date is before start date")
        return self

    def is_empty(self) -> bool:
        return not (self.start or self.end or self.current)

    def display(self) -> str:
        if self.current:
            return f"{display_date(self.start)} – Present" if self.start else "Present"
        if self.start and self.end and self.start != self.end:
            return f"{display_date(self.start)} – {display_date(self.end)}"
        return display_date(self.start or self.end)


class _Item(_Model):
    """Common provenance for list items. `confirmed` defaults to False only for AI suggestions."""

    origin: Origin = "extracted"
    confirmed: bool | None = None

    @model_validator(mode="after")
    def _default_confirmed(self) -> _Item:
        if self.confirmed is None:
            object.__setattr__(self, "confirmed", self.origin != "suggested")
        return self


class Experience(_Item):
    title: line(150) = ""
    company: line(150) = ""
    location: line(100) = ""
    dates: DateRange = Field(default_factory=DateRange)
    bullets: list[Bullet] = Field(default_factory=list, max_length=25)

    _clean_bullets = field_validator("bullets")(_drop_empty)


class Education(_Item):
    degree: line(200) = ""
    institution: line(200) = ""
    location: line(100) = ""
    dates: DateRange = Field(default_factory=DateRange)
    grade: line(60) = ""
    details: list[Bullet] = Field(default_factory=list, max_length=15)

    _clean_details = field_validator("details")(_drop_empty)


class Project(_Item):
    name: line(150) = ""
    description: paragraph(600) = ""
    bullets: list[Bullet] = Field(default_factory=list, max_length=15)
    tech: list[line(60)] = Field(default_factory=list, max_length=30)
    url: Link = ""
    demo_url: Link = ""  # a live demo or deployed site
    featured: bool = False  # shown as a larger case-study card on the portfolio; only the user sets this
    stars: int = Field(default=0, ge=0)

    _clean_bullets = field_validator("bullets")(_drop_empty)

    @field_validator("tech")
    @classmethod
    def _tech(cls, v: list[str]) -> list[str]:
        return skill_taxonomy.dedupe(v)


class Certification(_Item):
    name: line(200) = ""
    issuer: line(150) = ""
    date: PartialDate = ""
    url: Link = ""


class Contact(_Model):
    email: Email = ""
    phone: Phone = ""
    location: line(100) = ""
    linkedin: LinkedInLink = ""
    github: GitHubLink = ""
    website: Link = ""


# ── the profile ─────────────────────────────────────────────────────────────


class Profile(_Model):
    name: line(120) = ""
    headline: line(200) = ""
    summary: paragraph(1500) = ""
    contact: Contact = Field(default_factory=Contact)
    skills: list[line(60)] = Field(default_factory=list, max_length=80)
    languages: list[line(60)] = Field(default_factory=list, max_length=20)
    experience: list[Experience] = Field(default_factory=list, max_length=30)
    education: list[Education] = Field(default_factory=list, max_length=10)
    projects: list[Project] = Field(default_factory=list, max_length=30)
    certifications: list[Certification] = Field(default_factory=list, max_length=30)

    @field_validator("skills")
    @classmethod
    def _skills(cls, v: list[str]) -> list[str]:
        return skill_taxonomy.dedupe(v)

    @field_validator("languages")
    @classmethod
    def _languages(cls, v: list[str]) -> list[str]:
        return _dedupe_plain(v)

    # -- provenance --------------------------------------------------------

    def pending_items(self) -> list[tuple[str, int, str]]:
        """Unconfirmed AI suggestions as (section, index, label), for the review UI."""
        out: list[tuple[str, int, str]] = []
        sections = (
            ("experience", lambda x: x.title or x.company),
            ("education", lambda x: x.degree or x.institution),
            ("projects", lambda x: x.name),
            ("certifications", lambda x: x.name),
        )
        for section, label in sections:
            for i, item in enumerate(getattr(self, section)):
                if not item.confirmed:
                    out.append((section, i, label(item) or f"(untitled {section[:-1]})"))
        return out

    def exportable(self) -> Profile:
        """Copy with every unconfirmed (AI-suggested) item removed. Exporters must use this, never `self`."""
        keep = {
            s: [i for i in getattr(self, s) if i.confirmed]
            for s in ("experience", "education", "projects", "certifications")
        }
        return self.model_copy(update=keep, deep=True)

    # -- identity / persistence -------------------------------------------

    def content_hash(self) -> str:
        """Stable hash of the content. Use as a cache key (the old apps keyed caches on the filename)."""
        canon = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def to_json(self, *, indent: int | None = 2) -> str:
        envelope = {"kind": FILE_KIND, "schema_version": SCHEMA_VERSION, "profile": self.model_dump(mode="json")}
        return json.dumps(envelope, indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str | bytes) -> Profile:
        """Load a profile file. Raises ProfileError with a user-presentable message on any problem."""
        raw = data.encode("utf-8") if isinstance(data, str) else data
        if len(raw) > MAX_FILE_BYTES:
            raise ProfileError(f"Profile file is too large (limit {MAX_FILE_BYTES // 1_000_000} MB)")
        try:
            envelope = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProfileError("That file is not valid JSON") from exc
        if not isinstance(envelope, dict) or envelope.get("kind") != FILE_KIND:
            raise ProfileError("That is not a CareerForge profile file")
        version = envelope.get("schema_version")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ProfileError("Profile file has no valid schema_version")
        if version > SCHEMA_VERSION:
            raise ProfileError(f"Profile file is from a newer version (v{version}); please update the app")
        body = envelope.get("profile")
        if not isinstance(body, dict):
            raise ProfileError("Profile file has no profile section")
        return cls.from_dict(_migrate(body, version))

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> Profile:
        try:
            return cls.model_validate(body)
        except ValidationError as exc:
            raise ProfileError(_describe(exc)) from exc


def _dedupe_plain(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for v in values:
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _migrate(body: dict[str, Any], version: int) -> dict[str, Any]:
    """Upgrade an older `profile` dict to the current schema. v1 is current, so this is the extension point."""
    return body


def _describe(exc: ValidationError, limit: int = 5) -> str:
    """Turn pydantic errors into short, path-qualified messages: 'contact.email: Not a valid email address'."""
    lines = []
    for err in exc.errors()[:limit]:
        path = ".".join(str(p) for p in err["loc"]) or "profile"
        msg = err["msg"].removeprefix("Value error, ")
        lines.append(f"{path}: {msg}")
    more = len(exc.errors()) - limit
    return "; ".join(lines) + (f" (+{more} more)" if more > 0 else "")
