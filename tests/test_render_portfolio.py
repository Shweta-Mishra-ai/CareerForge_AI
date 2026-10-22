"""Portfolio website: safety, accessibility, honesty (nothing invented) and the deploy bundle."""

import glob
import io
import json
import re
import zipfile
from datetime import date

import pytest
from bs4 import BeautifulSoup
from markupsafe import escape
from pydantic import ValidationError
from test_grounding import faithful_standard
from test_render_cv import FULL, SNEAKY, fresher, hostile

from careerforge.models import Certification, Contact, Education, Experience, Profile, Project
from careerforge.readiness import NotReady, Readiness
from careerforge.render import portfolio as pf
from careerforge.render.options import contrast_ratio
from careerforge.render.portfolio import PortfolioOptions, build_portfolio
from careerforge.render.themes import MIN_CONTRAST, THEMES, with_accent

TODAY = date(2026, 10, 10)
THEME_KEYS = list(THEMES)


def full_profile() -> Profile:
    p = faithful_standard()
    return p.model_copy(
        update={
            "contact": p.contact.model_copy(update={"email": "priya.nair@gmail.com"}),
            "languages": ["English", "Hindi"],
            "projects": [
                Project(
                    name="settle-core",
                    description="Open-source settlement engine.",
                    tech=["Go", "Kafka"],
                    url="https://github.com/priya-demo/settle-core",
                    stars=42,
                    bullets=["Handles retries and idempotency."],
                ),
                Project(name="no-link-project", description="A project without a link."),
            ],
        }
    )


def build(p=None, **kw) -> str:
    return build_portfolio(p or full_profile(), PortfolioOptions(**kw), today=TODAY).html


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def bypass_gate(monkeypatch):
    monkeypatch.setattr(pf, "blockers", lambda *a, **k: Readiness(()))


# ── themes & contrast ───────────────────────────────────────────────────────


class TestThemes:
    @pytest.mark.parametrize("key", THEME_KEYS)
    def test_every_text_colour_pair_meets_wcag_aa(self, key):
        for fg, bg, what in THEMES[key].text_pairs():
            assert contrast_ratio(fg, bg) >= MIN_CONTRAST, f"{key}: {what} {fg} on {bg}"

    @pytest.mark.parametrize("key", THEME_KEYS)
    def test_the_stylesheet_really_uses_the_palette_that_was_checked(self, key):
        t = THEMES[key]
        html = build(theme=key)
        for token in (t.bg, t.surface, t.text, t.muted, t.accent, t.accent_text, t.border):
            assert token in html

    def test_a_hard_to_read_accent_is_rejected_with_the_numbers(self):
        with pytest.raises(ValueError, match="hard to read on the Light theme"):
            with_accent(THEMES["light"], "#ffff00")
        with pytest.raises(ValueError, match="hard to read on the Dark theme"):
            with_accent(THEMES["dark"], "#101010")

    def test_a_good_accent_is_applied_and_text_on_it_is_readable(self):
        t = with_accent(THEMES["light"], "#7a1fa2")
        assert t.accent == "#7a1fa2" and contrast_ratio(t.accent_text, t.accent) >= MIN_CONTRAST
        assert "--accent: #7a1fa2" in build(theme="light", accent="#7a1fa2")

    def test_unreadable_custom_accent_blocks_the_build(self):
        with pytest.raises(ValueError):
            build(theme="light", accent="#ffff00")

    @pytest.mark.parametrize("bad", ["red", "#fff", "#1f4e79;}body{display:none", "url(x)"])
    def test_accent_cannot_carry_css(self, bad):
        with pytest.raises(ValidationError):
            PortfolioOptions(accent=bad)

    def test_unknown_theme_and_section_are_rejected(self):
        with pytest.raises(ValidationError):
            PortfolioOptions(theme="neon")
        with pytest.raises(ValidationError):
            PortfolioOptions(hidden=frozenset({"blog"}))


# ── self-contained & safe by construction ──────────────────────────────────


@pytest.mark.parametrize("theme", THEME_KEYS)
class TestSelfContained:
    def test_no_executable_script_no_external_resource_no_import(self, theme):
        html = build(theme=theme)
        s = soup(html)
        assert [t.get("type") for t in s.find_all("script")] == ["application/ld+json"]
        assert not s.find(["img", "iframe", "object", "embed", "form", "input", "base"])
        # the only <link> is the inline icon (a data: URI: no request is made)
        links = s.find_all("link")
        assert [link["rel"] for link in links] == [["icon"]] and links[0]["href"].startswith("data:image/svg+xml,")
        assert not [t.name for t in s.find_all(True) if any(a.lower().startswith("on") for a in t.attrs)]
        css = s.find("style").string
        assert "@import" not in css and "url(" not in css and "@font-face" not in css
        assert not s.find(attrs={"src": True})

    def test_every_link_is_an_anchor_a_mailto_or_a_profile_url(self, theme):
        hrefs = [a["href"] for a in soup(build(theme=theme)).find_all("a")]
        assert hrefs
        for h in hrefs:
            assert h.startswith(("#", "mailto:", "https://linkedin.com/", "https://github.com/")), h

    def test_csp_blocks_everything_except_inline_css(self, theme):
        meta = soup(build(theme=theme)).find("meta", attrs={"http-equiv": "Content-Security-Policy"})
        csp = dict(d.strip().split(" ", 1) for d in meta["content"].split(";"))
        assert csp["default-src"] == "'none'" and csp["style-src"] == "'unsafe-inline'"
        assert csp["base-uri"] == "'none'" and csp["form-action"] == "'none'"
        assert "script-src" not in csp  # falls back to default-src 'none': nothing executes

    def test_every_in_page_link_target_exists(self, theme):
        s = soup(build(theme=theme))
        ids = {t["id"] for t in s.find_all(id=True)}
        for a in s.find_all("a", href=re.compile("^#")):
            assert a["href"][1:] in ids
        for t in s.find_all(attrs={"aria-labelledby": True}):
            assert t["aria-labelledby"] in ids

    def test_valid_document_basics(self, theme):
        s = soup(build(theme=theme))
        assert s.html["lang"] == "en" and s.find("meta", attrs={"name": "viewport"})
        assert len(s.find_all("h1")) == 1 and s.find("header") and s.find("main", id="main") and s.find("footer")
        assert s.find("a", class_="skip")["href"] == "#main"
        assert len({t["id"] for t in s.find_all(id=True)}) == len(s.find_all(id=True))  # ids are unique

    def test_heading_levels_never_skip(self, theme):
        levels = [int(h.name[1]) for h in soup(build(theme=theme)).find_all(re.compile("^h[1-6]$"))]
        assert levels[0] == 1
        assert all(b - a <= 1 for a, b in zip(levels, levels[1:], strict=False))


# ── hostile content ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("theme", THEME_KEYS)
@pytest.mark.parametrize("payload", SNEAKY)
def test_sneaky_text_is_escaped(theme, payload):
    html = build(hostile(payload), theme=theme)
    s = soup(html)
    assert str(escape(payload)) in html
    assert payload in s.find("main").get_text()
    assert len(s.find_all("style")) == 1 and len(s.find_all("script")) == 1
    assert not [t.name for t in s.find_all(True) if any(a.lower().startswith("on") for a in t.attrs)]


@pytest.mark.parametrize("theme", THEME_KEYS)
@pytest.mark.parametrize("payload", FULL)
def test_full_markup_is_inert_even_if_the_gate_were_bypassed(theme, payload, monkeypatch):
    bypass_gate(monkeypatch)
    html = build(hostile(payload), theme=theme)
    s = soup(html)
    assert [t.get("type") for t in s.find_all("script")] == ["application/ld+json"]
    assert not s.find(["img", "iframe", "object", "base", "foreignobject", "use", "image"])
    assert_only_our_own_inert_svgs(s)
    assert [link["rel"] for link in s.find_all("link")] == [["icon"]] and s.find("link")["href"].startswith("data:")
    assert not [t.name for t in s.find_all(True) if any(a.lower().startswith("on") for a in t.attrs)]
    assert payload in s.find("main").get_text()


@pytest.mark.parametrize("payload", FULL)
def test_gate_refuses_full_markup(payload):
    with pytest.raises(NotReady):
        build(hostile(payload))


def test_json_ld_cannot_be_broken_out_of(monkeypatch):
    bypass_gate(monkeypatch)
    evil = 'Eve</script><script>window.__pwned=1</script> "x"  '
    p = hostile("fine").model_copy(update={"name": evil, "headline": evil})
    html = build(p)
    s = soup(html)
    assert len(s.find_all("script")) == 1
    data = json.loads(s.find("script").string)
    assert data["name"] == evil and data["@type"] == "Person"
    assert "</script><script>" not in html


def test_site_url_must_be_http_or_https():
    for bad in ("javascript:alert(1)", "data:text/html,x", 'https://a.com/"><script>'):
        with pytest.raises(ValueError):
            PortfolioOptions(site_url=bad)
    assert PortfolioOptions(site_url="priya.dev").site_url == "https://priya.dev"


# ── honesty: only the user's content and computed facts ────────────────────


def assert_only_our_own_inert_svgs(s) -> None:
    """The page draws its own icons and cover art as inline SVG. Allow exactly that: decorative (aria-hidden), made of
    plain shapes, with no scripting, no links and no external references, so injected markup cannot hide among them."""
    for svg in s.find_all("svg"):
        assert svg.get("aria-hidden") == "true", "an svg that this page did not draw"
        assert {t.name for t in svg.find_all(True)} <= {"rect", "path", "circle"}
        for tag in [svg, *svg.find_all(True)]:
            assert not [a for a in tag.attrs if a.lower().startswith("on") or "href" in a.lower()]


def text_nodes(html: str) -> list[str]:
    s = soup(html)
    main = s.find("main")
    return [t.strip() for t in main.find_all(string=True) if t.strip()]


class TestNothingIsInvented:
    def test_sparse_profile_page_contains_exactly_its_own_text_plus_labels(self):
        p = Profile(
            name="Sam Rivera",
            contact=Contact(email="sam.rivera@gmail.com"),
            projects=[Project(name="Tiny Tool", description="Does one thing.")],
        )
        s = soup(build(p))
        assert text_nodes(build(p)) == [
            "Projects", "Tiny Tool", "Does one thing.", "Contact", "Email", "sam.rivera@gmail.com",
        ]  # fmt: skip
        assert s.find("h1").get_text() == "Sam Rivera" and s.find("p", class_="headline") is None

    def test_no_summary_means_no_about_section_and_a_warning(self):
        p = full_profile().model_copy(update={"summary": ""})
        result = build_portfolio(p, today=TODAY)
        s = soup(result.html)
        assert s.find(id="about") is None and "About" not in [a.get_text() for a in s.select("nav a")]
        assert any("About section is left out" in w for w in result.warnings)

    def test_description_meta_comes_from_the_summary_or_headline_only(self):
        s = soup(build())
        assert s.find("meta", attrs={"name": "description"})["content"] == full_profile().summary
        bare = full_profile().model_copy(update={"summary": ""})
        assert (
            soup(build(bare)).find("meta", attrs={"name": "description"})["content"]
            == "Priya Nair - Senior Backend Engineer"
        )
        nothing = Profile(
            name="Sam Rivera", contact=Contact(email="sam@gmail.com"), education=[Education(degree="BSc")]
        )
        assert soup(build(nothing)).find("meta", attrs={"name": "description"}) is None

    def test_stats_are_computed_from_the_profile(self):
        stats = [(li.strong.get_text(), li.span.get_text()) for li in soup(build()).select(".stats li")]
        assert stats == [("8", "years of experience"), ("2", "projects"), ("42", "GitHub stars")]

    def test_years_are_rounded_down_never_up(self):
        # 2018-12 .. 2026-07 is 7 years 8 months: the page must not claim 8
        p = full_profile().model_copy(
            update={"experience": [Experience(title="Dev", company="A", dates={"start": "2018-12", "end": "2026-07"})]}
        )
        stats = [(li.strong.get_text(), li.span.get_text()) for li in soup(build(p)).select(".stats li")]
        assert stats[0] == ("7", "years of experience")

    def test_stats_for_a_fresher_show_no_years_and_no_zero_values(self):
        stats = [(li.strong.get_text(), li.span.get_text()) for li in soup(build(fresher())).select(".stats li")]
        assert stats == [("1", "project")]

    def test_no_stats_at_all_when_nothing_to_count_or_when_switched_off(self):
        p = Profile(name="Sam Rivera", contact=Contact(email="sam@gmail.com"), education=[Education(degree="BSc")])
        assert soup(build(p)).find(class_="stats") is None
        assert soup(build(show_stats=False)).find(class_="stats") is None

    def test_singular_labels(self):
        p = full_profile().model_copy(
            update={
                "experience": [Experience(title="Dev", company="A", dates={"start": "2025-09", "end": "2026-10"})],
                "projects": [Project(name="p", stars=1)],
            }
        )
        labels = [li.span.get_text() for li in soup(build(p)).select(".stats li")]
        assert labels == ["year of experience", "project", "GitHub star"]

    def test_unconfirmed_ai_items_are_not_published(self):
        ghost = Experience(title="Wizard", company="FakeCo", origin="suggested", bullets=["Conjured revenue"])
        cert = Certification(name="Fake Cert", origin="suggested")
        p = full_profile().model_copy(
            update={"experience": [ghost, *full_profile().experience], "certifications": [cert]}
        )
        html = build(p)
        assert "FakeCo" not in html and "Fake Cert" not in html and "Finlytics" in html

    def test_section_order_and_content_match_the_profile(self):
        s = soup(build())
        assert [h.get_text() for h in s.select("main h2")] == [
            "About", "Projects", "Experience", "Skills", "Education", "Certifications", "Languages", "Contact",
        ]  # fmt: skip
        assert [h.get_text() for h in s.select("#projects h3")] == ["settle-core", "no-link-project"]
        assert [a.get_text() for a in s.select("#projects h3 a")] == ["settle-core"]  # only linked when a URL exists
        assert s.select_one("#projects .meta").get_text().strip() == "42 stars on GitHub"
        assert [li.get_text() for li in s.select("#projects .chips li")] == ["Go", "Kafka"]
        assert len(s.select("#experience .timeline > li")) == 2
        assert s.select_one("#languages p").get_text() == "English, Hindi"

    def test_hidden_sections_are_left_out_of_page_and_navigation(self):
        s = soup(build(hidden=frozenset({"education", "contact"})))
        assert s.find(id="education") is None and s.find(id="contact") is None
        assert "Education" not in [a.get_text() for a in s.select("nav a")]
        assert "Contact" not in [a.get_text() for a in s.select("nav a")]

    def test_empty_portfolio_is_refused(self):
        with pytest.raises(NotReady):
            build(Profile(name="Sam Rivera", contact=Contact(email="sam@gmail.com")))


# ── privacy defaults ────────────────────────────────────────────────────────


class TestPrivacy:
    def test_phone_is_off_by_default_and_opt_in(self):
        assert "98765" not in build()
        assert "+91 98765 43210" in build(show_phone=True) and "tel:+919876543210" in build(show_phone=True)

    def test_email_can_be_hidden(self):
        html = build(show_email=False)
        assert "priya.nair@gmail.com" not in html and "mailto:" not in html

    def test_a_sample_email_only_matters_when_it_would_be_shown(self):
        sample = faithful_standard()  # example.com address
        with pytest.raises(NotReady, match="sample email"):
            build_portfolio(sample, today=TODAY)
        assert "example.com" not in build_portfolio(sample, PortfolioOptions(show_email=False), today=TODAY).html

    def test_github_only_profile_without_any_email_can_publish(self):
        p = Profile(name="Sam Rivera", contact=Contact(github="github.com/sam"), projects=[Project(name="Tool")])
        html = build(p)
        assert "mailto:" not in html and "github.com/sam" in html

    def test_name_is_still_required(self):
        with pytest.raises(NotReady, match="real full name"):
            build(Profile(contact=Contact(email="a@gmail.com"), projects=[Project(name="Tool")]))

    def test_json_ld_only_contains_published_facts(self):
        data = json.loads(soup(build()).find("script").string)
        assert set(data) == {
            "@context", "@type", "name", "jobTitle", "description", "sameAs", "knowsAbout", "worksFor", "alumniOf",
        }  # fmt: skip
        assert "email" not in data and "telephone" not in data
        assert data["sameAs"] == ["https://linkedin.com/in/priya-nair-demo", "https://github.com/priya-demo"]
        assert data["knowsAbout"][:3] == ["Python", "Go", "PostgreSQL"] and len(data["knowsAbout"]) <= 20
        assert data["worksFor"]["name"] == "Finlytics Pvt Ltd"  # the role marked current, not the earlier one
        assert data["alumniOf"] == [{"@type": "EducationalOrganization", "name": "NIT Calicut"}]


# ── SEO ─────────────────────────────────────────────────────────────────────


class TestSeo:
    def test_title_description_and_open_graph(self):
        s = soup(build())
        assert s.title.get_text() == "Priya Nair - Senior Backend Engineer"
        assert s.find("meta", property="og:title")["content"] == s.title.get_text()
        assert (
            s.find("meta", property="og:description")["content"]
            == s.find("meta", attrs={"name": "description"})["content"]
        )
        assert s.find("meta", attrs={"name": "twitter:card"})["content"] == "summary"
        assert s.find("meta", property="og:image") is None  # no image is invented

    def test_canonical_only_when_the_address_is_known(self):
        assert soup(build()).find("link", rel="canonical") is None
        s = soup(build(site_url="https://priya.dev/"))
        assert s.find("link", rel="canonical")["href"] == "https://priya.dev/"
        assert s.find("meta", property="og:url")["content"] == "https://priya.dev/"

    def test_long_descriptions_are_cut_at_a_word_boundary(self):
        p = full_profile().model_copy(update={"summary": "Backend engineer " * 40})
        content = soup(build(p)).find("meta", attrs={"name": "description"})["content"]
        assert len(content) <= 155 and content.endswith("…") and not content[:-1].endswith(" ")


# ── bundle ──────────────────────────────────────────────────────────────────


class TestBundle:
    def result(self, **kw):
        return build_portfolio(full_profile(), PortfolioOptions(**kw), today=TODAY)

    def test_zip_contents_and_html_identity(self):
        r = self.result()
        with zipfile.ZipFile(io.BytesIO(r.zip_bytes())) as z:
            assert z.testzip() is None
            assert sorted(z.namelist()) == [".nojekyll", "404.html", "README.md", "index.html", "robots.txt"]
            assert z.read("index.html").decode() == r.html and z.read(".nojekyll") == b""

    def test_zip_is_deterministic(self):
        assert self.result().zip_bytes() == self.result().zip_bytes()

    def test_readme_matches_the_options_and_profile(self):
        readme = self.result().readme
        assert "priya-demo.github.io" in readme and "your email address" in readme and "phone" not in readme
        assert "no email address" in self.result(show_email=False).readme
        assert "your phone number" in self.result(show_phone=True).readme
        assert "https://priya.dev" in self.result(site_url="priya.dev").readme

    def test_readme_without_a_github_account_uses_a_placeholder_not_a_guess(self):
        p = Profile(name="Sam Rivera", contact=Contact(email="sam@gmail.com"), projects=[Project(name="Tool")])
        assert "your-username.github.io" in build_portfolio(p, today=TODAY).readme

    def test_html_is_small_enough_to_host_anywhere(self):
        assert len(self.result().html.encode()) < 60_000


# ── real browser: accessibility & layout ────────────────────────────────────


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            candidates = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")
            if not candidates:
                pytest.skip("no Chromium available")
            b = p.chromium.launch(executable_path=candidates[0])
        yield b
        b.close()


@pytest.mark.e2e
@pytest.mark.parametrize("theme", THEME_KEYS)
class TestInBrowser:
    def page(self, browser, tmp_path, html, width=1100):
        f = tmp_path / "index.html"
        f.write_text(html, encoding="utf-8")
        pg = browser.new_page(viewport={"width": width, "height": 900})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type in ("error", "warning") else None)
        pg.goto(f.as_uri())
        return pg, errors

    @pytest.mark.parametrize("width", [320, 768, 1440])
    def test_no_horizontal_scroll_and_no_console_noise(self, browser, tmp_path, theme, width):
        pg, errors = self.page(browser, tmp_path, build(theme=theme), width)
        assert pg.evaluate("document.documentElement.scrollWidth") <= width
        assert errors == []

    def test_skip_link_is_first_focusable_and_becomes_visible(self, browser, tmp_path, theme):
        pg, _ = self.page(browser, tmp_path, build(theme=theme))
        pg.keyboard.press("Tab")
        assert pg.evaluate("document.activeElement.className") == "skip"
        assert pg.evaluate("document.activeElement.getBoundingClientRect().top") >= 0
        pg.keyboard.press("Enter")
        assert pg.evaluate("location.hash") == "#main"

    def test_every_focusable_element_has_a_visible_focus_style(self, browser, tmp_path, theme):
        pg, _ = self.page(browser, tmp_path, build(theme=theme))
        count = pg.evaluate("document.querySelectorAll('a[href]').length")
        for _ in range(count):
            pg.keyboard.press("Tab")
            outline = pg.evaluate("getComputedStyle(document.activeElement).outlineStyle")
            width = pg.evaluate("parseFloat(getComputedStyle(document.activeElement).outlineWidth)")
            assert outline != "none" and width >= 2

    def test_computed_text_colours_meet_contrast_on_the_real_rendered_page(self, browser, tmp_path, theme):
        pg, _ = self.page(browser, tmp_path, build(theme=theme))
        pairs = pg.evaluate(
            """() => [...document.querySelectorAll('main *, header *, footer *')]
              .filter(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()))
              .map(e => {
                let bg = null, n = e;
                while (n && !bg) {
                  const c = getComputedStyle(n).backgroundColor;
                  if (c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') bg = c;
                  n = n.parentElement;
                }
                return [getComputedStyle(e).color, bg || getComputedStyle(document.body).backgroundColor, e.tagName];
              })"""
        )
        assert len(pairs) > 20

        def rgb(s):
            r, g, b = (int(v) for v in re.findall(r"\d+", s)[:3])
            return f"#{r:02x}{g:02x}{b:02x}"

        worst = min(contrast_ratio(rgb(fg), rgb(bg)) for fg, bg, _ in pairs)
        assert worst >= MIN_CONTRAST

    def test_hostile_markup_executes_nothing_in_a_real_browser(self, browser, tmp_path, theme, monkeypatch):
        bypass_gate(monkeypatch)
        payload = (
            '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>"><svg onload="window.__pwned=1">'
        )
        pg, errors = self.page(browser, tmp_path, build(hostile(payload), theme=theme))
        pg.wait_for_timeout(200)
        assert (
            pg.evaluate("window.__pwned") is None
            and pg.evaluate("document.querySelectorAll('img, svg:not([aria-hidden=true])').length") == 0
        )
        assert errors == []

    def test_csp_really_blocks_a_script_that_got_through(self, browser, tmp_path, theme):
        """Defence in depth: even if markup escaped, the page's own CSP forbids execution."""
        html = build(theme=theme).replace("</body>", "<script>window.__ran=1</script></body>")
        pg, _ = self.page(browser, tmp_path, html)
        assert pg.evaluate("window.__ran") is None

    def test_print_view_hides_navigation(self, browser, tmp_path, theme):
        pg, _ = self.page(browser, tmp_path, build(theme=theme))
        pg.emulate_media(media="print")
        assert pg.evaluate("getComputedStyle(document.querySelector('header nav')).display") == "none"
