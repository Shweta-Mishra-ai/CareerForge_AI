"""The rule-based (no-AI) CV reader: layouts it understands, things it must never invent, and a PDF round trip."""

import random
import re

import pytest
from e2e_support import FIXTURES
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


# ── PDFs made by a real word processor (Word-style documents converted with LibreOffice) ──────────────────────
# The fixtures were produced by python-docx + LibreOffice, i.e. by software other than our own renderer.


def pdf_fixture(name):
    return (FIXTURES / name).read_bytes()


class TestRealWordProcessorPdfs:
    def read(self, name):
        res = ingest_upload(name, pdf_fixture(name), None)
        assert res.grounding.findings == ()
        return res.profile

    def test_single_column_with_tab_aligned_dates(self):
        p = self.read("real_word_classic.pdf")
        assert (p.name, p.headline, p.contact.location) == ("Rahul Verma", "Data Analyst", "Pune, India")
        assert [(e.title, e.company, e.dates.display(), len(e.bullets)) for e in p.experience] == [
            ("Senior Data Analyst", "RetailCo", "Jan 2022 – Present", 2),
            ("Data Analyst", "FinServe", "Jun 2019 – Dec 2021", 2),
        ]
        assert [(e.degree, e.institution, e.dates.display()) for e in p.education] == [
            ("B.Sc. Statistics", "Savitribai Phule Pune University", "2015 – 2018")
        ]
        assert p.skills == ["SQL", "Power BI", "Python", "Pandas", "Excel", "Tableau"]
        assert [c.name for c in p.certifications] == ["Microsoft Power BI Data Analyst"]

    def test_two_column_table_with_the_name_after_the_sidebar(self):
        p = self.read("real_word_sidebar_table.pdf")
        assert (p.name, p.headline) == ("Sneha Iyer", "Product Designer")
        assert p.languages == ["English", "Tamil", "Hindi"]  # the name did not leak into the languages
        assert p.skills == ["Figma", "User Research", "Prototyping", "HTML/CSS", "Accessibility"]
        assert [(e.title, e.company, e.dates.display()) for e in p.experience] == [
            ("Product Designer", "Northwind Apps", "2021 – Present"),
            ("UI Designer", "PixelCraft", "2018 – 2021"),
        ]
        assert [(e.degree, e.institution, e.dates.display()) for e in p.education] == [
            ("B.Des Communication Design", "NID Ahmedabad", "2014 – 2018")  # the range was wrapped over two lines
        ]
        assert p.contact.email == "sneha.iyer@gmail.com" and p.contact.location == "Chennai, India"

    def test_company_line_with_place_then_title_and_numeric_dates(self):
        p = self.read("real_word_company_first.pdf")
        assert p.name == "Priyanka Sharma" and p.contact.location == "Delhi"
        assert [(e.title, e.company, e.location, e.dates.display()) for e in p.experience] == [
            ("Marketing Manager", "Globex Corporation", "Delhi, India", "Mar 2020 – Present"),
            ("Marketing Executive", "Initech", "Mumbai, India", "Jul 2017 – Feb 2020"),
        ]
        assert [(e.degree, e.institution) for e in p.education] == [
            ("MBA, Marketing", "Symbiosis Institute of Business Management"),
            ("B.Com", "Delhi University"),
        ]
        assert p.skills == ["SEO", "Email Marketing", "Google Analytics", "Canva", "Content Strategy", "HubSpot"]


class TestNewReaderRules:
    def test_a_date_range_wrapped_over_two_lines_is_joined(self):
        p, _ = read_cv("Sam Lee\nsam@gmail.com\n\nEDUCATION\nBSc Physics, State University, 2014 –\n2018")
        assert p.education[0].dates.display() == "2014 – 2018"

    def test_a_trailing_dash_is_only_joined_to_a_following_date(self):
        p, _ = read_cv("Sam Lee\nsam@gmail.com\n\nSUMMARY\nI work on things -\nPython and Go projects")
        assert p.summary == "I work on things - Python and Go projects"

    def test_headline_comes_from_the_first_cell_of_a_contact_line(self):
        p, _ = read_cv("Sam Lee\nBackend Engineer | sam@gmail.com | +91 98765 43210 | Pune")
        assert (p.headline, p.contact.location) == ("Backend Engineer", "Pune")

    def test_a_contact_cell_is_never_taken_as_the_headline(self):
        p, _ = read_cv("Sam Lee\nsam@gmail.com | github.com/sam | Pune, India")
        assert p.headline == "" and p.contact.location == "Pune, India"

    def test_contact_section_supplies_a_location(self):
        p, _ = read_cv("Sam Lee\n\nCONTACT\nsam@gmail.com\nLisbon\n\nSKILLS\nPython")
        assert p.contact.location == "Lisbon" and p.skills == ["Python"]

    def test_the_name_rescue_never_overrides_a_name_that_was_found(self):
        p, _ = read_cv(
            "Sam Lee\nsam@gmail.com\n\nLANGUAGES\nEnglish\nMaria Gonzalez\nSpanish Teacher\n\nSKILLS\nPython"
        )
        assert p.name == "Sam Lee" and "Maria Gonzalez" in p.languages

    def test_the_name_rescue_needs_the_pair_to_close_a_section_and_not_be_a_known_skill(self):
        # not the last two lines of the section
        p, _ = read_cv("\nSKILLS\nPython\nMaria Gonzalez\nSpanish Teacher\nGo\n\nEXPERIENCE\nDev - Co (2020 - 2021)")
        assert p.name == ""
        # a known skill is never a name
        q, _ = read_cv("\nSKILLS\nProject Management\nData Analysis\n\nEXPERIENCE\nDev - Co (2020 - 2021)")
        assert q.name == "" and q.skills == ["Project Management", "Data Analysis"]

    def test_company_place_split_only_when_the_right_side_is_a_place(self):
        p, _ = read_cv("Sam\nEXPERIENCE\nGlobex - Delhi, India\nManager    2020 - 2021\n- Did work here.\n")
        assert (p.experience[0].company, p.experience[0].location) == ("Globex", "Delhi, India")
        q, _ = read_cv("Sam\nEXPERIENCE\nAcme - Data Platform Team\nManager    2020 - 2021\n- Did work here.\n")
        assert q.experience[0].company == "Acme - Data Platform Team" and q.experience[0].location == ""

    @pytest.mark.parametrize(
        "degree",
        ["B.Des Communication Design", "M.Des", "BFA Painting", "PGDM Marketing", "B.Pharm", "M.Ed Curriculum"],
    )
    def test_more_degree_names_are_recognised(self, degree):
        p, _ = read_cv(f"Sam\nEDUCATION\nSome Place, {degree}, 2019")
        assert p.education[0].degree == degree

    def test_unrecognised_education_parts_are_assigned_in_the_usual_order(self):
        p, _ = read_cv("Sam\nEDUCATION\nHonours Programme in Design, Northern Hall, Oslo, 2019")
        e = p.education[0]
        assert (e.degree, e.institution, e.location) == ("Honours Programme in Design", "Northern Hall", "Oslo")

    def test_a_job_title_at_the_end_of_a_sidebar_section_is_not_taken_for_a_name(self):
        p, _ = read_cv(
            "\nLANGUAGES\nEnglish\nSpanish Teacher\nOnline Language Instructor\n\nEXPERIENCE\nDev - Co (2020 - 2021)"
        )
        assert p.name == "" and "Spanish Teacher" in p.languages

    def test_the_headline_under_a_rescued_name_must_look_like_a_headline(self):
        p, _ = read_cv("\nLANGUAGES\nEnglish\nMaria Gonzalez\nHindi\n\nEXPERIENCE\nDev - Co (2020 - 2021)")
        assert p.name == "" and p.languages == ["English", "Maria Gonzalez", "Hindi"]


class TestLinkedInStylePdf:
    """A document laid out like LinkedIn's 'Save to PDF' (sidebar first; company, title, then dates with a duration).

    The sample was composed from knowledge of that layout, NOT exported from a real account: treat it as a regression
    guard for the layout, not as proof about every real export.
    """

    def profile(self):
        res = ingest_upload("l.pdf", pdf_fixture("real_linkedin_style.pdf"), None)
        assert res.grounding.findings == ()
        return res.profile

    def test_identity_comes_from_after_the_sidebar(self):
        p = self.profile()
        assert (p.name, p.headline) == ("Rahul Verma", "Senior Data Analyst at RetailCo")
        assert p.contact.location == "Pune, Maharashtra, India" and p.contact.email == "rahul.verma@gmail.com"
        assert p.contact.linkedin == "https://www.linkedin.com/in/rahul-verma-demo"

    def test_company_then_title_then_dates_with_duration_and_a_location_line(self):
        p = self.profile()
        assert [(e.title, e.company, e.location, e.dates.display(), e.bullets) for e in p.experience] == [
            (
                "Senior Data Analyst",
                "RetailCo",
                "Pune, Maharashtra, India",
                "Jan 2022 – Present",
                [
                    "Built 12 Power BI dashboards used by 40 managers.",
                    "Automated weekly reporting in Python, saving 6 hours per week.",
                ],
            ),
            (
                "Data Analyst",
                "FinServe",
                "Mumbai, Maharashtra, India",
                "Jun 2019 – Dec 2021",
                ["Wrote SQL queries over 50M rows to detect fraud patterns."],
            ),
        ]

    def test_education_over_two_lines_keeps_the_whole_degree(self):
        p = self.profile()
        assert [(e.degree, e.institution, e.dates.display()) for e in p.education] == [
            ("Bachelor of Science - BS, Statistics", "Savitribai Phule Pune University", "2015 – 2018")
        ]

    def test_top_skills_are_extended_with_skills_the_document_itself_uses_and_awards_are_not_certifications(self):
        p = self.profile()
        assert p.skills[:3] == ["SQL", "Power BI", "Python"]
        assert [c.name for c in p.certifications] == [
            "Microsoft Power BI Data Analyst",
            "Google Data Analytics Certificate",
        ]
        assert p.languages == ["English (Native or Bilingual)", "Hindi (Full Professional)"]
        assert "Employee of the Year" not in p.model_dump_json()

    def test_duration_text_is_never_taken_for_a_company_or_title(self):
        p, _ = read_cv(
            "Sam\n\nEXPERIENCE\nAcme\nEngineer\nMarch 2020 - Present (5 years 7 months)\nPune, India\n- Did it."
        )
        e = p.experience[0]
        assert (e.title, e.company, e.location) == ("Engineer", "Acme", "Pune, India")
        assert "years" not in p.model_dump_json()

    def test_two_plain_lines_before_a_date_are_only_a_company_and_title_when_one_looks_like_a_title(self):
        text = "Sam\n\nEXPERIENCE\nAcme\nEngineer\n2020 - 2021\n- First.\nLed migration of services\nWrote the docs\n2018 - 2019\n"
        first, second = read_cv(text)[0].experience
        assert (first.title, first.company) == ("Engineer", "Acme")
        assert first.bullets == ["First.", "Led migration of services"]  # a plain line stays a bullet of its own job
        assert "Led migration of services" not in f"{second.title}{second.company}"

    def test_a_name_followed_by_more_than_a_headline_and_a_place_is_not_a_rescued_name(self):
        text = "\nLANGUAGES\nEnglish\nMaria Gonzalez\nProduct Designer\nPune, India\nHindi\n\nEXPERIENCE\nDev - Co (2020 - 2021)"
        p, _ = read_cv(text)
        assert p.name == "" and "Maria Gonzalez" in p.languages and "Hindi" in p.languages

    def test_top_skills_are_extended_only_for_linkedin_style_documents(self):
        body = "EXPERIENCE\nDev - Co (2020 - 2021)\n- Deployed services with Docker and Kubernetes.\n"
        linkedin, _ = read_cv(f"Sam Lee\nsam@gmail.com\n\nTop Skills\nSQL\n\n{body}")
        plain, _ = read_cv(f"Sam Lee\nsam@gmail.com\n\nSKILLS\nSQL\n\n{body}")
        assert linkedin.skills == ["SQL", "Docker", "Kubernetes"] and plain.skills == ["SQL"]


class TestBounds:
    def test_a_run_of_blank_lines_is_one_separator_and_does_not_hide_content(self):
        p, _ = read_cv("Sam Lee\nsam@gmail.com" + "\n" * 50_000 + "SKILLS\nPython")
        assert p.name == "Sam Lee" and p.skills == ["Python"]

    def test_absurd_line_counts_are_cut_with_a_note(self):
        p, notes = read_cv("SKILLS\nPython\n" + "x\n" * 20_000)
        assert "Python" in p.skills  # the first part was read
        assert any("very long" in n for n in notes)

    def test_a_long_paragraph_on_one_line_is_still_read_as_a_summary(self):
        sentence = "Backend engineer who builds reliable payment systems. "
        p, _ = read_cv(f"Sam Lee\nsam@gmail.com\n\nSUMMARY\n{sentence * 20}\n\nSKILLS\nPython")
        assert p.summary == (sentence * 20).strip() and p.skills == ["Python"]  # re-joined at the original spaces

    def test_a_token_without_spaces_longer_than_a_line_is_split_not_dropped(self):
        p, _ = read_cv("Sam Lee\nsam@gmail.com\n\nSUMMARY\n" + "a" * 1000)
        assert len(p.summary.replace(" ", "")) == 1000
