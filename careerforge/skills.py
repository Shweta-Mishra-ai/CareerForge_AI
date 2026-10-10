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


def _build_patterns() -> list[tuple[Skill, re.Pattern[str] | None, re.Pattern[str] | None]]:
    out = []
    for skill in TAXONOMY:
        every = {skill.name.lower(), *(a.lower() for a in skill.aliases)}
        strong = sorted(every - set(skill.weak), key=len, reverse=True)
        strong_re = re.compile("|".join(_token(n) for n in strong), re.I) if strong else None
        weak_re = None
        if skill.weak:
            alt = "|".join(re.escape(w) for w in skill.weak)
            weak_re = re.compile(_LIST_DELIMS + "(?:" + alt + ")" + _LIST_END, re.I | re.M)
        out.append((skill, strong_re, weak_re))
    return out


_PATTERNS = _build_patterns()


def find_skills(text: str) -> list[str]:
    """Skills mentioned in `text`, canonical names, in taxonomy order. Precision over recall."""
    body = clean_text(text, multiline=True)
    if not body:
        return []
    return [
        skill.name
        for skill, strong, weak in _PATTERNS
        if (strong and strong.search(body)) or (weak and weak.search(body))
    ]
