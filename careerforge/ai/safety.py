"""Handling untrusted document text before it reaches a model.

CV/JD/scraped text is attacker-controllable. Defence in depth: (1) strip instruction-like lines and tag
look-alikes here, (2) fence the text and tell the model it is data, (3) validate output against a schema,
(4) check the output is grounded in the (sanitised) source - see grounding.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from careerforge.text import clean_text

_INJECTION = re.compile(
    r"""(
        ignore\s+(?:all\s+|any\s+|the\s+)*(?:previous|prior|above|earlier|preceding)\s+(?:instruction|prompt|rule|direction)s?
      | disregard\s+(?:all\s+|any\s+|the\s+)*(?:previous|prior|above|earlier)
      | forget\s+(?:all\s+|everything\s+)(?:previous|prior|above|you)
      | (?:reveal|print|show|repeat|leak)\s+(?:your\s+|the\s+)?(?:system\s+)?(?:prompt|instructions)
      | \bsystem\s+prompt\b
      | \bnew\s+instructions?\s*:
      | you\s+are\s+(?:now\s+)?(?:chatgpt|an?\s+ai\b|a\s+language\s+model|in\s+developer\s+mode|dan\b)
      | <\s*/?\s*(?:system|assistant|user|source|instructions?|document)\b[^>]*>
      | \[\s*/?\s*(?:inst|system)\s*\]
    )""",
    re.I | re.X,
)


@dataclass(frozen=True)
class SanitizedSource:
    text: str
    removed: tuple[str, ...]  # whole lines dropped because they look like instructions to an AI
    clipped: bool = False

    @property
    def suspicious(self) -> bool:
        return bool(self.removed)


def sanitize_source(raw: str | None, max_chars: int | None = None) -> SanitizedSource:
    """Clean control characters, drop instruction-like lines, optionally clip at a line boundary."""
    text = clean_text(raw, multiline=True)
    kept: list[str] = []
    removed: list[str] = []
    for line in text.split("\n"):
        if _INJECTION.search(line):
            removed.append(line.strip()[:200])
        else:
            kept.append(line)
    text = "\n".join(kept).strip()
    clipped = False
    if max_chars and len(text) > max_chars:
        cut = text.rfind("\n", 0, max_chars)
        text = text[: cut if cut > max_chars * 0.5 else max_chars].rstrip()
        clipped = True
    return SanitizedSource(text, tuple(removed), clipped)


def fence(label: str, text: str) -> str:
    """Wrap untrusted text in <label>...</label>. Sanitised text cannot contain a closing tag."""
    return f"<{label}>\n{text}\n</{label}>"
