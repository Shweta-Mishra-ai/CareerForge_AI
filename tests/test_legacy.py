"""Legacy adapter tests. Inputs mirror what the old prompts/code actually produced."""

import re

import pytest

from careerforge.legacy import html_to_blocks, parse_contact_string, profile_from_legacy

CF_EXPERIENCE = (
    "<p><b>Senior Backend Engineer at Finlytics Pvt Ltd (Mar 2021 – Present)</b></p>"
    "<ul><li>Cut p95 latency from 480ms to 190ms</li><li>Mentored 4 engineers</li></ul>"
    "<p><b>Software Engineer at ShipFast (Jul 2018 – Feb 2021)</b></p>"
    "<ul><li>Built full-stack real-time tracking APIs</li></ul>"
)


def test_careerforge_experience_html():
    p, warnings = profile_from_legacy({"name": "A B", "experience": CF_EXPERIENCE})
    assert warnings == []
    first, second = p.experience
    assert (first.title, first.company) == ("Senior Backend Engineer", "Finlytics Pvt Ltd")
    assert first.dates.display() == "Mar 2021 – Present"
    assert first.bullets == ["Cut p95 latency from 480ms to 190ms", "Mentored 4 engineers"]
    assert second.dates.display() == "Jul 2018 – Feb 2021"
    assert second.bullets == ["Built full-stack real-time tracking APIs"]  # AUDIT: hyphens must survive


def test_education_projects_certificates_html():
    p, w = profile_from_legacy(
        {
            "name": "A",
            "education": "<p><b>B.Tech Computer Science, NIT Calicut</b><br>2014 – 2018 | CGPA 8.4</p>",
            "projects": "<p><b>Tracker | React, Node.js</b></p><ul><li>Built charts</li></ul>",
            "certificates": "<p><b>AWS Developer</b> — Amazon (2022)</p>",
        }
    )
    assert w == []
    edu = p.education[0]
    assert (edu.degree, edu.institution, edu.grade) == ("B.Tech Computer Science", "NIT Calicut", "CGPA 8.4")
    assert edu.dates.display() == "2014 – 2018"
    assert p.projects[0].name == "Tracker" and p.projects[0].tech == ["React", "Node.js"]
    assert p.projects[0].bullets == ["Built charts"]
    cert = p.certifications[0]
    assert (cert.name, cert.issuer, cert.date) == ("AWS Developer", "Amazon", "2022")


def test_contact_pipe_string():
    c = parse_contact_string("a@b.com | +91 98765 43210 | linkedin.com/in/x | github.com/y | Pune, India")
    assert (c.email, c.phone, c.location) == ("a@b.com", "+91 98765 43210", "Pune, India")
    assert c.linkedin.endswith("/in/x") and c.github.endswith("/y")


def test_bad_contact_pieces_become_warnings_not_crashes():
    w = []
    c = parse_contact_string("not@@mail | javascript:alert(1)", w)
    assert c.email == "" and w


def test_careerboost_dict_shape():
    p, w = profile_from_legacy(
        {
            "name": "Priya",
            "current_title": "Engineer",
            "email": "p@example.com",
            "phone": "+91 98765 43210",
            "location": "Pune",
            "linkedin": "https://linkedin.com/in/p",
            "github": "https://github.com/p",
            "skills": ["python", "nodejs"],
            "experience": [
                {
                    "title": "Dev",
                    "company": "Acme",
                    "duration": "Jan 2020 - Present",
                    "description": "Built full-stack apps\n• Reduced cost by 30%",
                }
            ],
            "education": [{"degree": "B.Tech", "institution": "NIT", "year": "2018"}],
            "projects": [
                {
                    "name": "Tool",
                    "description": "A tool",
                    "language": "Python",
                    "stars": 5,
                    "url": "https://github.com/p/tool",
                    "topics": ["cli"],
                }
            ],
            "certifications": ["AWS Developer"],
            "years_experience": 5,
            "raw_text": "x",
            "github_stats": {"stars": 1},
        }
    )
    assert w == []
    assert p.headline == "Engineer" and p.skills == ["Python", "Node.js"]
    assert p.experience[0].bullets == ["Built full-stack apps", "Reduced cost by 30%"]
    assert p.experience[0].dates.current is True
    assert p.projects[0].tech == ["Python", "cli"] and p.projects[0].stars == 5
    assert p.education[0].dates.display() == "2018"


def test_placeholder_names_become_empty():
    p, _ = profile_from_legacy({"name": "Candidate", "headline": "Professional"})
    assert p.name == "" and p.headline == ""


def test_unreadable_dates_warn_and_keep_the_item():
    p, w = profile_from_legacy({"experience": "<p><b>Dev at Acme (back in the day)</b></p><ul><li>x</li></ul>"})
    assert p.experience[0].company.startswith("Acme") and p.experience[0].dates.is_empty()


def test_garbled_item_does_not_abort_the_rest():
    p, w = profile_from_legacy(
        {"projects": [{"name": "ok"}, {"name": "bad", "url": "javascript:alert(1)"}, {"name": "also ok"}]}
    )
    assert [x.name for x in p.projects] == ["ok", "also ok"]
    assert any("bad" in m or "project #2" in m for m in w)


def test_plain_text_experience_is_not_lost():
    p, _ = profile_from_legacy({"experience": "Worked at a bakery doing sales"})
    e = p.experience[0]
    assert (e.title, e.company) == ("", "")  # no invented structure
    assert e.bullets == ["Worked at a bakery doing sales"]


def test_script_content_is_dropped_but_text_kept():
    blocks = html_to_blocks("<p><b>Dev</b></p><script>alert(1)</script><ul><li>ok</li></ul>")
    flat = " ".join(" ".join([b.header, b.rest, *b.lines, *b.bullets]) for b in blocks)
    assert "alert" not in flat and "ok" in flat


@pytest.mark.parametrize("fixture", ["cv_standard.txt", "cv_hostile.txt"])
def test_content_words_are_preserved_through_html_roundtrip(fixture, fixture_text):
    """Property: wrapping lines as <li> and parsing back loses no words."""
    words = [w for w in re.findall(r"[A-Za-z]{4,}", fixture_text(fixture)) if w.lower() not in {"script"}]
    html = (
        "<p><b>Header</b></p><ul>"
        + "".join(
            f"<li>{ln.replace('&', '&amp;').replace('<', '&lt;')}</li>" for ln in fixture_text(fixture).splitlines()
        )
        + "</ul>"
    )
    blocks = html_to_blocks(html)
    text = " ".join(b for blk in blocks for b in blk.bullets)
    assert all(w in text for w in words)
