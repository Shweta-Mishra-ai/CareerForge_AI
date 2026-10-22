"""Small decorative graphics for the portfolio: project cover art and company monograms.

Everything is generated from the text itself (a hash picks the shapes), so the same project always gets the same
picture, nothing is fetched, and no file is shipped. The SVG carries no text and no colour of its own: it is painted
with the page's CSS variables through the classes `.a`, `.b` and `.t`, so it follows the theme, including the
automatic light/dark one.
"""

from __future__ import annotations

import hashlib
import re

from markupsafe import Markup

_AB = "ab"  # which of the two theme colours a shape uses
W, H = 320, 100  # the viewBox; the image is scaled to fill its box and cropped, never stretched
_COMPANY_SUFFIX = {"pvt", "ltd", "limited", "inc", "llc", "llp", "corp", "corporation", "co", "gmbh", "plc", "ag", "sa"}


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.casefold().encode("utf-8")).digest()


def _circles(d: bytes) -> str:
    out = [f'<rect width="{W}" height="{H}" class="t"/>']
    for i in range(4):
        cx, cy, r = d[i] % W, 10 + d[i + 4] % 80, 24 + d[i + 8] % 46
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" class="{_AB[i % 2]}" opacity="0.{2 + d[i + 12] % 3}"/>')
    return "".join(out)


def _bars(d: bytes) -> str:
    out = [f'<rect width="{W}" height="{H}" class="t"/>']
    x = -30 + d[0] % 20
    for i in range(7):
        w = 12 + d[i + 1] % 34
        out.append(
            f'<rect x="{x}" y="-40" width="{w}" height="190" class="{_AB[i % 2]}" opacity="0.{1 + d[i + 9] % 4}" '
            'transform="rotate(24 160 50)"/>'
        )
        x += w + 8 + d[i + 17] % 24
    return "".join(out)


def _dots(d: bytes) -> str:
    out = [f'<rect width="{W}" height="{H}" class="t"/>']
    focus = 60 + d[0] % 200
    for row in range(5):
        for col in range(16):
            x, y = 12 + col * 20, 10 + row * 20
            size = max(1.2, 7 - abs(x - focus) / 22 + (d[(row * 16 + col) % 32] % 3) * 0.4)
            out.append(f'<circle cx="{x}" cy="{y}" r="{size:.1f}" class="{_AB[(row + col) % 2]}" opacity="0.55"/>')
    return "".join(out)


def _arcs(d: bytes) -> str:
    out = [f'<rect width="{W}" height="{H}" class="t"/>']
    cx, cy = (d[0] % 2) * W, d[1] % 100
    for i in range(6):
        out.append(
            f'<circle cx="{cx}" cy="{cy}" r="{20 + i * 22}" fill="none" class="{_AB[i % 2]}s" '
            f'stroke-width="{4 + d[i + 2] % 8}" opacity="0.{2 + d[i + 8] % 3}"/>'
        )
    return "".join(out)


_PATTERNS = (_circles, _bars, _dots, _arcs)


def cover_svg(name: str) -> Markup:
    """Decorative cover picture for a project, chosen and shaped by its name."""
    d = _digest(name or "project")
    body = _PATTERNS[d[31] % len(_PATTERNS)](d)
    return Markup(  # noqa: S704 - built only from integers and fixed strings
        f'<svg class="art" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice" aria-hidden="true" '
        f'focusable="false">{body}</svg>'
    )


def monogram(company: str) -> str:
    """One or two capital letters for a company badge: "Finlytics Pvt Ltd" gives F, "ShipFast Logistics" gives SL."""
    words = [w for w in re.split(r"[\s,.&/-]+", company) if any(c.isalpha() for c in w)]
    words = [w for w in words if w.casefold() not in _COMPANY_SUFFIX] or words
    letters = [next(c for c in w if c.isalpha()).upper() for w in words[:2]]
    return "".join(letters) or "•"
