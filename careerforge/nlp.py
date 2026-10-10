"""Small, dependency-free text helpers shared by grounding and ATS matching."""

from __future__ import annotations

import re
import unicodedata

STOP = frozenset(
    """a an and are as at be been by for from has have in into is it its of on or that the their this to was were
    with using used use via per over under across within while about also more most than then which who whom will
    our your you they them his her him she he we i my me""".split()
)


def normalize(text: str) -> str:
    """Lower-case, accent-folded, alphanumeric-only text; words hyphenated across line breaks are re-joined."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    return re.sub(r"[^0-9a-z]+", " ", text).strip()


def stem(token: str) -> str:
    """Very light suffix stripping ('managed' -> 'manag', 'dashboards' -> 'dashboard'). Good enough for matching."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > 4 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def content_tokens(text: str, *, min_len: int = 3) -> list[str]:
    return [t for t in normalize(text).split() if len(t) >= min_len and t not in STOP and not t.isdigit()]
