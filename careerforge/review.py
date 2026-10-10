"""Review-step operations on a Profile: accept or discard AI-suggested items. Pure functions, UI-agnostic."""

from __future__ import annotations

from careerforge.models import Profile

SECTIONS = ("experience", "education", "projects", "certifications")


def _check(profile: Profile, section: str, index: int) -> list:
    if section not in SECTIONS:
        raise ValueError(f"Unknown section: {section!r}")
    items = getattr(profile, section)
    if not 0 <= index < len(items):
        raise ValueError(f"No {section} item at position {index}")
    return items


def confirm(profile: Profile, section: str, index: int) -> Profile:
    """Mark one suggested item as accepted by the user (it then appears in exports). Provenance is kept."""
    _check(profile, section, index)
    data = profile.model_dump()
    data[section][index]["confirmed"] = True
    return Profile.model_validate(data)


def discard(profile: Profile, section: str, index: int) -> Profile:
    """Remove one item entirely."""
    _check(profile, section, index)
    data = profile.model_dump()
    del data[section][index]
    return Profile.model_validate(data)


def confirm_all(profile: Profile) -> Profile:
    data = profile.model_dump()
    for section in SECTIONS:
        for item in data[section]:
            item["confirmed"] = True
    return Profile.model_validate(data)
