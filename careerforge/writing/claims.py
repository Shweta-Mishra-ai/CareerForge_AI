"""Find claims in AI-written text that the CV (or, for names, the posting) does not support. Deterministic.

Used for prose where first person and motivation are natural (cover letters), so the checks target FACTS:
numbers, names/products, skills, and fill-in-the-blank leftovers.
"""

from __future__ import annotations

import re

from careerforge import skills as taxonomy
from careerforge.tailor.verify import _PLACEHOLDER, _new_names, _numbers


def unsupported_claims(
    text: str, *, profile_text: str, years: int, posting_text: str = "", extra_known: str = ""
) -> list[str]:
    """Human-readable issues; empty list means every checkable claim traces to the CV/posting."""
    issues: list[str] = []
    if _PLACEHOLDER.search(text):
        issues.append("contains placeholder or markup text that must be replaced")
    # extra_known is text the user typed into the form themselves (a hook, a start date): its numbers are theirs too
    allowed = _numbers(profile_text) | _numbers(extra_known) | {str(y) for y in (years - 1, years, years + 1) if y > 0}
    if extra := sorted(_numbers(text) - allowed):
        issues.append(f"mentions number(s) not in your CV: {', '.join(extra)}")
    known = f"{profile_text}\n{posting_text}\n{extra_known}"
    if names := _new_names(text, known):
        issues.append(f"mentions name(s) found in neither your CV nor the posting: {', '.join(dict.fromkeys(names))}")
    have = set(taxonomy.find_skills(profile_text))
    if bad := [s for s in taxonomy.find_skills(text) if s not in have and not taxonomy.implied_by(s, have)]:
        issues.append(f"claims skill(s) your CV does not show: {', '.join(bad)}")
    if m := re.search(r"(?i)\b(?:expert|master|guru|world[- ]class|best[- ]in[- ]class)\b", text):
        issues.append(f"uses an unsupported superlative: '{m.group(0)}'")
    return issues
