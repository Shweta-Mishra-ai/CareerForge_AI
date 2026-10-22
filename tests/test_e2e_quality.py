"""Security, mobile layout and accessibility, in a real browser."""

import re

import pytest
from axe_playwright_python.sync_playwright import Axe
from e2e_fixtures import CV, Session
from playwright.sync_api import expect
from test_render_portfolio import THEME_KEYS, build, full_profile

from careerforge.render.portfolio import LAYOUTS

pytestmark = pytest.mark.e2e

PAYLOAD = (
    '<img src=x onerror="window.__pwned=1"> <script>window.__pwned=1</script> [x](javascript:window.__pwned=1) '
    '"><svg onload=window.__pwned=1> {{7*7}} {% raw %} ${7*7}'
)
HOSTILE_CV = f"""Eve Mallory
eve.mallory@gmail.com | +1 415 555 0132 | Springfield, USA

SUMMARY
Engineer. {PAYLOAD}

EXPERIENCE
Engineer - Acme (2020 - 2023)
- Built things. {PAYLOAD}
- Second bullet [link](javascript:window.__pwned=1) done.

EDUCATION
BSc Computing, State University, 2019

PROJECTS
Tool {PAYLOAD}
Does stuff. {PAYLOAD}

SKILLS
Python, Docker
"""


def pwned(page) -> bool:
    return bool(page.evaluate("window.__pwned") or any(f.evaluate("window.__pwned") for f in page.frames[1:]))


class TestHostileContent:
    def test_nothing_in_the_cv_job_posting_or_previews_can_run_code(self, session, tmp_path):
        s, page = session, session.page
        path = tmp_path / "evil.txt"
        path.write_text(HOSTILE_CV, encoding="utf-8")
        s.load_cv(path)
        for section in ("Skills", "Experience", "Education", "Projects", "Certifications", "Basics"):
            s.choose(section)
            s.settle()
            assert not pwned(page) and not s.dialogs
        s.go("ATS check")
        s.paste_job(f"Job\nRequirements: Python {PAYLOAD}")
        expect(page.get_by_text("ATS match score")).to_be_visible()
        s.go("Insights")
        s.choose("Keyword heat")
        s.go("CV")
        s.settle()
        for template in ("ATS Modern", "Executive", "Designed Sidebar"):
            page.get_by_role("combobox", name="Template").click()
            page.get_by_role("option", name=template).click()
            s.settle()
            assert not pwned(page)
        s.go("Portfolio")
        s.settle()
        assert not pwned(page)
        s.go("Letters & interviews")
        page.get_by_label("Company", exact=True).fill(PAYLOAD)
        s.choose("Outreach emails")
        s.settle()
        assert not pwned(page) and not s.dialogs
        # no element created from user text exists anywhere in the app page (previews live in sandboxed frames)
        assert page.locator("img[src='x'], [onerror], [onload]").count() == 0
        s.assert_clean()

    def test_preview_frames_forbid_scripts_even_if_markup_slipped_through(self, session):
        s, page = session, session.page
        s.load_cv()
        s.go("CV")
        frame_el = page.locator("iframe").first
        expect(frame_el).to_be_visible(timeout=30000)
        frame = page.frame_locator("iframe").first
        expect(frame.get_by_text("Priya Nair").first).to_be_visible()
        ran = page.frames[1].evaluate(
            "() => { const s = document.createElement('script'); s.textContent = 'window.__csp = 1';"
            " document.head.appendChild(s); return window.__csp === 1; }"
        )
        assert ran is False  # the CSP inside the preview blocked the inline script

    def test_oversized_and_wrong_type_uploads_are_refused_politely(self, session, tmp_path):
        s, page = session, session.page
        exe = tmp_path / "x.exe"
        exe.write_bytes(b"MZ\x90\x00")
        page.set_input_files("input[type=file]", str(exe))
        expect(page.get_by_text("not allowed", exact=False).or_(page.get_by_text("File type"))).to_be_visible(
            timeout=10000
        )
        assert not page.locator("[data-testid=stException]").count()
        zip_bomb = tmp_path / "bomb.zip"
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Profile.csv", "First Name,Last Name\n" + "A,B\n" * 5)
            z.writestr("Messages.csv", "x" * 2_000_000)
        zip_bomb.write_bytes(buf.getvalue())
        page.set_input_files("input[type=file]", str(zip_bomb))
        s.click("Read this file")
        s.settle()
        assert not page.locator("[data-testid=stException]").count()  # messages are never read; no crash either way
        assert "Traceback" not in s.server.log_text()


class TestMobile:
    @pytest.fixture
    def phone(self, browser, server):
        s = Session(browser, server, viewport=(375, 740))
        yield s
        s.close()

    def overflow(self, page) -> int:
        return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")

    def test_core_flow_works_on_a_phone_without_sideways_scrolling(self, phone):
        s, page = phone, phone.page
        assert self.overflow(page) <= 1
        page.set_input_files("input[type=file]", str(CV))
        s.choose("Basic (no AI, nothing leaves this app)") if page.get_by_text("Basic (no AI").count() else None
        s.click("Read this file")
        s.wait_title("Review & edit")
        assert self.overflow(page) <= 1
        expect(page.get_by_label("Full name")).to_have_value("Priya Nair")
        # the navigation lives behind the menu button on small screens
        page.get_by_test_id("stExpandSidebarButton").click()
        page.get_by_role("link", name="ATS check").first.click()
        s.wait_title("ATS check")
        assert self.overflow(page) <= 1
        s.paste_job()
        expect(page.get_by_text("ATS match score")).to_be_visible()
        assert self.overflow(page) <= 1
        s.assert_clean()

    def test_export_page_fits_a_phone(self, phone):
        s, page = phone, phone.page
        s.load_cv()
        page.get_by_test_id("stExpandSidebarButton").click()
        page.get_by_role("link", name=re.compile(r"(^|\s)CV$")).first.click()
        s.wait_title("CV")
        expect(page.get_by_role("button", name=re.compile("Build my files"))).to_be_visible(timeout=30000)
        assert self.overflow(page) <= 1

    @pytest.mark.parametrize("layout", list(LAYOUTS))
    @pytest.mark.parametrize("theme", THEME_KEYS)
    def test_generated_portfolio_is_responsive_at_320px(self, browser, theme, layout, tmp_path):
        f = tmp_path / "index.html"
        f.write_text(build(full_profile(), theme=theme, layout=layout), encoding="utf-8")
        page = browser.new_page(viewport={"width": 320, "height": 640})
        page.goto(f.as_uri())
        assert page.evaluate("document.documentElement.scrollWidth") <= 320
        page.close()


# ── accessibility ───────────────────────────────────────────────────────────

# Streamlit's own chrome, which we cannot change. Everything else (all of our content, widgets, colours) is enforced.
#  * the sidebar page-navigation list is built from non-list markup (axe: list / listitem)
#  * the sidebar container carries an ARIA attribute axe does not allow on it (aria-allowed-attr on .stSidebar)
STREAMLIT_NAV = "[data-testid='stSidebarNav']"
STREAMLIT_CONTAINER_RULES = {("aria-allowed-attr", ".stSidebar")}


def violations(page):
    results = Axe().run(
        page,
        context={"exclude": [[STREAMLIT_NAV]]},
        options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]}},
    )
    out = []
    for v in results.response["violations"]:
        if v["impact"] not in ("serious", "critical"):
            continue
        nodes = [n for n in v["nodes"] if (v["id"], str(n["target"][0])) not in STREAMLIT_CONTAINER_RULES]
        if nodes:
            out.append({**v, "nodes": nodes})
    return out


def describe(found) -> str:
    return "\n".join(
        f"{v['id']} ({v['impact']}): {v['help']} :: "
        + "; ".join(n["target"][0] if isinstance(n["target"][0], str) else str(n["target"][0]) for n in v["nodes"][:3])
        for v in found
    )


class TestAccessibility:
    def test_start_page(self, session):
        found = violations(session.page)
        assert not found, describe(found)

    def test_review_page_sections(self, session):
        s = session
        s.load_cv()
        for section in ("Basics", "Skills", "Experience", "Education", "Certifications"):
            s.choose(section)
            s.settle()
            found = violations(s.page)
            assert not found, f"{section}: {describe(found)}"

    def test_ats_results_page(self, session):
        s = session
        s.load_cv()
        s.go("ATS check")
        s.paste_job()
        expect(s.page.get_by_text("ATS match score")).to_be_visible()
        found = violations(s.page)
        assert not found, describe(found)

    def test_export_page(self, session):
        s = session
        s.load_cv()
        s.go("CV")
        expect(s.page.get_by_role("button", name=re.compile("Build my files"))).to_be_visible(timeout=30000)
        found = violations(s.page)
        assert not found, describe(found)

    def test_jobs_settings_and_about_pages(self, session):
        s = session
        s.load_cv()
        for name in (
            "Jobs & tracker",
            "Settings",
            "How it works",
            "Insights",
            "Letters & interviews",
            "LinkedIn profile",
        ):
            s.go(name)
            s.settle()
            found = violations(s.page)
            assert not found, f"{name}: {describe(found)}"

    @pytest.mark.parametrize("layout", list(LAYOUTS))
    @pytest.mark.parametrize("theme", THEME_KEYS)
    def test_generated_portfolio_has_no_wcag_violations(self, browser, theme, layout, tmp_path):
        f = tmp_path / "index.html"
        f.write_text(build(full_profile(), theme=theme, layout=layout), encoding="utf-8")
        page = browser.new_page()
        page.goto(f.as_uri())
        results = Axe().run(
            page,
            options={
                "runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]}
            },
        )
        found = results.response["violations"]
        page.close()
        assert not found, describe(found)

    @pytest.mark.parametrize("layout", list(LAYOUTS))
    def test_the_automatic_portfolio_is_accessible_in_dark_mode_too(self, browser, layout, tmp_path):
        f = tmp_path / "index.html"
        f.write_text(build(full_profile(), theme="auto", layout=layout), encoding="utf-8")
        page = browser.new_page(color_scheme="dark")
        page.goto(f.as_uri())
        assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(15, 23, 42)"  # really dark
        results = Axe().run(
            page, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "best-practice"]}}
        )
        found = results.response["violations"]
        page.close()
        assert not found, describe(found)

    @pytest.mark.parametrize("layout", list(LAYOUTS))
    @pytest.mark.parametrize("scheme", ["light", "dark"])
    def test_portfolio_with_case_studies_cv_button_and_404_page_are_accessible(self, browser, tmp_path, scheme, layout):
        from datetime import date

        from test_portfolio_v2 import PDF

        from careerforge.models import Project
        from careerforge.render.portfolio import PortfolioOptions, build_portfolio

        p = full_profile()
        p = p.model_copy(update={"projects": [Project(name="Big One", description="Flagship.", bullets=["Cut costs by 30%"], tech=["Go"], url="https://github.com/priya-demo/big", demo_url="https://big.example.com", featured=True), *p.projects]})  # fmt: skip
        built = build_portfolio(
            p,
            PortfolioOptions(
                theme="auto", layout=layout, include_cv=True, custom_domain="jane.dev", show_location=True
            ),
            today=date(2026, 10, 10),
            cv_pdf=PDF,
        )
        for name in ("index.html", "404.html"):
            f = tmp_path / name
            f.write_bytes(built.files()[name])
            page = browser.new_page(color_scheme=scheme)
            page.goto(f.as_uri())
            results = Axe().run(
                page, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "best-practice"]}}
            )
            found = [v for v in results.response["violations"] if not (name == "404.html" and v["id"] == "region")]
            page.close()
            assert not found, f"{name} ({scheme}): {describe(found)}"

    def test_the_cover_letter_html_is_accessible(self, browser, tmp_path):
        from datetime import date

        from test_letter import FULL, JD, P

        from careerforge.render.letter import render_letter_html
        from careerforge.writing.basic_letter import build_basic_letter

        letter = build_basic_letter(P, JD, details=FULL, today=date(2026, 10, 10)).letter
        f = tmp_path / "letter.html"
        f.write_text(render_letter_html(letter), encoding="utf-8")
        page = browser.new_page()
        page.goto(f.as_uri())
        results = Axe().run(page, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa"]}})
        found = [v for v in results.response["violations"] if v["id"] != "region"]  # a letter has no site landmarks
        page.close()
        assert not found, describe(found)

    def test_letters_page_with_a_letter_lint_and_outreach_tabs(self, session):
        s, page = session, session.page
        s.load_cv()
        s.go("Letters & interviews")
        s.paste_job()
        s.click("Create my cover letter")
        expect(page.get_by_text("What was checked")).to_be_visible(timeout=30000)
        found = violations(page)
        assert not found, f"letter: {describe(found)}"
        s.choose("Outreach emails")
        company = page.get_by_label("Company", exact=True)
        company.fill("Northwind Payments")
        company.blur()
        for tab, marker in (
            ("Apply and follow up", "Cold email to a recruiter or hiring manager"),
            ("Replies for other moments", "Reply to a recruiter who contacted you"),
            ("Find the right people", "Boolean search"),
        ):
            page.get_by_role("tab", name=tab).click()
            expect(page.get_by_text(marker).first).to_be_visible(timeout=30000)
            found = violations(page)
            assert not found, f"outreach ({tab}): {describe(found)}"

    def test_jobs_page_with_filters_and_tracker_details(self, session):
        s, page = session, session.page
        s.load_cv()
        s.go("Jobs & tracker")
        expect(page.get_by_role("textbox", name=re.compile("Company careers pages"))).to_be_visible()
        found = violations(page)
        assert not found, f"jobs: {describe(found)}"
        s.choose("Application tracker")
        page.get_by_label("Company", exact=True).fill("Acme")
        page.get_by_label("Role", exact=True).fill("Engineer")
        s.click("Add application")
        expect(page.get_by_text("Next action and contact")).to_be_visible()
        found = violations(page)
        assert not found, f"tracker: {describe(found)}"

    def test_generated_cv_html_has_no_wcag_violations(self, browser, tmp_path):
        from test_render_cv import experienced

        from careerforge.render.cv import render_cv_html
        from careerforge.render.options import TEMPLATES, RenderOptions

        for template in TEMPLATES:
            f = tmp_path / f"{template}.html"
            f.write_text(render_cv_html(experienced(), RenderOptions(template=template)), encoding="utf-8")
            page = browser.new_page()
            page.goto(f.as_uri())
            results = Axe().run(page, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa"]}})
            found = [
                v for v in results.response["violations"] if v["id"] != "region"
            ]  # a CV page has no site landmarks
            page.close()
            assert not found, f"{template}: {describe(found)}"


def test_the_accessibility_audit_really_detects_problems(browser):
    """Negative control: a page with known WCAG failures must be reported, or the audits above prove nothing."""
    page = browser.new_page()
    page.set_content(
        '<html lang="en"><body><main><h1>Title</h1><img src="x.png"><p style="color:#cccccc;background:#fff">faint</p>'
        '<button></button><input type="text"></main></body></html>'
    )
    ids = {v["id"] for v in violations(page)}
    page.close()
    assert {"image-alt", "color-contrast", "button-name", "label"} <= ids
