import pytest

from careerforge import skills


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
