"""Skill taxonomy: canonical names, aliases and boundary-safe detection.

Replaces the two substring-based keyword lists from the old apps. Matching is token-based, so 'java' does
not match 'javascript', 'ios' does not match 'studios', and ambiguous names (R, Go, C, Excel...) only count
when they clearly appear as a skill (in a list, or as 'R programming' etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from careerforge.text import clean_text


@dataclass(frozen=True)
class Skill:
    name: str
    category: str
    aliases: tuple[str, ...] = ()
    weak: tuple[str, ...] = ()  # lowercase tokens that are also common words: only count in a skill list


def _s(name: str, category: str, *aliases: str, weak: tuple[str, ...] = ()) -> Skill:
    return Skill(name, category, aliases, weak)


L, FE, BE, DATA, CLOUD, DB, TOOLS, PRAC = (
    "Languages",
    "Frontend",
    "Backend",
    "Data & AI",
    "Cloud & DevOps",
    "Databases",
    "Tools",
    "Practices",
)

TAXONOMY: tuple[Skill, ...] = (
    # languages
    _s("Python", L),
    _s("Java", L),
    _s("JavaScript", L, "js", "ecmascript"),
    _s("TypeScript", L, "ts"),
    _s("Go", L, "golang", "go language", "go programming", weak=("go",)),
    _s("Rust", L),
    _s("Swift", L),
    _s("Kotlin", L),
    _s("C++", L, "cpp"),
    _s("C#", L, "csharp", "c sharp"),
    _s("C", L, weak=("c",)),
    _s(".NET", L, "dotnet", ".net core", "asp.net"),
    _s("Ruby", L),
    _s("PHP", L),
    _s("Scala", L),
    _s("R", L, "r programming", "r language", weak=("r",)),
    _s("MATLAB", L),
    _s("Dart", L),
    _s("SQL", L),
    _s("Bash", L, "shell scripting", "shell"),
    _s("HTML", L, "html5"),
    _s("CSS", L, "css3"),
    # frontend
    _s("React", FE, "react.js", "reactjs"),
    _s("Angular", FE, "angularjs"),
    _s("Vue.js", FE, "vue", "vuejs"),
    _s("Next.js", FE, "nextjs"),
    _s("Nuxt.js", FE, "nuxt"),
    _s("Svelte", FE),
    _s("Redux", FE),
    _s("Tailwind CSS", FE, "tailwind", "tailwindcss"),
    _s("Bootstrap", FE),
    _s("Sass", FE, "scss"),
    _s("Material UI", FE, "mui"),
    _s("Figma", TOOLS),
    _s("Three.js", FE, "threejs"),
    _s("WebGL", FE),
    _s("React Native", FE),
    _s("Flutter", FE),
    _s("Android", FE),
    _s("iOS", FE),
    # backend
    _s("Node.js", BE, "nodejs", "node js", "node", weak=("node",)),
    _s("Express.js", BE, "expressjs", "express", weak=("express",)),
    _s("Django", BE),
    _s("Flask", BE),
    _s("FastAPI", BE),
    _s("Spring Boot", BE, "springboot"),
    _s("Spring", BE, weak=("spring",)),
    _s("Laravel", BE),
    _s("Rails", BE, "ruby on rails"),
    _s("GraphQL", BE),
    _s("REST API", BE, "rest", "restful", "rest apis", "restful api", "restful apis"),
    _s("gRPC", BE),
    _s("WebSocket", BE, "websockets"),
    _s("Microservices", BE, "microservice"),
    _s("Celery", BE),
    _s("Kafka", BE, "apache kafka"),
    _s("RabbitMQ", BE),
    # data & ai
    _s("Pandas", DATA),
    _s("NumPy", DATA),
    _s("Matplotlib", DATA),
    _s("Seaborn", DATA),
    _s("Plotly", DATA),
    _s("Machine Learning", DATA, "ml"),
    _s("Deep Learning", DATA),
    _s("NLP", DATA, "natural language processing"),
    _s("Computer Vision", DATA),
    _s("LLM", DATA, "llms", "large language models"),
    _s("TensorFlow", DATA),
    _s("PyTorch", DATA),
    _s("scikit-learn", DATA, "sklearn", "scikit learn"),
    _s("Keras", DATA),
    _s("Hugging Face", DATA, "huggingface"),
    _s("LangChain", DATA),
    _s("OpenAI", DATA),
    _s("Generative AI", DATA, "genai", "gen ai"),
    _s("RAG", DATA, "retrieval augmented generation"),
    _s("OpenCV", DATA),
    _s("Power BI", DATA, "powerbi"),
    _s("Tableau", DATA),
    _s("Excel", DATA, "microsoft excel", "ms excel", weak=("excel",)),
    _s("Statistics", DATA),
    _s("A/B Testing", DATA, "ab testing", "a/b tests"),
    _s("Spark", DATA, "apache spark", "pyspark"),
    _s("Airflow", DATA, "apache airflow"),
    _s("dbt", DATA),
    # databases
    _s("PostgreSQL", DB, "postgres"),
    _s("MySQL", DB),
    _s("SQLite", DB),
    _s("MongoDB", DB, "mongo"),
    _s("Redis", DB),
    _s("Elasticsearch", DB, "elastic search"),
    _s("Cassandra", DB),
    _s("DynamoDB", DB),
    _s("Snowflake", DB),
    _s("BigQuery", DB),
    _s("Firebase", DB),
    _s("Supabase", DB),
    _s("Oracle", DB, weak=("oracle",)),
    # cloud & devops
    _s("AWS", CLOUD, "amazon web services"),
    _s("Azure", CLOUD, "microsoft azure"),
    _s("GCP", CLOUD, "google cloud", "google cloud platform"),
    _s("EC2", CLOUD),
    _s("S3", CLOUD, "amazon s3"),
    _s("Lambda", CLOUD, "aws lambda", weak=("lambda",)),
    _s("Docker", CLOUD),
    _s("Kubernetes", CLOUD, "k8s"),
    _s("Terraform", CLOUD),
    _s("Ansible", CLOUD),
    _s("Helm", CLOUD, weak=("helm",)),
    _s("CI/CD", CLOUD, "ci cd", "cicd", "continuous integration", "continuous delivery"),
    _s("Jenkins", CLOUD),
    _s("GitHub Actions", CLOUD),
    _s("GitLab CI", CLOUD, "gitlab ci/cd"),
    _s("Linux", CLOUD),
    _s("Nginx", CLOUD),
    _s("Prometheus", CLOUD),
    _s("Grafana", CLOUD),
    # tools & practices
    _s("Git", TOOLS),
    _s("GitHub", TOOLS),
    _s("GitLab", TOOLS),
    _s("Jira", TOOLS),
    _s("Confluence", TOOLS),
    _s("Postman", TOOLS),
    _s("Agile", PRAC),
    _s("Scrum", PRAC),
    _s("Kanban", PRAC),
    _s("Unit Testing", PRAC, "unit tests"),
    _s("TDD", PRAC, "test driven development"),
    _s("System Design", PRAC),
    _s("UI/UX", PRAC, "ui ux", "ux design"),
)

_BY_KEY: dict[str, Skill] = {}
for _skill in TAXONOMY:
    for _alias in (_skill.name, *_skill.aliases):
        _BY_KEY[clean_text(_alias).lower()] = _skill

# Knowing the key skill reasonably implies the base one (a Flask developer knows Python). One direction only:
# a posting asking for Flask is NOT satisfied by "Python".
IMPLIES: dict[str, tuple[str, ...]] = {
    **dict.fromkeys(("PostgreSQL", "MySQL", "SQLite", "Snowflake", "BigQuery"), ("SQL",)),
    **dict.fromkeys(("Pandas", "NumPy", "Django", "Flask", "FastAPI", "Celery", "Matplotlib", "Seaborn"), ("Python",)),
    **dict.fromkeys(("scikit-learn", "PyTorch", "TensorFlow", "Keras"), ("Python", "Machine Learning")),
    **dict.fromkeys(("React", "Angular", "Vue.js", "Svelte", "Node.js", "TypeScript"), ("JavaScript",)),
    "Next.js": ("React", "JavaScript"),
    "Redux": ("React", "JavaScript"),
    "Express.js": ("Node.js", "JavaScript"),
    "Spring Boot": ("Java",),
    "Rails": ("Ruby",),
    "Laravel": ("PHP",),
    **dict.fromkeys(("Tailwind CSS", "Sass", "Bootstrap"), ("CSS",)),
    "GitHub Actions": ("CI/CD", "Git"),
    "GitLab CI": ("CI/CD", "Git"),
    "Jenkins": ("CI/CD",),
    **dict.fromkeys(("GitHub", "GitLab"), ("Git",)),
    "Deep Learning": ("Machine Learning",),
    "LLM": ("NLP",),
}


def implied_by(skill: str, have: set[str]) -> str | None:
    """A skill in `have` that implies `skill`, or None."""
    return next((h for h in sorted(have) if skill in IMPLIES.get(h, ())), None)


KNOWN_NAMES = frozenset(s.name for s in TAXONOMY)
CATEGORY_ORDER = (L, FE, BE, DATA, DB, CLOUD, TOOLS, PRAC)


def lookup(name: str) -> Skill | None:
    return _BY_KEY.get(clean_text(name).lower())


def canonicalize(name: str) -> str:
    """Canonical display name for a known skill (case/alias-insensitive); otherwise the cleaned input."""
    text = clean_text(name)
    skill = lookup(text)
    return skill.name if skill else text


def category_of(name: str) -> str:
    skill = lookup(name)
    return skill.category if skill else "Other"


def dedupe(names: list[str]) -> list[str]:
    """Canonicalise, drop empties/duplicates (case-insensitive), keep first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in names:
        name = canonicalize(raw)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


# ── detection in free text ──────────────────────────────────────────────────

_LIST_DELIMS = r"(?:^|[,;|•·▪\n/:()])\s*"
_LIST_END = r"\s*(?:$|[,;|•·▪\n/()])"


def _token(alias: str) -> str:
    # aliases may contain + # . / - ; forbid being glued to other word characters on either side
    return rf"(?<![\w+#.]){re.escape(alias)}(?![\w+#]|\.\w)"


_EXPLICIT = r"[,;|•·▪/:(]"  # a real list delimiter (start/end of line does not count for the and/or forms)
_JOIN = r"(?:and|or|&)"


def _build_patterns() -> list[tuple[Skill, re.Pattern[str] | None, re.Pattern[str] | None]]:
    out = []
    for skill in TAXONOMY:
        every = {skill.name.lower(), *(a.lower() for a in skill.aliases)}
        strong = sorted(every - set(skill.weak), key=len, reverse=True)
        strong_re = re.compile("|".join(_token(n) for n in strong), re.I) if strong else None
        weak_re = None
        if skill.weak:
            alt = "|".join(re.escape(w) for w in skill.weak)
            # (A) delimited on both sides, any case:       "Python, go, R"
            both = _LIST_DELIMS + "(?:" + alt + ")" + _LIST_END
            # (B)/(C) joined by and/or on one side, an explicit delimiter on the other, EXACT canonical casing:
            #         "SQL, Excel and stakeholders"   "Tableau, Python and Excel,"
            names = "|".join(re.escape(n) for n in {skill.name, *(w.title() for w in skill.weak)})
            left = rf"{_EXPLICIT}\s*(?:{names})\s+{_JOIN}\s"
            right = rf"\s{_JOIN}\s+(?:{names})\s*(?:{_EXPLICIT[:-1]}\)]|$)"
            weak_re = re.compile(f"(?i:{both})|{left}|{right}", re.M)
        out.append((skill, strong_re, weak_re))
    return out


_PATTERNS = _build_patterns()


def _push(tops: list[tuple[int, str]], end: int, name: str) -> None:
    """Keep the two largest ends belonging to two different skills."""
    for k, (e, n) in enumerate(tops):
        if n == name:
            tops[k] = (max(e, end), name)
            break
    else:
        tops.append((end, name))
    tops.sort(reverse=True)
    del tops[2:]


def _best(tops: list[tuple[int, str]], exclude: str) -> int:
    return next((end for end, name in tops if name != exclude), -1)


def _standalone(spans: dict[str, list[tuple[int, int]]]) -> set[str]:
    """Skills with at least one mention that is not inside a LONGER mention of a different skill.

    A sweep over the mentions in start order, so the cost is O(n log n) in the number of mentions. (The obvious
    pairwise comparison was quadratic: a 100 KB document took seconds, a 1 MB one minutes.)
    """
    flat = sorted((a, -b, name) for name, found in spans.items() for a, b in found)
    standalone: set[str] = set()
    earlier: list[tuple[int, str]] = []  # best ends among mentions that start before the current position
    i = 0
    while i < len(flat):
        j = i
        while j < len(flat) and flat[j][0] == flat[i][0]:
            j += 1
        same_start: list[tuple[int, str]] = []  # same start, longer mentions first
        for _, neg_end, name in flat[i:j]:
            end = -neg_end
            if _best(earlier, name) >= end or _best(same_start, name) > end:
                _push(same_start, end, name)
                continue
            standalone.add(name)
            _push(same_start, end, name)
        for end, name in same_start:
            _push(earlier, end, name)
        i = j
    return standalone


def find_skills(text: str) -> list[str]:
    """Skills mentioned in `text`, canonical names, in taxonomy order. Precision over recall.

    A skill whose every mention lies inside a longer skill's mention is dropped ("GitHub" inside "GitHub Actions",
    "Spring" inside "Spring Boot"), so one phrase is never counted twice.
    """
    body = clean_text(text, multiline=True)
    if not body:
        return []
    spans: dict[str, list[tuple[int, int]]] = {}
    for skill, strong, weak in _PATTERNS:
        found = [m.span() for pat in (strong, weak) if pat for m in pat.finditer(body)]
        if found:
            spans[skill.name] = found
    keep = _standalone(spans)
    return [skill.name for skill, _, _ in _PATTERNS if skill.name in keep]
