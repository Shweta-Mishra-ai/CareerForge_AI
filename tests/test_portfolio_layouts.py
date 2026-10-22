"""Portfolio layouts: three designs (profile, hero, editorial) that must show exactly the same content."""

import re
from datetime import date

import pytest
from bs4 import BeautifulSoup
from pydantic import ValidationError
from test_render_cv import SNEAKY, hostile
from test_render_portfolio import bypass_gate, full_profile

from careerforge.models import Education, Experience, Profile, Project
from careerforge.render.portfolio import LAYOUTS, PortfolioOptions, _initials, _rows, build_portfolio
from careerforge.render.themes import THEMES, TINT_SHARE, contrast_ratio, mix

TODAY = date(2026, 10, 10)
LAYOUT_KEYS = list(LAYOUTS)
THEME_KEYS = list(THEMES)


def build(profile=None, **kw):
    return build_portfolio(profile or full_profile(), PortfolioOptions(**kw), today=TODAY)


def soup(html):
    return BeautifulSoup(html, "html.parser")


def visible_text(html):
    s = soup(html)
    for tag in s(["script", "style", "nav"]):
        tag.decompose()
    return re.sub(r"\s+", " ", s.get_text(" ")).strip()


class TestSameContentEveryLayout:
    @pytest.mark.parametrize("theme", THEME_KEYS)
    def test_every_layout_and_theme_builds(self, theme):
        for layout in LAYOUT_KEYS:
            assert "<h1>" in build(layout=layout, theme=theme).html

    def test_the_words_on_the_page_are_identical_across_layouts(self):
        words = {
            layout: set(re.findall(r"[\w'.+-]{3,}", visible_text(build(layout=layout).html))) for layout in LAYOUT_KEYS
        }
        assert all(w == words["profile"] for w in words.values()), {k: w ^ words["profile"] for k, w in words.items()}

    def test_every_fact_of_the_profile_appears_in_every_layout(self):
        p = full_profile()
        facts = [p.name, p.headline, p.summary, "Finlytics Pvt Ltd", "Mar 2021", "Cut p95 API latency", "NIT Calicut",
                 "AWS Certified Developer", "settle-core", "PostgreSQL", "Hindi", "priya.nair@gmail.com"]  # fmt: skip
        for layout in LAYOUT_KEYS:
            text = visible_text(build(layout=layout).html)
            for fact in facts:
                assert fact in text, (layout, fact)

    def test_the_default_is_the_profile_layout(self):
        assert PortfolioOptions().layout == "profile" and 'class="profile"' in build().html

    def test_an_unknown_layout_is_refused(self):
        with pytest.raises(ValidationError):
            PortfolioOptions(layout="grid")

    def test_every_layout_has_a_label_and_a_description_for_the_picker(self):
        assert all(label and len(text) > 30 for label, text in LAYOUTS.values())


class TestStructure:
    @pytest.mark.parametrize("layout", LAYOUT_KEYS)
    def test_landmarks_are_correct(self, layout):
        s = soup(build(layout=layout).html)
        assert len(s.find_all("h1")) == 1 and len(s.find_all("main")) == 1
        assert s.find("header") and s.find("nav", attrs={"aria-label": "Sections"})
        footer = s.find("footer")
        assert footer and not footer.find_parent("main")  # a footer inside <main> is not the page footer
        assert s.find("a", class_="skip")["href"] == "#main" and s.find(id="main")

    @pytest.mark.parametrize("layout", LAYOUT_KEYS)
    def test_every_nav_link_has_a_target_and_headings_do_not_skip_levels(self, layout):
        s = soup(build(layout=layout).html)
        ids = {t["id"] for t in s.find_all(id=True)}
        for a in s.select("nav a"):
            assert a["href"].lstrip("#") in ids, a
        levels = [int(h.name[1]) for h in s.find_all(re.compile("^h[1-6]$"))]
        assert all(b - a <= 1 for a, b in zip(levels, levels[1:], strict=False)), levels

    @pytest.mark.parametrize("layout", LAYOUT_KEYS)
    def test_the_avatar_is_decorative_and_shows_initials(self, layout):
        avatar = soup(build(layout=layout).html).select_one(".avatar")
        if layout == "editorial":
            assert avatar is None  # the editorial masthead is type only
        else:
            assert avatar["aria-hidden"] == "true" and avatar.get_text() == "PN"

    @pytest.mark.parametrize("layout", LAYOUT_KEYS)
    def test_the_page_is_self_contained(self, layout):
        s = soup(build(layout=layout, theme="auto").html)
        assert [t.get("type") for t in s.find_all("script")] == ["application/ld+json"]
        assert not s.find(["img", "iframe", "object", "embed", "form", "input", "base"])
        css = s.find("style").string
        assert "@import" not in css and "url(" not in css and "@font-face" not in css
        assert [link["href"][:5] for link in s.find_all("link")] == ["data:"]

    @pytest.mark.parametrize("layout", LAYOUT_KEYS)
    def test_print_hides_navigation_and_buttons(self, layout):
        assert "@media print" in soup(build(layout=layout).html).find("style").string


class TestRows:
    def test_short_neighbours_share_a_row_in_pairs(self):
        assert _rows(["about", "projects", "education", "certifications", "languages"], pair=True) == [
            ["about"], ["projects"], ["education", "certifications"], ["languages"],
        ]  # fmt: skip
        assert _rows(["education", "languages"], pair=True) == [["education", "languages"]]

    def test_long_sections_never_pair_and_editorial_never_pairs(self):
        assert _rows(["experience", "skills", "education"], pair=True) == [["experience"], ["skills"], ["education"]]
        assert _rows(["education", "certifications"], pair=False) == [["education"], ["certifications"]]
        assert _rows(["certifications", "projects", "languages"], pair=True) == [
            ["certifications"],
            ["projects"],
            ["languages"],
        ]

    def test_the_page_pairs_education_and_certifications_except_in_the_editorial_layout(self):
        for layout, paired in (("profile", True), ("hero", True), ("editorial", False)):
            s = soup(build(layout=layout).html)
            assert bool(s.select(".pair #education, .pair #certifications")) is paired, layout

    def test_hiding_a_section_leaves_the_other_on_its_own(self):
        s = soup(build(hidden=frozenset({"certifications", "languages"})).html)
        assert not s.select(".pair") and s.find(id="education") and not s.find(id="certifications")
        s = soup(build(hidden=frozenset({"certifications"})).html)  # education now pairs with languages instead
        assert [sec["id"] for sec in s.select(".pair section")] == ["education", "languages"]


class TestPrivacyAndContent:
    @pytest.mark.parametrize("layout", LAYOUT_KEYS)
    def test_the_city_is_not_shown_unless_asked(self, layout):
        assert "Bengaluru" not in build(layout=layout).html
        shown = build(layout=layout, show_location=True).html
        assert "Bengaluru, India" in visible_text(shown)
        assert "Bengaluru" not in soup(shown).find("script").string  # never in the structured data

    @pytest.mark.parametrize("layout", LAYOUT_KEYS)
    def test_the_email_button_follows_the_email_setting(self, layout):
        s = soup(build(layout=layout).html)
        mail = {a["href"] for a in s.select("a.button") if a["href"].startswith("mailto:")}
        assert mail == {"mailto:priya.nair@gmail.com"}
        assert all(a["href"] == "#projects" for a in s.select("a.button") if not a["href"].startswith("mailto:"))
        hidden = soup(build(layout=layout, show_email=False).html)
        assert not [a for a in hidden.select("a") if a["href"].startswith("mailto:")]

    @pytest.mark.parametrize("layout", LAYOUT_KEYS)
    def test_no_summary_means_no_about_but_a_working_page(self, layout):
        p = full_profile().model_copy(update={"summary": ""})
        s = soup(build(p, layout=layout).html)
        assert not s.find(id="about") and s.find(id="experience")

    @pytest.mark.parametrize("layout", LAYOUT_KEYS)
    def test_a_projects_only_profile_builds(self, layout):
        p = Profile(name="Sam Rivera", contact=full_profile().contact, projects=[Project(name="Tool", description="x")])
        s = soup(build(p, layout=layout).html)
        assert s.find(id="projects") and not s.find(id="experience")

    @pytest.mark.parametrize("layout", LAYOUT_KEYS)
    @pytest.mark.parametrize("payload", SNEAKY)
    def test_hostile_text_stays_inert_in_every_layout(self, layout, payload, monkeypatch):
        bypass_gate(monkeypatch)
        s = soup(build(hostile(payload), layout=layout).html)
        assert [t.get("type") for t in s.find_all("script")] == ["application/ld+json"]
        assert not [t.name for t in s.find_all(True) if any(a.lower().startswith("on") for a in t.attrs)]

    def test_initials(self):
        assert [_initials(n) for n in ("Priya Nair", "priya", "Priya Kumari Nair", "", "  ", "李 雷", "-- 99")] == [
            "PN", "P", "PN", "•", "•", "李雷", "•",
        ]  # fmt: skip


class TestTint:
    def test_mix_is_a_straight_blend(self):
        assert mix("#000000", "#ffffff", 0.5) == "#808080" and mix("#ff0000", "#0000ff", 0.0) == "#0000ff"
        assert mix("#ff0000", "#0000ff", 1.0) == "#ff0000"

    @pytest.mark.parametrize("key", THEME_KEYS)
    def test_text_on_tinted_areas_meets_aa_in_every_palette(self, key):
        theme = THEMES[key]
        for palette in (theme, theme.dark) if theme.dark else (theme,):
            assert palette.tint == mix(palette.accent, palette.bg, TINT_SHARE)
            for fg in (palette.text, palette.muted, palette.accent):
                assert contrast_ratio(fg, palette.tint) >= 4.5, (key, palette.key, fg)

    def test_a_custom_accent_that_fails_on_the_tint_is_refused(self):
        from careerforge.render.themes import with_accent

        grey = "#767676"  # passes on white (4.5) but not on a tinted card
        with pytest.raises(ValueError):
            with_accent(THEMES["light"], grey)


class TestExperienceDates:
    def test_dates_sit_in_their_own_element_so_they_never_run_into_the_title(self):
        p = full_profile().model_copy(
            update={
                "experience": [Experience(title="Dev", company="Acme", dates={"start": "2020-01", "end": "2021-01"})]
            }
        )
        job = soup(build(p).html).select_one(".timeline li")
        assert job.select_one(".job-head h3").get_text() == "Dev"
        assert job.select_one(".job-head .when").get_text() == "Jan 2020 – Jan 2021"

    def test_an_entry_without_dates_has_no_empty_date_element(self):
        p = full_profile().model_copy(update={"experience": [Experience(title="Dev", company="Acme")]})
        assert not soup(build(p).html).select(".when")

    def test_education_without_details_renders_a_card(self):
        p = full_profile().model_copy(update={"education": [Education(degree="BSc", institution="Uni")]})
        assert soup(build(p).html).select_one("#education .card h3").get_text() == "BSc"
