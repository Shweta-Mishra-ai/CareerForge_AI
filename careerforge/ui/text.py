"""Text helpers for safe display."""

from __future__ import annotations

_MD_SPECIAL = "\\`*_{}[]()<>#+-.!|~$&:"


def md_escape(text: object) -> str:
    """Make user-derived text display literally in st.markdown (no formatting, links, HTML, emoji codes or LaTeX)."""
    return "".join("\\" + c if c in _MD_SPECIAL else c for c in str(text))
