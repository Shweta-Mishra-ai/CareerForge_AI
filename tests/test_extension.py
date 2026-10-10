"""Chrome extension library tests, run in real Chromium via Playwright.

Scope: the URL gate and the text-extraction/cleaning LOGIC against a fixture that imitates LinkedIn's structure
(duplicated screen-reader text, UI noise). It cannot prove LinkedIn's live markup still matches the selectors -
that needs a manual check on a real profile.
"""

import glob
import json
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
LIB = Path(__file__).resolve().parent.parent / "chrome_extension" / "lib.js"
pytestmark = pytest.mark.e2e

PAGE = """<html><body><main>
<h1 class="text-heading-xlarge">Priya Nair</h1>
<div class="text-body-medium break-words">Senior Backend Engineer</div>
<span class="text-body-small inline t-black--light break-words">Bengaluru, India</span>
<section><div><h2 class="pvs-header__title"><span aria-hidden="true">About</span><span class="visually-hidden">About</span></h2></div>
<div><span aria-hidden="true">Backend engineer building payment APIs.</span><span class="visually-hidden">Backend engineer building payment APIs.</span><span>…see more</span></div></section>
<section><h2 class="pvs-header__title"><span aria-hidden="true">Experience</span></h2>
<ul><li>Backend Engineer<br>Backend Engineer<br>Finlytics · Full-time<br>Mar 2021 - Present · 5 yrs<br>Cut latency 480ms to 190ms</li>
<li>Software Engineer<br>ShipFast<br>Jul 2018 - Feb 2021</li></ul><div>Show all 4 experiences</div></section>
<section><h2 class="pvs-header__title"><span aria-hidden="true">Education</span></h2><div>NIT Calicut<br>B.Tech Computer Science<br>2014 - 2018</div></section>
<section><h2 class="pvs-header__title"><span aria-hidden="true">Skills</span></h2><div>Python<br>Python<br>12 endorsements<br>Kafka<br>Endorse</div></section>
<section><h2 class="pvs-header__title"><span aria-hidden="true">Licenses &amp; certifications</span></h2><div>AWS Certified Developer<br>Show credential</div></section>
</main></body></html>"""


@pytest.fixture(scope="module")
def page():
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            candidates = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")
            if not candidates:
                pytest.skip("Chromium is not available")
            browser = p.chromium.launch(executable_path=candidates[0])
        pg = browser.new_page()
        pg.set_content(PAGE)
        pg.add_script_tag(path=str(LIB))
        yield pg
        browser.close()


def run(page, expr, arg=None):
    return page.evaluate(expr, arg)


class TestUrlGate:
    @pytest.mark.parametrize("url", ["https://www.linkedin.com/in/priya-nair-demo/", "https://linkedin.com/in/priya",
                                     "https://in.linkedin.com/in/priya-nair?trk=x", "https://www.linkedin.com/in/priya/details/skills/"])  # fmt: skip
    def test_real_profile_urls_accepted(self, page, url):
        assert run(page, "u => CareerForge.isLinkedInProfileUrl(u)", url) is True

    @pytest.mark.parametrize("url", [
        "https://evil.com/?linkedin.com/in/priya",  # the old substring check accepted this
        "https://evil.com/linkedin.com/in/priya", "https://linkedin.com.evil.io/in/priya",
        "https://evil-linkedin.com/in/priya", "https://www.linkedin.com@evil.com/in/priya",
        "http://www.linkedin.com/in/priya", "https://www.linkedin.com/feed/", "https://www.linkedin.com/in/",
        "https://www.linkedin.com/jobs/view/123", "javascript:alert(1)", "not a url", "", "https://linkedin.com/company/x",
    ])  # fmt: skip
    def test_everything_else_rejected(self, page, url):
        assert run(page, "u => CareerForge.isLinkedInProfileUrl(u)", url) is False


class TestExtraction:
    def result(self, page):
        return run(page, "() => CareerForge.extractProfileText(document)")

    def test_sections_are_found_and_cleaned(self, page):
        r = self.result(page)
        t = r["text"]
        assert r["complete"] is True and r["missing"] == []
        assert (
            "Name: Priya Nair" in t and "Headline: Senior Backend Engineer" in t and "Location: Bengaluru, India" in t
        )
        assert "ABOUT:\nBackend engineer building payment APIs." in t  # heading line is not repeated as content
        assert "SKILLS:\nPython\nKafka" in t
        assert "Cut latency 480ms to 190ms" in t and "NIT Calicut" in t and "AWS Certified Developer" in t

    def test_duplicated_screen_reader_text_and_ui_noise_are_removed(self, page):
        t = self.result(page)["text"]
        assert t.count("Backend engineer building payment APIs.") == 1
        assert "Backend Engineer\nBackend Engineer" not in t and "Python\nPython" not in t
        for noise in ("Show all 4 experiences", "…see more", "Endorse", "12 endorsements", "Show credential"):
            assert noise not in t

    def test_header_does_not_claim_the_content_is_verified(self, page):
        t = self.result(page)["text"]
        assert "VERIFIED" not in t.upper() and t.startswith("[LinkedIn profile text copied from the page")

    def test_unknown_markup_falls_back_to_page_text_and_says_so(self, page):
        r = page.evaluate("""() => {
            const doc = new DOMParser().parseFromString('<main><h1>Priya Nair</h1><div>Some redesigned layout text about Python and Go.</div></main>', 'text/html');
            return CareerForge.extractProfileText(doc); }""")
        assert r["complete"] is False and r["missing"] == ["EXPERIENCE", "EDUCATION", "SKILLS"]
        assert "PAGE TEXT (sections could not be identified)" in r["text"] and "redesigned layout" in r["text"]

    def test_partial_pages_report_exactly_what_is_missing(self, page):
        r = page.evaluate("""() => {
            const doc = new DOMParser().parseFromString('<main><h1>P</h1><section><h2 class="pvs-header__title"><span aria-hidden="true">Experience</span></h2><div>Dev at Acme</div></section></main>', 'text/html');
            return CareerForge.extractProfileText(doc); }""")
        assert r["missing"] == ["EDUCATION", "SKILLS"] and r["complete"] is False

    def test_output_is_plain_text_not_html(self, page):
        r = page.evaluate("""() => {
            const doc = new DOMParser().parseFromString('<main><h1>&lt;img src=x onerror=alert(1)&gt;</h1></main>', 'text/html');
            return CareerForge.extractProfileText(doc).text; }""")
        assert "<img src=x onerror=alert(1)>" in r  # kept as inert text; the app escapes it when rendering


def test_manifest_is_least_privilege_and_valid():
    manifest = json.loads((LIB.parent / "manifest.json").read_text())
    assert manifest["manifest_version"] == 3
    assert set(manifest["permissions"]) == {"activeTab", "scripting"}
    assert "host_permissions" not in manifest and "content_scripts" not in manifest  # nothing runs unless clicked
    assert "VERIFIED" not in manifest["description"].upper()


def test_popup_only_reports_success_after_the_copy_resolved():
    src = (LIB.parent / "popup.js").read_text()
    assert src.index("await navigator.clipboard.writeText") < src.index("Copied ")
    assert "catch (copyError)" in src and "never claim success" in src.lower()
