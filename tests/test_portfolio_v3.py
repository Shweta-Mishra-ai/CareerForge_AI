"""Portfolio v3: colour presets, hero glow, generated project covers and company badges."""

from datetime import date

import pytest
from bs4 import BeautifulSoup
from pydantic import ValidationError
from test_render_portfolio import browser, full_profile  # noqa: F401  (browser is a fixture)

from careerforge.models import Experience, Profile, Project
from careerforge.render.options import contrast_ratio
from careerforge.render.portfolio import LAYOUTS, PortfolioOptions, build_portfolio
from careerforge.render.portfolio_art import cover_svg, monogram
from careerforge.render.themes import MIN_CONTRAST, PRESETS, THEMES, mix, shift_hue, with_accent, with_preset

TODAY = date(2026, 10, 10)


def build(profile=None, **kw):
    return build_portfolio(profile or full_profile(), PortfolioOptions(**kw), today=TODAY)


class TestPresets:
    @pytest.mark.parametrize("theme", list(THEMES))
    @pytest.mark.parametrize("preset", list(PRESETS))
    def test_every_preset_is_readable_on_every_theme_and_both_pages_of_auto(self, theme, preset):
        t = with_preset(THEMES[theme], preset)
        for palette in (t, t.dark) if t.dark else (t,):
            for fg, bg, what in palette.text_pairs():
                assert contrast_ratio(fg, bg) >= MIN_CONTRAST, f"{preset} on {theme}: {what}"

    def test_auto_gets_the_light_shade_on_the_light_page_and_the_dark_shade_on_the_dark_page(self):
        t = with_preset(THEMES["auto"], "teal")
        assert (t.accent, t.dark.accent) == (PRESETS["teal"][1], PRESETS["teal"][2])
        html = build(theme="auto", preset="teal").html
        assert PRESETS["teal"][1] in html and PRESETS["teal"][2] in html

    def test_a_dark_theme_uses_the_dark_shade(self):
        assert with_preset(THEMES["dark"], "rose").accent == PRESETS["rose"][2]

    def test_unknown_presets_and_combining_with_a_custom_accent_are_refused(self):
        with pytest.raises(ValidationError, match="Unknown colour"):
            PortfolioOptions(preset="neon")
        with pytest.raises(ValueError, match="Unknown colour"):
            with_preset(THEMES["light"], "neon")
        with pytest.raises(ValidationError, match="either a named colour or your own"):
            PortfolioOptions(preset="teal", accent="#1d4ed8")

    def test_the_old_rule_still_holds_for_custom_colours_on_auto(self):
        with pytest.raises(ValueError, match="no single colour is readable"):
            with_accent(THEMES["auto"], "#1d4ed8")

    def test_a_custom_accent_must_also_be_readable_on_the_hero_glow(self):
        # #7c3aed is fine on the plain page (5.7:1) but only 4.47:1 on the glow, where links can sit
        with pytest.raises(ValueError, match="hero glow"):
            with_accent(THEMES["light"], "#7c3aed")


class TestGlow:
    @pytest.mark.parametrize("theme", list(THEMES))
    def test_glow_colours_are_the_accent_blended_into_the_page_and_carry_no_unchecked_text(self, theme):
        t = THEMES[theme]
        assert t.wash == mix(t.accent, t.bg, 0.16) and t.wash2 == mix(t.accent2, t.bg, 0.16)
        names = {what for _, _, what in t.text_pairs()}
        assert {"text on the hero glow", "text on the second hero glow"} <= names

    def test_the_partner_colour_is_a_hue_turn_of_the_accent(self):
        assert shift_hue("#ff0000", 120) == "#00ff00" and shift_hue("#336699", 0) == "#336699"
        assert shift_hue("#808080", 90) == "#808080"  # greys have no hue to turn

    def test_the_stylesheet_exposes_the_glow_in_both_palettes_of_auto(self):
        html = build(theme="auto").html
        t = THEMES["auto"]
        for value in (t.wash, t.wash2, t.dark.wash, t.dark.wash2, t.accent2, t.dark.accent2):
            assert value in html


class TestArt:
    def test_a_cover_is_deterministic_and_depends_on_the_name(self):
        assert cover_svg("Big One") == cover_svg("Big One") == cover_svg("  big one ".strip())
        pictures = {str(cover_svg(f"project {i}")) for i in range(40)}
        assert len(pictures) > 20

    @pytest.mark.parametrize("name", ["a", "Big One", "settle-core", "<script>alert(1)</script>", "", "日本語"])
    def test_a_cover_is_inert_decorative_and_uses_theme_variables_only(self, name):
        svg = BeautifulSoup(str(cover_svg(name)), "html.parser").find("svg")
        assert svg["aria-hidden"] == "true" and not svg.get_text().strip()
        assert {t.name for t in svg.find_all(True)} <= {"rect", "path", "circle"}
        assert not [a for t in svg.find_all(True) for a in t.attrs if a.startswith("on") or "href" in a]
        assert "#" not in str(svg)  # no hard-coded colour: the page's palette paints it

    def test_all_four_patterns_occur(self):
        def kind(name):
            tags = BeautifulSoup(str(cover_svg(name)), "html.parser").find_all(True)
            if any(t.get("fill") == "none" for t in tags):
                return "arcs"
            if any(t.get("transform") for t in tags):
                return "bars"
            return "dots" if sum(t.name == "circle" for t in tags) > 40 else "circles"

        assert {kind(f"p{i}") for i in range(60)} == {"arcs", "bars", "dots", "circles"}

    @pytest.mark.parametrize(
        ("company", "expected"),
        [
            ("Finlytics Pvt Ltd", "F"),
            ("ShipFast Logistics", "SL"),
            ("Acme Corp", "A"),
            ("Pvt Ltd", "PL"),
            ("Tata Consultancy Services", "TC"),
            ("  ", "•"),
            ("123", "•"),
            ("ünïcode GmbH", "Ü"),
        ],
    )
    def test_monograms(self, company, expected):
        assert monogram(company) == expected


class TestPageUsesIt:
    @pytest.mark.parametrize("layout", list(LAYOUTS))
    def test_projects_get_covers_and_jobs_get_badges(self, layout):
        s = BeautifulSoup(build(layout=layout).html, "html.parser")
        assert len(s.select("#projects .cover svg")) == len(full_profile().projects)
        assert [m.get_text() for m in s.select("#experience .mono")] == ["F", "SL"]
        assert all(m["aria-hidden"] == "true" for m in s.select(".mono"))

    @pytest.mark.parametrize("layout", list(LAYOUTS))
    def test_contact_tiles_carry_a_visible_label_and_an_icon(self, layout):
        s = BeautifulSoup(build(layout=layout).html, "html.parser")
        tiles = s.select("#contact a.tile")
        assert [t.find("small").get_text() for t in tiles] == ["Email", "LinkedIn", "GitHub"]
        assert all(t.find("svg", attrs={"aria-hidden": "true"}) for t in tiles)

    def test_a_profile_with_no_company_still_builds_a_badge(self):
        p = Profile(
            name="Sam Rivera",
            contact=full_profile().contact,
            experience=[Experience(title="Freelance developer", bullets=["Built a thing for a client."])],
            projects=[Project(name="Tool")],
        )
        s = BeautifulSoup(build(p).html, "html.parser")
        assert [m.get_text() for m in s.select(".mono")] == ["FD"]

    def test_print_drops_the_decoration(self):
        assert ".cover, .banner { display: none !important; }" in build().html.replace(
            "nav, .skip, .actions, .topbar, ", ""
        )

    def test_motion_is_only_added_when_the_visitor_allows_it(self):
        html = build().html
        assert "prefers-reduced-motion: no-preference" in html and "translateY(-3px)" in html
        assert "scroll-behavior: auto" in html  # reduced-motion still turns smooth scrolling off


class TestInBrowser:
    @pytest.mark.parametrize("layout", list(LAYOUTS))
    @pytest.mark.parametrize("scheme", ["light", "dark"])
    @pytest.mark.parametrize("preset", ["teal", "orange", "slate"])
    def test_presets_pass_axe_in_both_pages_of_the_automatic_theme(self, browser, tmp_path, layout, scheme, preset):  # noqa: F811
        from axe_playwright_python.sync_playwright import Axe

        f = tmp_path / "index.html"
        f.write_text(build(theme="auto", preset=preset, layout=layout).html, encoding="utf-8")
        page = browser.new_page(color_scheme=scheme)
        page.goto(f.as_uri())
        results = Axe().run(
            page, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa", "best-practice"]}}
        )
        page.close()
        assert not results.response["violations"], [
            (v["id"], [n["html"][:80] for n in v["nodes"]]) for v in results.response["violations"]
        ]

    @pytest.mark.parametrize("layout", list(LAYOUTS))
    @pytest.mark.parametrize("width", [320, 390, 768])
    def test_nothing_scrolls_sideways_even_with_a_long_unbroken_address(self, browser, tmp_path, layout, width):  # noqa: F811
        p = full_profile()
        long_mail = "a" * 60 + "@" + "b" * 40 + ".example.org"
        p = p.model_copy(update={"contact": p.contact.model_copy(update={"email": long_mail})})
        f = tmp_path / "index.html"
        f.write_text(build(p, layout=layout, theme="light").html, encoding="utf-8")
        page = browser.new_page(viewport={"width": width, "height": 800})
        page.goto(f.as_uri())
        over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        page.close()
        assert over <= 0, f"{over}px of sideways scroll at {width}px in the {layout} layout"
