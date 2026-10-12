"""Skills roadmap for the gaps an ATS report found. Deterministic: no AI, and deliberately no web links.

Links invented by models go stale or are wrong, so the roadmap gives search terms and concrete practice projects
instead. Effort figures are rough planning estimates by skill category, labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass

from careerforge import skills as taxonomy
from careerforge.ats.report import AtsReport
from careerforge.models import Profile

# (min weeks, max weeks) of part-time study to reach "can use it in a small project"; rough planning estimates
EFFORT = {
    "Languages": (6, 12), "Frontend": (3, 8), "Backend": (3, 8), "Data & AI": (6, 14),
    "Databases": (2, 5), "Cloud & DevOps": (3, 8), "Tools": (1, 2), "Practices": (1, 3), "Other": (2, 6),
}  # fmt: skip
PROJECT_IDEAS = {
    "Languages": "Re-implement a small tool you already built in {skill} (a CLI, a parser, or a REST client).",
    "Frontend": "Build a small responsive app with {skill}: a list, a form, and one page that fetches data.",
    "Backend": "Build a small API with {skill}: three endpoints, input validation, tests, and a README.",
    "Data & AI": "Take a public dataset, answer three questions with {skill}, and write up the findings.",
    "Databases": "Model a small schema in {skill}, load sample data, and write five useful queries.",
    "Cloud & DevOps": "Deploy a small app using {skill}, then automate the deployment and document the steps.",
    "Tools": "Use {skill} on a real repository or project for a week and note what it improves.",
    "Practices": "Apply {skill} to one existing project and describe the before and after.",
    "Other": "Build one small project that uses {skill} end to end and publish it.",
}


@dataclass(frozen=True)
class RoadmapItem:
    skill: str
    priority: str  # "required" | "unspecified" | "preferred"
    category: str
    weeks: tuple[int, int]
    builds_on: str  # a skill you already have that makes this faster, or ""
    steps: tuple[str, ...]
    project: str


def build_roadmap(report: AtsReport, profile: Profile, *, limit: int = 8) -> list[RoadmapItem]:
    have = {taxonomy.canonicalize(s) for s in profile.exportable().skills}
    items: list[RoadmapItem] = []
    for req in sorted((r for r in report.missing if r.kind == "skill"), key=lambda r: -r.weight)[:limit]:
        category = taxonomy.category_of(req.term)
        low, high = EFFORT.get(category, EFFORT["Other"])
        base = next((h for h in sorted(have) if req.term in taxonomy.IMPLIES and h in taxonomy.IMPLIES[req.term]), "")
        same_area = next((h for h in sorted(have) if taxonomy.category_of(h) == category), "")
        builds_on = base or same_area
        if builds_on:
            low, high = max(1, low // 2), max(2, high * 2 // 3)
        steps = (
            f'Read the official {req.term} documentation (search: "{req.term} official documentation").',
            f"Follow one beginner tutorial for {req.term} and rebuild it without copying.",
            "Do the practice project below and keep the code in a public repository.",
            f"Only after you have really used {req.term}, add it to your Skills and describe the project in a bullet.",
        )
        items.append(
            RoadmapItem(
                req.term,
                req.importance,
                category,
                (low, high),
                builds_on,
                steps,
                PROJECT_IDEAS.get(category, PROJECT_IDEAS["Other"]).format(skill=req.term),
            )
        )
    return items


def roadmap_markdown(items: list[RoadmapItem]) -> str:
    """The roadmap as a Markdown checklist the user can keep (plain text, nothing but the roadmap's own fields)."""
    lines = ["# Learning roadmap", ""]
    for item in items:
        low, high = item.weeks
        lines += [f"## {item.skill} ({item.priority}): about {low}-{high} weeks", ""]
        if item.builds_on:
            lines += [f"Builds on what you already know: {item.builds_on}", ""]
        lines += [f"{n}. {step}" for n, step in enumerate(item.steps, 1)]
        lines += ["", f"**Project idea:** {item.project}", ""]
    lines += [
        "Estimates are rough and assume part-time study. Only add a skill to your CV once you have really used it.",
        "",
    ]
    return "\n".join(lines)
