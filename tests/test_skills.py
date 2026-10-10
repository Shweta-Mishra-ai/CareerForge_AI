import pytest

from careerforge import skills
from careerforge.skills import find_skills


class TestFindSkills:
    def test_regression_no_r_in_ordinary_words(self):
        # AUDIT #4: old substring matcher found 'R' (and others) in ordinary prose
        assert skills.find_skills("I love programming and stress testing, mirrors and storage") == []

    @pytest.mark.parametrize(
        "text,absent",
        [
            ("Experienced in JavaScript and React", "Java"),
            ("Worked at design studios", "iOS"),
            ("Managed storage and the fragmentation of data", "RAG"),
            ("MySQL and PostgreSQL databases", "SQL"),
            ("Please express interest and go to the market", "Express.js"),
            ("We excel in delivery", "Excel"),
            ("Spring cleaning and a golden retriever", "Spring"),
        ],
    )
    def test_no_false_positives(self, text, absent):
        assert absent not in skills.find_skills(text)

    @pytest.mark.parametrize(
        "text,present",
        [
            ("Python, Go, R, SQL", "R"),
            ("Python, Go, R, SQL", "Go"),
            ("Skills: C, C++, Rust", "C"),
            ("Statistics in R programming", "R"),
            ("Backend in Golang", "Go"),
            ("Dashboards in Microsoft Excel", "Excel"),
            ("Built with Node.js and Express", "Node.js"),
            ("Skills: React, Express, Mongo", "Express.js"),
            ("Deployed with k8s on GCP", "Kubernetes"),
            ("Wrote C# and .NET services", "C#"),
            ("Wrote C# and .NET services", ".NET"),
            ("CI/CD via GitHub Actions", "CI/CD"),
            ("REST APIs over gRPC", "REST API"),
        ],
    )
    def test_finds_real_mentions(self, text, present):
        assert present in skills.find_skills(text)

    def test_c_does_not_match_cpp_or_csharp(self):
        found = skills.find_skills("I use C++ and C#")
        assert "C" not in found and "C++" in found and "C#" in found

    def test_dotnet_not_confused_with_node_dot_js(self):
        assert "Node.js" not in skills.find_skills("ASP.NET developer")

    def test_empty(self):
        assert skills.find_skills("") == [] and skills.find_skills(None) == []


class TestCanonical:
    @pytest.mark.parametrize(
        "raw,want",
        [
            ("nodejs", "Node.js"),
            ("POSTGRES", "PostgreSQL"),
            ("k8s", "Kubernetes"),
            ("  react.js ", "React"),
            ("Obscure Tool 9", "Obscure Tool 9"),
        ],
    )
    def test_canonicalize(self, raw, want):
        assert skills.canonicalize(raw) == want

    def test_dedupe_keeps_order_and_merges_aliases(self):
        assert skills.dedupe(["python", "Node", "PYTHON", "nodejs", "", "Foo", "foo"]) == ["Python", "Node.js", "Foo"]

    def test_category(self):
        assert skills.category_of("docker") == "Cloud & DevOps" and skills.category_of("zzz") == "Other"

    def test_taxonomy_has_no_alias_collisions(self):
        seen = {}
        for s in skills.TAXONOMY:
            for key in (s.name, *s.aliases):
                key = key.lower()
                assert seen.setdefault(key, s.name) == s.name, f"{key!r} maps to {seen[key]} and {s.name}"


class TestAmbiguousWordsJoinedByAndOr:
    @pytest.mark.parametrize(
        "text,present",
        [
            ("skilled in SQL, Tableau or Power BI, Python (Pandas), Excel and stakeholder communication", "Excel"),
            ("Tools: Tableau, Python and Excel, plus SQL", "Excel"),
            ("Languages: Python, Go and Rust", "Go"),
            ("Backend: Node.js, Express and MongoDB", "Express.js"),
        ],
    )
    def test_found(self, text, present):
        assert present in skills.find_skills(text)

    @pytest.mark.parametrize(
        "text,absent",
        [
            ("Excel and stakeholder management are important", "Excel"),  # sentence start: no explicit delimiter
            ("Spring and summer internships", "Spring"),
            ("We excel in delivery, and we love it", "Excel"),  # lower-case verb
            ("Thanks, go and tell them", "Go"),  # lower-case 'go'
            ("Open to Spring or Fall cohorts", "Spring"),
            ("He will express, and then excel, over time", "Express.js"),
        ],
    )
    def test_not_found(self, text, absent):
        assert absent not in skills.find_skills(text)


class TestImplication:
    def test_one_direction_only(self):
        assert skills.implied_by("Python", {"Flask"}) == "Flask"
        assert skills.implied_by("Flask", {"Python"}) is None

    def test_a_skill_never_implies_itself(self):
        assert skills.implied_by("Python", {"Python"}) is None
        assert skills.implied_by("SQL", {"SQL", "Excel"}) is None

    def test_unknown_and_empty(self):
        assert skills.implied_by("Python", set()) is None and skills.implied_by("Nope", {"Flask"}) is None

    def test_every_implied_target_is_a_known_skill(self):
        for source, targets in skills.IMPLIES.items():
            assert source in skills.KNOWN_NAMES, source
            assert all(t in skills.KNOWN_NAMES and t != source for t in targets), (source, targets)


# ── the containment rule is implemented as a sweep; it must agree with the obvious (quadratic) definition ──────


def _reference_standalone(spans):
    """The definition, written the slow obvious way."""
    keep = set()
    for name, mine in spans.items():
        others = [sp for other, sps in spans.items() if other != name for sp in sps]
        if any(not any(oa <= a and b <= ob and (ob - oa) > (b - a) for oa, ob in others) for a, b in mine):
            keep.add(name)
    return keep


def test_sweep_matches_the_definition_on_random_overlapping_mentions():
    import random

    from careerforge.skills import _standalone

    rng = random.Random(11)
    for _ in range(3000):
        spans = {}
        for name in rng.sample("ABCDEFG", rng.randint(1, 6)):
            found = []
            for _ in range(rng.randint(1, 5)):
                a = rng.randint(0, 25)
                found.append((a, a + rng.randint(1, 8)))
            spans[name] = found
        assert _standalone(spans) == _reference_standalone(spans), spans


@pytest.mark.parametrize(
    "text,expected",
    [
        ("We use GitHub Actions for CI", {"GitHub Actions"}),
        ("GitHub Actions and GitHub", {"GitHub Actions", "GitHub"}),
        ("Spring Boot", {"Spring Boot"}),
    ],
)
def test_nested_names_are_still_counted_once(text, expected):
    assert expected <= set(find_skills(text)) and (("GitHub" in find_skills(text)) == ("GitHub" in expected))


def test_a_huge_document_is_processed_in_linear_time():
    import time

    text = "Built pipelines with GitHub Actions, Docker and Kubernetes. " * 10000  # about 600 KB, 30,000 mentions
    start = time.perf_counter()
    found = find_skills(text)
    elapsed = time.perf_counter() - start
    assert sorted(found) == ["Docker", "GitHub Actions", "Kubernetes"] and elapsed < 15  # was minutes when quadratic
