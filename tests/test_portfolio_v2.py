"""Portfolio v2: automatic light/dark, featured case studies, the CV download, and the files a real site needs."""

import io
import json
import zipfile
from datetime import date
from xml.etree import ElementTree

import pytest
from test_render_portfolio import bypass_gate, full_profile, soup  # noqa: F401

from careerforge.models import Contact, Profile, Project
from careerforge.render.options import contrast_ratio
from careerforge.render.portfolio import PortfolioOptions, build_portfolio
from careerforge.render.themes import MIN_CONTRAST, THEMES, with_accent

TODAY = date(2026, 10, 10)
PDF = b"%PDF-1.7 fake but opaque bytes"


def make(profile=None, cv=None, **kw):
    return build_portfolio(profile or full_profile(), PortfolioOptions(**kw), today=TODAY, cv_pdf=cv)


class TestAutoTheme:
    def test_both_palettes_meet_aa_for_every_text_pair(self):
        auto = THEMES["auto"]
        assert auto.dark is not None and auto.dark.key == "dark"
        for palette in (auto, auto.dark):
            for fg, bg, what in palette.text_pairs():
                assert contrast_ratio(fg, bg) >= MIN_CONTRAST, (palette.key, what)
        assert auto.worst_contrast() >= MIN_CONTRAST

    def test_the_page_follows_the_visitors_device_with_a_media_query(self):
        html = make(theme="auto").html
        css = soup(html).find("style").string
        assert "@media (prefers-color-scheme: dark)" in css and THEMES["dark"].bg in css and THEMES["light"].bg in css
        assert soup(html).find("meta", attrs={"name": "color-scheme"})["content"] == "light dark"
        themed = soup(html).find_all("meta", attrs={"name": "theme-color"})
        assert [m["media"] for m in themed] == ["(prefers-color-scheme: light)", "(prefers-color-scheme: dark)"]

    def test_a_single_theme_has_no_media_query_and_one_theme_colour(self):
        s = soup(make(theme="light").html)
        assert "prefers-color-scheme" not in s.find("style").string
        assert [m.get("media") for m in s.find_all("meta", attrs={"name": "theme-color"})] == [None]

    def test_a_custom_accent_is_refused_because_no_colour_is_readable_on_both_pages(self):
        steps = range(0, 256, 51)  # 216 colours: a coarse proof that the refusal is not just about one unlucky colour
        for r in steps:
            for g in steps:
                for b in steps:
                    with pytest.raises(ValueError, match="no single colour"):
                        with_accent(THEMES["auto"], f"#{r:02x}{g:02x}{b:02x}")

    def test_the_same_accent_is_fine_on_a_single_theme(self):
        assert with_accent(THEMES["light"], "#7c3aed").accent == "#7c3aed"

    def test_the_page_builder_reports_the_refusal(self):
        with pytest.raises(ValueError, match="Choose Light, Dark or Minimal"):
            make(theme="auto", accent="#7c3aed")

    def test_auto_is_offered_as_a_choice(self):
        assert PortfolioOptions(theme="auto").theme == "auto"


class TestProjects:
    def profile(self):
        p = full_profile()
        projects = [
            Project(name="Plain", description="Ordinary.", url="https://github.com/priya-demo/plain"),
            Project(
                name="Big One", description="The flagship.", bullets=["Cut costs by 30%", "Served 2M users"],
                tech=["Go"], url="https://github.com/priya-demo/big", demo_url="https://big.example.com", featured=True,
            ),
            Project(name="Demo Only", description="Has a demo.", demo_url="https://demo.example.com/x"),
        ]  # fmt: skip
        return p.model_copy(update={"projects": projects})

    def test_featured_projects_are_larger_case_studies_shown_first(self):
        s = soup(make(self.profile()).html)
        cases = s.select("article.case")
        assert [c.h3.get_text() for c in cases] == ["Big One"]
        assert "Case study" in cases[0].get_text() and "Served 2M users" in cases[0].get_text()
        assert [c.h3.get_text() for c in s.select("article.card")][:2] == ["Plain", "Demo Only"]
        assert s.find("h3", string="Featured") and s.find("h3", string="More projects")

    def test_without_featured_projects_nothing_changes_in_the_layout(self):
        p = self.profile().model_copy(update={"projects": [Project(name="Plain", description="x")]})
        s = soup(make(p).html)
        assert not s.select("article.case") and not s.find("h3", string="Featured") and s.select("article.card")

    def test_demo_and_source_links_are_real_anchors(self):
        s = soup(make(self.profile()).html)
        case = s.select_one("article.case")
        assert [(a.get_text(), a["href"]) for a in case.select("p.links a")] == [
            ("Source", "https://github.com/priya-demo/big"),
            ("Live demo", "https://big.example.com"),
        ]
        demo_only = next(c for c in s.select("article.card") if c.h3.get_text() == "Demo Only")
        assert [(a.get_text(), a["href"]) for a in demo_only.select("p.links a")] == [
            ("Live demo", "https://demo.example.com/x")
        ]

    def test_only_the_user_can_feature_a_project_and_bad_demo_links_are_refused(self):
        assert Project(name="x").featured is False and Project(name="x").demo_url == ""
        with pytest.raises(ValueError):
            Project(name="x", demo_url="javascript:alert(1)")

    def test_old_profile_files_without_the_new_fields_still_load(self):
        data = json.loads(full_profile().to_json())
        for pr in data["profile"]["projects"] if "profile" in data else data["projects"]:
            pr.pop("demo_url", None), pr.pop("featured", None)
        assert Profile.from_json(json.dumps(data)).projects[0].featured is False

    def test_hostile_project_text_stays_inert_inside_a_case_study(self, monkeypatch):
        bypass_gate(monkeypatch)
        p = self.profile().model_copy(
            update={
                "projects": [Project(name='<img src=x onerror="1">', description="<script>1</script>", featured=True)]
            }
        )
        s = soup(make(p).html)
        assert not s.find("img") and [t.get("type") for t in s.find_all("script")] == ["application/ld+json"]


class TestCv:
    def test_the_cv_is_linked_and_shipped_when_asked(self):
        r = make(cv=PDF, include_cv=True)
        link = soup(r.html).select_one("a[download]")
        assert link["href"] == "Priya_Nair_CV.pdf" and link.has_attr("download")
        assert r.files()["Priya_Nair_CV.pdf"] == PDF
        with zipfile.ZipFile(io.BytesIO(r.zip_bytes())) as z:
            assert z.read("Priya_Nair_CV.pdf") == PDF

    def test_no_link_and_no_file_unless_asked(self):
        r = make(cv=PDF)
        assert not soup(r.html).select("a[download]") and "Priya_Nair_CV.pdf" not in r.files()

    def test_asking_without_a_pdf_warns_and_never_leaves_a_dead_link(self):
        r = make(include_cv=True)
        assert not soup(r.html).select("a[download]") and any("CV PDF could not be made" in w for w in r.warnings)

    def test_the_readme_mentions_the_cv_file(self):
        assert "Priya_Nair_CV.pdf" in make(cv=PDF, include_cv=True).readme
        assert "Priya_Nair_CV.pdf" not in make().readme


class TestSiteFiles:
    def test_default_bundle(self):
        r = make()
        assert sorted(r.files()) == [".nojekyll", "404.html", "README.md", "index.html", "robots.txt"]
        assert r.files()["robots.txt"] == b"User-agent: *\nAllow: /\n"

    def test_site_address_adds_a_sitemap_and_points_robots_at_it(self):
        r = make(site_url="https://jane.example.com/")
        robots = r.files()["robots.txt"].decode()
        assert "Allow: /" in robots and "Sitemap: https://jane.example.com/sitemap.xml" in robots
        root = ElementTree.fromstring(r.files()["sitemap.xml"])
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        assert root.find("s:url/s:loc", ns).text == "https://jane.example.com/"
        assert root.find("s:url/s:lastmod", ns).text == "2026-10-10"

    def test_noindex_blocks_crawlers_in_both_places_and_drops_the_sitemap(self):
        r = make(noindex=True, site_url="https://jane.example.com/")
        assert r.files()["robots.txt"] == b"User-agent: *\nDisallow: /\n" and "sitemap.xml" not in r.files()
        assert soup(r.html).find("meta", attrs={"name": "robots"})["content"] == "noindex"
        assert "NOT to list the page" in r.readme
        assert not soup(make().html).find("meta", attrs={"name": "robots"})

    def test_custom_domain_writes_cname_and_sets_the_canonical_address(self):
        r = make(custom_domain="Jane.Dev")
        assert r.files()["CNAME"] == b"jane.dev\n"
        assert soup(r.html).find("link", rel="canonical")["href"] == "https://jane.dev/"
        assert "sitemap.xml" in r.files() and "DNS" in r.readme

    def test_a_different_site_address_and_domain_warn(self):
        r = make(custom_domain="jane.dev", site_url="https://other.example.com/")
        assert any("different" in w for w in r.warnings)
        assert not any("different" in w for w in make(custom_domain="jane.dev").warnings)

    @pytest.mark.parametrize(
        "bad",
        [
            "https://jane.dev",
            "jane.dev/path",
            "jane",
            "-x.dev",
            "a b.dev",
            "jane.dev.",
            "x" * 300 + ".dev",
            "jane_x.dev",
        ],
    )
    def test_bad_domains_are_refused(self, bad):
        with pytest.raises(ValueError):
            PortfolioOptions(custom_domain=bad)

    @pytest.mark.parametrize("good", ["jane.dev", "www.jane-doe.co.uk", "JANE.DEV", "  jane.dev  "])
    def test_good_domains_are_normalised(self, good):
        assert PortfolioOptions(custom_domain=good).custom_domain == good.strip().lower()

    def test_the_404_page_is_self_contained_and_links_home(self):
        page = soup(make(site_url="https://jane.example.com/").files()["404.html"].decode())
        assert [a["href"] for a in page.find_all("a")] == ["https://jane.example.com/"]
        assert not page.find_all("script") and not page.find(["img", "iframe", "form"])
        assert "default-src 'none'" in page.find("meta", attrs={"http-equiv": "Content-Security-Policy"})["content"]
        assert page.find("meta", attrs={"name": "robots"})["content"] == "noindex"
        assert [a["href"] for a in soup(make().files()["404.html"].decode()).find_all("a")] == ["/"]

    def test_the_404_page_follows_the_auto_theme(self):
        assert "prefers-color-scheme: dark" in make(theme="auto").files()["404.html"].decode()

    def test_bundles_are_deterministic_with_every_option_on(self):
        a = make(cv=PDF, include_cv=True, custom_domain="jane.dev", theme="auto").zip_bytes()
        assert a == make(cv=PDF, include_cv=True, custom_domain="jane.dev", theme="auto").zip_bytes()
        with zipfile.ZipFile(io.BytesIO(a)) as z:
            assert z.testzip() is None and "CNAME" in z.namelist() and len(z.namelist()) == len(set(z.namelist()))

    def test_readme_lists_the_extra_files_and_the_no_preview_image_limit(self):
        readme = make(site_url="https://jane.example.com/").readme
        for name in ("robots.txt", "404.html", "sitemap.xml"):
            assert name in readme
        assert "no preview image" in readme


class TestFaviconAndData:
    def icon(self, name):
        p = full_profile().model_copy(update={"name": name})
        return soup(make(p).html).find("link", rel="icon")["href"]

    @pytest.mark.parametrize(
        "name,initials",
        [
            ("Priya Nair", "PN"),
            ("priya", "P"),
            ("Priya Kumari Nair", "PN"),
            ("李 雷", "李雷"),
            ("Anne-Marie O'Neil", "AO"),
        ],
    )
    def test_initials(self, name, initials):
        from urllib.parse import unquote

        svg = unquote(self.icon(name).split(",", 1)[1])
        assert f">{initials}</text>" in svg and svg.count("<") == svg.count(">")

    def test_the_icon_cannot_carry_markup_from_the_name(self, monkeypatch):
        bypass_gate(monkeypatch)
        from urllib.parse import unquote

        svg = unquote(self.icon("<b>Eve</b> <script>x</script>"))
        assert "<script" not in svg and "<b>" not in svg

    def test_works_for_is_only_claimed_for_a_role_marked_current(self):
        p = full_profile()
        done = p.model_copy(
            update={
                "experience": [
                    e.model_copy(update={"dates": e.dates.model_copy(update={"current": False, "end": "2024-01"})})
                    for e in p.experience
                ]
            }
        )
        for profile, expected in ((p, True), (done, False)):
            data = json.loads(soup(make(profile).html).find("script").string)
            assert ("worksFor" in data) is expected

    def test_knows_about_is_capped_and_alumni_are_unique(self):
        p = full_profile().model_copy(update={"skills": [f"Skill{i}" for i in range(40)]})
        data = json.loads(soup(make(p).html).find("script").string)
        assert len(data["knowsAbout"]) == 20
        assert len(json.loads(soup(make().html).find("script").string)["alumniOf"]) == 1

    def test_a_github_only_profile_still_builds_every_file(self):
        p = Profile(name="Sam Rivera", contact=Contact(github="github.com/sam"), projects=[Project(name="Tool")])
        assert {"index.html", "404.html", "robots.txt"} <= set(make(p).files())
