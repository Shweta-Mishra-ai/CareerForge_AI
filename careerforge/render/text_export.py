"""Plain-text CV: what you paste into an online application form, or send when a portal wants .txt."""

from __future__ import annotations

from careerforge.models import Profile
from careerforge.readiness import require_ready
from careerforge.render.options import RenderOptions
from careerforge.render.view import build_blocks, contact_items


def render_cv_txt(profile: Profile, options: RenderOptions | None = None) -> str:
    options = options or RenderOptions()
    p = require_ready(profile)
    lines = [p.name.upper()]
    if p.headline:
        lines.append(p.headline)
    contact = " | ".join(c.text for c in contact_items(p.contact))
    if contact:
        lines.append(contact)
    for block in build_blocks(p, options):
        lines += ["", block.title.upper(), "-" * len(block.title)]
        if block.paragraph:
            lines.append(block.paragraph)
        for label, names in block.skills:
            lines.append(f"{label}: {names}" if label else names)
        for i, e in enumerate(block.entries):
            if i:
                lines.append("")
            lines.append(f"{e.head}  ({e.when})" if e.when else e.head)
            if e.sub:
                lines.append(e.sub)
            if e.text:
                lines.append(e.text)
            lines += [f"- {b}" for b in e.bullets]
    return "\n".join(lines) + "\n"
