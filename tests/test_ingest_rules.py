"""The rule-based (no-AI) CV reader: layouts it understands, things it must never invent, and a PDF round trip."""

import random
import re

import pytest
from test_grounding import faithful_standard
from test_render_cv import fresher, ready

from careerforge.ai.grounding import ground_profile
from careerforge.ingest.pipeline import ingest_upload
from careerforge.ingest.rules import collapse_spaced, heading_of, read_cv
from careerforge.readiness import check
from careerforge.render.cv import render_cv_pdf
from careerforge.render.options import TEMPLATES, RenderOptions


def read(text):
    return read_cv(text)


class TestHeadings:
    @pytest.mark.parametrize(
        "line,section",
        [
            ("EXPERIENCE", "experience"),
            ("Work Experience", "experience"),
            ("Professional Experience:", "experience"),
            ("SKILLS", "skills"),
            ("Technical Skills", "skills"),
            ("S K I L L S", "skills"),
            ("W O R K  E X P E R I E N C E", "experience"),
            ("Education & Training", "education"),
            ("Projects", "projects"),
            ("Certifications", "certifications"),
            ("PROFILE", "summary"),
            ("Awards", "ignore"),
        ],
    )
    def test_recognised(self, line, section):
        assert heading_of(line) == section

    @pytest.mark.parametrize(
        "line",
        ["Experienced engineer with Python", "- Skills", "Skills include Python and Go", "My experience", "", "x" * 60],
    )
    def test_not_headings(self, line):
        assert heading_of(line) is None

    def test_spaced_letters_collapse_without_merging_words(self):
        assert collapse_spaced("W O R K  E X P E R I E N C E") == "WORK EXPERIENCE"
        assert collapse_spaced("Senior Engineer") == "Senior Engineer"
        assert collapse_spaced("A B") == "A B"  # too short to be a spaced word


class TestStandardLayouts:
    def test_standard_fixture_matches_the_expected_profile(self, fixture_text):
        p, notes = read(fixture_text("cv_ready.txt"))
        want = ready(faithful_standard())
        assert (p.name, p.headline, p.summary) == (want.name, want.headline, want.summary)
        assert p.contact == want.contact
        assert [(e.title, e.company, e.dates, e.bullets) for e in p.experience] == [
            (e.title, e.company, e.dates, e.bullets) for e in want.experience
        ]
        assert [(e.degree, e.institution, e.grade, e.dates.display()) for e in p.education] == [
            ("B.Tech Computer Science", "NIT Calicut", "CGPA 8.4", "2018")
        ]
        assert p.skills == want.skills
        assert [(c.name, c.date) for c in p.certifications] == [("AWS Certified Developer - Associate", "2022")]
        assert "basic (rule-based) reader" in notes[0]

    def test_fresher_fixture(self, fixture_text):
        p, _ = read(fixture_text("cv_fresher.txt"))
        assert p.name == "Arjun Mehta" and p.summary.startswith("Final-year student")
        assert p.contact.location == "Moradabad, UP, India" and p.contact.github == "https://github.com/arjun-demo"
        assert [(e.degree, e.institution, e.grade, e.dates.display()) for e in p.education] == [
            ("B.Tech Information Technology", "Demo Institute of Technology", "8.1 CGPA", "2021 – 2025")
        ]
        assert [(x.name, x.tech, x.description) for x in p.projects] == [
            (
                "Expense Tracker",
                ["React", "Node.js", "MongoDB"],
                "Built a full-stack web app to track expenses with charts.",
            ),
            (
                "Chatbot for college FAQs",
                ["Python", "Flask"],
                "Built a retrieval chatbot that answers admission questions.",
            ),
        ]
        assert p.experience == []

    def test_nothing_is_invented_for_a_document_without_headings(self, fixture_text):
        p, notes = read(fixture_text("cv_sparse.txt"))
        assert p.name == "Maria Gonzalez" and p.experience == [] and p.education == []
        assert any("No standard section headings" in n for n in notes)


class TestJobHeaderLayouts:
    def jobs(self, body):
        p, notes = read(f"Sam Lee\nsam.lee@gmail.com\n\nEXPERIENCE\n{body}\n")
        return [(e.title, e.company, e.location, e.dates.display(), e.bullets) for e in p.experience], notes

    def test_title_dash_company_with_dates_in_parentheses(self):
        jobs, notes = self.jobs("Data Analyst - RetailCo (2022 - Present)\n- Built dashboards.")
        assert jobs == [("Data Analyst", "RetailCo", "", "2022 – Present", ["Built dashboards."])]
        assert len(notes) == 1  # nothing ambiguous

    def test_title_at_company_pipe_dates(self):
        jobs, _ = self.jobs("Software Engineer at Acme Corp | Jan 2020 - Dec 2022\n- Shipped things.")
        assert jobs[0][:4] == ("Software Engineer", "Acme Corp", "", "Jan 2020 – Dec 2022")

    def test_company_dash_title_is_detected_by_the_title_word(self):
        jobs, _ = self.jobs("Globex Inc — Senior Developer (2019 - 2022)\n- Led a team.")
        assert jobs[0][:2] == ("Senior Developer", "Globex Inc")

    def test_title_and_dates_then_company_on_the_next_line(self):
        jobs, _ = self.jobs("Product Designer    Mar 2021 – Present\nNorthwind · Remote\n- Redesigned checkout.")
        assert jobs == [("Product Designer", "Northwind", "Remote", "Mar 2021 – Present", ["Redesigned checkout."])]

    def test_company_line_then_title_and_dates(self):
        jobs, _ = self.jobs("Northwind Payments\nBackend Engineer    2020 - 2023\n- Wrote APIs.")
        assert jobs[0][:2] == ("Backend Engineer", "Northwind Payments")

    def test_ambiguous_header_is_split_by_position_and_flagged(self):
        jobs, notes = self.jobs("Acme - Globex (2019 - 2020)\n- Did work.")
        assert jobs[0][:2] == ("Acme", "Globex")
        assert any("could not be told apart" in n for n in notes)

    def test_wrapped_bullets_are_joined_and_new_bullets_stay_separate(self):
        jobs, _ = self.jobs(
            "Engineer - Acme (2020 - 2022)\n"
            "* Automated weekly reports in Python,\n  saving 6 hours per week.\n"
            "* Second bullet that ends cleanly.\n"
            "• Third bullet"
        )
        assert jobs[0][4] == [
            "Automated weekly reports in Python, saving 6 hours per week.",
            "Second bullet that ends cleanly.",
            "Third bullet",
        ]

    def test_two_jobs_and_present_variants(self):
        jobs, _ = self.jobs(
            "Lead - A Co (Jan 2022 - Current)\n- One.\n\nEngineer - B Co (2019 - 2021)\n- Two.\n- Three."
        )
        assert [(j[0], j[3], len(j[4])) for j in jobs] == [
            ("Lead", "Jan 2022 – Present", 1),
            ("Engineer", "2019 – 2021", 2),
        ]

    def test_a_job_without_dates_is_not_invented_from_text(self):
        jobs, _ = self.jobs("Worked at a bakery decorating cakes\n- Made 100 cakes.")
        assert jobs == []  # no date range = no recognisable header, so nothing is made up


class TestOtherSections:
    def sections(self, body):
        return read(f"Sam Lee\nsam.lee@gmail.com\n\n{body}\n")[0]

    def test_skills_with_categories_and_separators(self):
        p = self.sections("SKILLS\nLanguages: Python, Go\nTools: Docker | Git; Kubernetes\n• Communication")
        assert p.skills == ["Python", "Go", "Docker", "Git", "Kubernetes", "Communication"]

    def test_markup_and_sentences_are_not_skills(self):
        p = self.sections("SKILLS\nPython, <script>alert(1)</script>, I have worked on many projects in my life.")
        assert p.skills == ["Python"]

    def test_skills_fall_back_to_known_skills_in_the_text_when_there_is_no_skills_section(self):
        p = read_cv("Sam Lee\nsam@gmail.com\nI build APIs with Python, Docker and Kubernetes. I like to go home.")[0]
        assert p.skills == ["Python", "Docker", "Kubernetes"]  # "go" in prose is not the language

    def test_education_multi_line_and_two_degrees(self):
        p = self.sections(
            "EDUCATION\nMaster of Science in Data Science\nState University\n2019 - 2021\nGPA 3.8/4.0\n\n"
            "Bachelor of Arts, City College, 2015 - 2019"
        )
        got = [(e.degree, e.institution, e.dates.display(), e.grade) for e in p.education]
        assert got == [
            ("Master of Science in Data Science", "State University", "2019 – 2021", "GPA 3.8/4.0"),
            ("Bachelor of Arts", "City College", "2015 – 2019", ""),
        ]

    def test_two_consecutive_one_line_degrees_are_two_entries(self):
        p = self.sections("EDUCATION\nM.Tech CSE, IIT Madras, 2020\nB.Tech CSE, NIT Trichy, 2018")
        assert [(e.degree, e.institution) for e in p.education] == [
            ("M.Tech CSE", "IIT Madras"),
            ("B.Tech CSE", "NIT Trichy"),
        ]

    def test_certifications_languages_and_summary(self):
        p = self.sections(
            "SUMMARY\nAnalyst who loves data.\nSecond line.\n\nCERTIFICATIONS\n- Google Data Analytics (2023)\nPMP, 2021\n\n"
            "LANGUAGES\nEnglish, Hindi (native)"
        )
        assert p.summary == "Analyst who loves data. Second line."
        assert [(c.name, c.date) for c in p.certifications] == [("Google Data Analytics", "2023"), ("PMP", "2021")]
        assert p.languages == ["English", "Hindi (native)"]

    def test_projects_with_url_label_and_parenthesised_tech(self):
        p = self.sections(
            "PROJECTS\nSettle Core (Go, Kafka) github.com/sam/settle-core\nOpen-source settlement engine.\n"
            "- Handles retries.\n\nTodo App\nTech: React, Redux\nA small app."
        )
        a, b = p.projects
        assert (a.name, a.tech, a.url, a.description, a.bullets) == (
            "Settle Core", ["Go", "Kafka"], "https://github.com/sam/settle-core", "Open-source settlement engine.", ["Handles retries."]
        )  # fmt: skip
        assert (b.name, b.tech, b.description) == ("Todo App", ["React", "Redux"], "A small app.")

    def test_ignored_sections_are_reported_not_imported(self):
        p, notes = read("Sam Lee\nsam@gmail.com\n\nINTERESTS\nChess\n\nSKILLS\nPython")
        assert p.skills == ["Python"] and "Chess" not in p.model_dump_json()
        assert any("were not imported" in n for n in notes)

    def test_overlong_summary_is_shortened_at_a_sentence_and_flagged(self):
        p, notes = read("Sam Lee\nsam@gmail.com\n\nSUMMARY\n" + "This is a sentence about work. " * 80)
        assert len(p.summary) <= 1500 and p.summary.endswith(".") and any("shortened" in n for n in notes)

    def test_all_caps_name_is_normalised_and_flagged(self):
        p, notes = read("SAMEER KHAN\nsam@gmail.com")
        assert p.name == "Sameer Khan" and any("capitals" in n for n in notes)


class TestHeaderParsing:
    @pytest.mark.parametrize(
        "first", ["Curriculum Vitae", "Resume", "sam@gmail.com", "+91 98765 43210", "Page 1 of 2", "<b>Sam</b> Lee"]
    )
    def test_non_names_are_not_taken_as_the_name(self, first):
        assert read(f"{first}\nsam@gmail.com\n\nSKILLS\nPython")[0].name == ""

    def test_headline_location_and_contact_line_with_separators(self):
        p, _ = read("Sam Lee\nBackend Developer\nsam@gmail.com | +91 98765 43210 | Pune, India | github.com/samlee\n")
        assert (p.name, p.headline, p.contact.location, p.contact.github) == (
            "Sam Lee",
            "Backend Developer",
            "Pune, India",
            "https://github.com/samlee",
        )

    def test_two_column_first_line_uses_only_the_first_column(self, fixture_text):
        assert read(fixture_text("cv_two_column.txt"))[0].name == "Sameer Khan"


class TestContactLinks:
    @pytest.mark.parametrize(
        "text,github",
        [
            ("github.com/priya-demo/repo", "https://github.com/priya-demo"),
            ("https://www.github.com/a_b-c", "https://www.github.com/a_b-c"),
            ("GitHub: github.com/priya-demo.", "https://github.com/priya-demo"),
        ],
    )
    def test_github_username_is_taken_whole(self, text, github):
        assert read_cv(f"Sam Lee\n{text}\nsam@gmail.com")[0].contact.github == github


class TestSafety:
    @pytest.mark.parametrize("name", ["cv_ready", "cv_fresher", "cv_sparse", "cv_hostile", "cv_two_column"])
    def test_output_is_always_grounded_in_the_source(self, fixture_text, name):
        text = fixture_text(f"{name}.txt")
        profile, _ = read(text)
        _, report = ground_profile(profile, text)
        assert report.findings == (), [(f.path, f.reason) for f in report.findings]

    def test_hostile_document_yields_no_name_no_headline_no_instructions_and_is_not_exportable(self, fixture_text):
        p, _ = read(fixture_text("cv_hostile.txt"))
        blob = p.model_dump_json()
        assert p.name == "" and p.headline == "" and p.skills == ["C++", "R&D", "it's"]
        assert "IGNORE ALL" not in blob and "Google" not in blob and "<script" not in blob
        assert not check(p).ready  # whatever markup remains inside bullets is caught by the export gate

    def test_ingest_pipeline_uses_it_and_reports_grounding(self, fixture_text):
        res = ingest_upload("cv.txt", fixture_text("cv_ready.txt").encode(), None)
        assert res.source == "heuristic" and res.grounding.findings == () and len(res.profile.experience) == 2

    def test_random_garbage_never_crashes_and_always_yields_a_valid_profile(self):
        rng = random.Random(7)
        words = [
            "Engineer",
            "2019",
            "-",
            "–",
            "EXPERIENCE",
            "Skills",
            "•",
            "(",
            ")",
            "Acme",
            "|",
            "at",
            "Mar",
            "Present",
            "B.Tech",
            "@",
            "x" * 70,
            "",
            "2020 - 2022",
            "*",
        ]
        for _ in range(300):
            lines = ["  ".join(rng.choice(words) for _ in range(rng.randint(0, 6))) for _ in range(rng.randint(1, 25))]
            profile, notes = read_cv("\n".join(lines))
            assert profile.model_dump() and notes

    def test_unicode_and_very_long_lines_do_not_crash(self):
        read_cv("李小龍\n" + "EXPERIENCE\n" + "Dev - Co (2020 - 2021)\n" + "- " + "é" * 5000)


# ── the whole loop: our own PDF -> text -> rule reader -> same facts ──────────


@pytest.mark.parametrize("template", [k for k, t in TEMPLATES.items() if t.ats_safe])
def test_a_pdf_we_generate_is_read_back_with_the_same_facts(template):
    original = ready(faithful_standard())
    pdf = render_cv_pdf(original, RenderOptions(template=template)).data
    res = ingest_upload("cv.pdf", pdf, None)
    p = res.profile
    assert p.name.casefold() == original.name.casefold() and p.headline.casefold() == original.headline.casefold()
    assert p.contact.email == original.contact.email and p.contact.phone == original.contact.phone
    assert [(e.title, e.company, e.dates) for e in p.experience] == [
        (e.title, e.company, e.dates) for e in original.experience
    ]
    assert [e.bullets for e in p.experience] == [e.bullets for e in original.experience]
    assert [(e.degree, e.institution, e.grade) for e in p.education] == [
        (e.degree, e.institution, e.grade) for e in original.education
    ]
    assert set(p.skills) == set(original.skills)
    assert [(c.name, c.date) for c in p.certifications] == [(c.name, c.date) for c in original.certifications]
    assert p.summary == original.summary
    assert res.grounding.findings == ()


def test_round_trip_for_a_fresher_cv():
    original = fresher()
    res = ingest_upload("cv.pdf", render_cv_pdf(original, RenderOptions()).data, None)
    p = res.profile
    assert [(x.name, x.tech, x.bullets, x.url) for x in p.projects] == [
        (x.name, x.tech, x.bullets, x.url) for x in original.projects
    ]
    assert [(e.degree, e.institution, e.grade) for e in p.education] == [
        (e.degree, e.institution, e.grade) for e in original.education
    ]
    assert re.sub(r"\W", "", p.name) == re.sub(r"\W", "", original.name)
