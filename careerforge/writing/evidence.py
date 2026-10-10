"""Pair what the posting asks for with what the candidate has actually done.

This is the technique behind every strong cover letter: pick the requirements the posting stresses and answer each with
one real, measurable example. Pairs come from the ATS matcher (so they are the requirements the CV really meets) and use
the candidate's own bullets verbatim; nothing is generated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from careerforge.ats.match import Match, starts_with_action_verb
from careerforge.models import Profile

_IMPORTANCE = {"required": 3, "unspecified": 2, "preferred": 1}


@dataclass(frozen=True)
class Evidence:
    requirement: str
    bullet: str  # the candidate's own words
    employer: str  # where it happened ("" if the bullet is from a project)
    project: str = ""  # the project's name when the bullet is from a project

    def as_sentence(self) -> str:
        """'At Finlytics, I cut p95 latency by 40%.' (bullets begin with a past-tense verb)."""
        text = self.bullet.rstrip(".")
        if self.employer:
            lead = f"At {self.employer}, "
        else:
            lead = f"In my {self.project} project, " if self.project else "In a project, "
        if starts_with_action_verb(self.bullet):
            return f"{lead}I {text[0].lower()}{text[1:]}."
        return f"{lead}{text[0].lower()}{text[1:]}."


def _score(bullet: str) -> float:
    return (
        2.0 * bool(re.search(r"\d", bullet)) + 1.0 * starts_with_action_verb(bullet) + (0.5 if len(bullet) < 200 else 0)
    )


def evidence_pairs(profile: Profile, matches: tuple[Match, ...], *, limit: int = 3) -> list[Evidence]:
    """Up to `limit` (requirement, own bullet) pairs, most important requirements first, each bullet used once."""
    p = profile.exportable()
    # (bullet, employer, project name, text a requirement may be found in: the bullet, plus a project's own tech list)
    sources = [(b, e.company or e.title, "", b) for e in p.experience for b in e.bullets]
    sources += [(b, "", pr.name, f"{b} {' '.join(pr.tech)}") for pr in p.projects for b in pr.bullets]
    ranked = sorted(matches, key=lambda m: (-_IMPORTANCE.get(m.requirement.importance, 1), -m.quality))
    used: set[str] = set()
    out: list[Evidence] = []
    for m in ranked:
        term = m.requirement.term
        # a bare skills-list mention yields no candidate: the term must appear in a bullet or a project's tech list
        candidates = [src for src in sources if src[0] not in used and term.lower() in src[3].lower()]
        if not candidates:
            continue
        bullet, employer, project, _ = max(candidates, key=lambda src: _score(src[0]))
        used.add(bullet)
        out.append(Evidence(term, bullet, employer, project))
        if len(out) == limit:
            break
    return out
