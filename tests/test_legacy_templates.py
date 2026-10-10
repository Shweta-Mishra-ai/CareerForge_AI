"""Characterisation tests for templates/cv_styles.py (replaced in Phase 5).

Passing tests pin behaviour we must not regress. `xfail(strict=True)` tests record KNOWN BUGS from the
audit: when a later phase fixes one, the test XPASSes, strict mode fails CI, and the marker must be removed.
"""

import pytest

from templates.cv_styles import render_cv

TEMPLATES = [
    "1. Premium Two-Column (Navy & White)",
    "2. Executive Corporate (Clean & Bold)",
    "3. Creative Professional (Ribbons & Colors)",
    "4. Minimalist Clean (Kinsley Morrison)",
    "5. Modern Single Column (Teal Accent)",
    "6. Academic Structured (Classic)",
    "7. Dark Premium (Gold & Charcoal)",
]

BASE = {
    "name": "Priya Nair",
    "headline": "Senior Backend Engineer",
    "contact": "priya@example.com | +91 98765 43210 | Bengaluru",
    "skills": "Python, Go, Redis",
    "experience": "<p><b>Engineer at Acme (2020 - Now)</b></p><ul><li>Built things</li></ul>",
    "education": "<p><b>B.Tech, NIT</b></p>",
    "certificates": "",
    "projects": "",
}


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_template_renders_html_with_name(template):
    html = render_cv(template, BASE)
    assert html.lstrip().startswith("<html>")
    assert "Priya Nair" in html or "Priya<br>Nair" in html  # template 4 splits the name


@pytest.mark.parametrize("template", TEMPLATES)
@pytest.mark.xfail(reason="AUDIT #5: render_cv does not HTML-escape user/LLM text (XSS)")
def test_name_and_skills_are_html_escaped(template):
    html = render_cv(template, {**BASE, "name": "<script>alert(1)</script>", "skills": "<img src=x onerror=alert(2)>"})
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x onerror=alert(2)>" not in html


@pytest.mark.xfail(reason="AUDIT #9: skills=None crashes render_cv with TypeError")
def test_none_skills_does_not_crash():
    render_cv(TEMPLATES[0], {**BASE, "skills": None})


@pytest.mark.xfail(reason="AUDIT: icon heuristic matches substring 'up' so 'Set up team' gets a location pin")
def test_contact_icon_not_fooled_by_substring_up():
    html = render_cv(TEMPLATES[4], {**BASE, "contact": "Set up team"})
    assert "📍" not in html


@pytest.mark.xfail(reason="AUDIT: unknown template silently falls through to template 7")
def test_unknown_template_name_is_rejected():
    with pytest.raises(ValueError):
        render_cv("does not exist", BASE)
