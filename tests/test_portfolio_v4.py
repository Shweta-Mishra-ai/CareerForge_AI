"""Portfolio v4: the Spotlight and Bento layouts, your photo, and the "Open to opportunities" badge."""

import base64
import io
from datetime import date

import pytest
from bs4 import BeautifulSoup
from PIL import Image
from test_render_portfolio import browser, full_profile  # noqa: F401  (browser is a fixture)

from careerforge.models import Contact, Experience, Profile, Project
from careerforge.render.options import contrast_ratio
from careerforge.render.photo import SIDE, PhotoError, prepare_photo
from careerforge.render.portfolio import LAYOUTS, PortfolioOptions, build_portfolio
from careerforge.render.themes import LARGE_TEXT_MIN, PRESETS, THEMES, with_preset

TODAY = date(2026, 10, 10)
NEW = ["spotlight", "bento"]


def build(profile=None, photo=None, **kw):
    return build_portfolio(profile or full_profile(), PortfolioOptions(**kw), today=TODAY, photo=photo)


def soup(html):
    return BeautifulSoup(html, "html.parser")


def image_bytes(fmt="JPEG", size=(900, 1200), mode="RGB", colour=(200, 120, 60), **save):
    buf = io.BytesIO()
    Image.new(mode, size, colour).save(buf, fmt, **save)
    return buf.getvalue()


# ── the photo ───────────────────────────────────────────────────────────────


class TestPhoto:
    def test_it_becomes_a_small_square_jpeg(self):
        out = prepare_photo(image_bytes(size=(1600, 2400)))
        with Image.open(io.BytesIO(out)) as img:
            assert img.format == "JPEG" and img.size == (SIDE, SIDE)
        assert len(out) < 60_000

    def test_location_and_camera_data_are_dropped(self):
        exif = Image.Exif()
        exif[0x010F] = "PhoneMaker"  # camera make
        exif[0x0132] = "2026:10:10 09:30:00"  # when it was taken
        out = prepare_photo(image_bytes(exif=exif.tobytes()))
        with Image.open(io.BytesIO(out)) as img:
            assert not img.getexif() and "exif" not in img.info
        assert b"PhoneMaker" not in out and b"2026:10:10" not in out  # GPS lives in the same EXIF block

    def test_the_phone_rotation_is_applied_before_it_is_dropped(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # "rotate 90 degrees": a portrait photo stored sideways
        wide = io.BytesIO()
        img = Image.new("RGB", (1200, 600), (255, 255, 255))
        img.paste((0, 0, 0), (0, 0, 600, 600))  # left half black
        img.save(wide, "JPEG", exif=exif.tobytes())
        with Image.open(io.BytesIO(prepare_photo(wide.getvalue()))) as out:
            top, bottom = out.getpixel((SIDE // 2, 5)), out.getpixel((SIDE // 2, SIDE - 5))
        assert sum(top) < 100 and sum(bottom) > 600  # the black half ended up on top: rotated, as the phone meant

    def test_transparent_png_and_webp_are_accepted(self):
        assert prepare_photo(image_bytes("PNG", mode="RGBA", colour=(0, 0, 0, 0)))[:2] == b"\xff\xd8"
        assert prepare_photo(image_bytes("WEBP"))[:2] == b"\xff\xd8"

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            (b"", "empty"),
            (b"not an image at all", "could not be read"),
            (image_bytes("GIF", mode="P"), "JPEG, PNG or WebP"),
            (b"<svg onload=alert(1)>", "could not be read"),
        ],
    )
    def test_bad_files_are_refused_with_a_sentence(self, data, message):
        with pytest.raises(PhotoError, match=message):
            prepare_photo(data)

    def test_huge_files_and_pixel_bombs_are_refused(self):
        with pytest.raises(PhotoError, match="8 MB"):
            prepare_photo(b"\xff" * (8 * 1024 * 1024 + 1))
        bomb = image_bytes("PNG", size=(8000, 6000), mode="1", colour=0)  # tiny file, 48 megapixels
        assert len(bomb) < 2_000_000
        with pytest.raises(PhotoError, match="megapixels"):
            prepare_photo(bomb)

    @pytest.mark.parametrize("layout", [k for k in LAYOUTS if k != "editorial"])
    def test_every_picture_layout_shows_it_inline_with_a_text_alternative(self, layout):
        s = soup(build(photo=image_bytes(), layout=layout).html)
        imgs = s.select("img.avatar")
        assert len(imgs) == 1 and imgs[0]["alt"] == "Photo of Priya Nair"
        assert imgs[0]["src"].startswith("data:image/jpeg;base64,")
        decoded = base64.b64decode(imgs[0]["src"].split(",", 1)[1])
        with Image.open(io.BytesIO(decoded)) as img:
            assert img.size == (SIDE, SIDE)

    def test_the_editorial_layout_stays_type_only(self):
        assert not soup(build(photo=image_bytes(), layout="editorial").html).find("img")

    def test_no_photo_means_no_image_and_the_initials_instead(self):
        s = soup(build(layout="spotlight").html)
        assert not s.find("img") and s.select_one(".orb .avatar").get_text() == "PN"

    def test_a_bad_photo_stops_the_build_with_the_reason(self):
        with pytest.raises(PhotoError):
            build(photo=b"nonsense")


# ── the badge ───────────────────────────────────────────────────────────────


class TestOpenToWork:
    @pytest.mark.parametrize("layout", list(LAYOUTS))
    def test_it_is_off_unless_you_turn_it_on(self, layout):
        assert "Open to opportunities" not in build(layout=layout).html
        s = soup(build(layout=layout, open_to_work=True).html)
        badge = s.select_one(".status")
        assert badge.get_text(strip=True) == "Open to opportunities"
        assert badge.find("span", class_="dot")["aria-hidden"] == "true"


# ── spotlight ───────────────────────────────────────────────────────────────


class TestSpotlight:
    def test_the_headline_is_the_big_title_with_its_last_word_in_the_gradient(self):
        s = soup(build(layout="spotlight").html)
        h1 = s.find("h1")
        assert h1.get_text(" ", strip=True) == "Senior Backend Engineer"
        assert h1.find("span", class_="grad").get_text() == "Engineer"
        assert s.select_one(".kicker").get_text() == "Priya Nair"

    def test_without_a_headline_the_name_is_the_title(self):
        p = full_profile().model_copy(update={"headline": ""})
        s = soup(build(p, layout="spotlight").html)
        assert s.find("h1").get_text(" ", strip=True) == "Priya Nair" and not s.select(".kicker")

    def test_the_summary_sits_in_the_introduction_and_is_not_repeated(self):
        html = build(layout="spotlight").html
        s = soup(html)
        assert s.body.get_text().count(full_profile().summary) == 1
        assert s.select_one("#about h2").get_text() == "About" and "sr-only" in s.select_one("#about h2")["class"]
        assert not s.select("main #about")

    def test_floating_cards_use_only_what_you_chose_to_show(self):
        s = soup(build(layout="spotlight").html)
        assert not s.select(".float.f1")  # the city is opt-in
        assert s.select_one(".float.f2").get_text(strip=True) == "Senior Backend Engineer · Finlytics Pvt Ltd"
        shown = soup(build(layout="spotlight", show_location=True).html)
        assert shown.select_one(".float.f1").get_text(strip=True) == "Bengaluru, India"

    def test_hiding_a_section_also_hides_it_from_the_introduction(self):
        s = soup(build(layout="spotlight", hidden=frozenset({"experience", "skills"})).html)
        assert not s.select(".float.f2") and not s.select(".chipline")
        assert "Finlytics" not in s.get_text() and "PostgreSQL" not in s.get_text()

    def test_no_current_role_means_no_role_card(self):
        p = full_profile()
        past = [e.model_copy(update={"dates": e.dates.model_copy(update={"current": False})}) for e in p.experience]
        s = soup(build(p.model_copy(update={"experience": past}), layout="spotlight").html)
        assert not s.select(".float.f2")


class TestGradientIsReadable:
    @pytest.mark.parametrize("theme", list(THEMES))
    @pytest.mark.parametrize("preset", [None, *PRESETS])
    def test_the_gradient_end_is_large_text_readable_everywhere_it_can_sit(self, theme, preset):
        t = with_preset(THEMES[theme], preset) if preset else THEMES[theme]
        for pal in (t, t.dark) if t.dark else (t,):
            for bg in (pal.bg, pal.surface, pal.wash, pal.wash2):
                assert contrast_ratio(pal.grad_end, bg) >= LARGE_TEXT_MIN
                assert contrast_ratio(pal.accent, bg) >= 4.5

    def test_it_falls_back_to_the_accent_when_the_partner_colour_is_too_faint(self):
        t = with_preset(THEMES["light"], "orange")
        assert t.grad_end == t.accent != t.accent2
        assert THEMES["dark"].grad_end == THEMES["dark"].accent2  # where it is readable, the gradient is kept


# ── bento ───────────────────────────────────────────────────────────────────


class TestBento:
    def test_the_overview_tiles(self):
        s = soup(build(layout="bento").html)
        assert [t.select_one("strong").get_text() for t in s.select(".box.stat")] == ["8", "2", "42"]
        role = s.select_one(".box.role")
        assert role.select_one(".mono").get_text() == "F" and "Finlytics Pvt Ltd" in role.get_text()
        assert [li.get_text() for li in s.select(".box.skillset li")] == ["Python", "Go", "PostgreSQL", "Redis"]
        assert s.select_one(".box#contact h2").get_text() == "Contact" and len(s.select("#contact")) == 1

    def test_hidden_contact_and_experience_leave_no_tile(self):
        s = soup(build(layout="bento", hidden=frozenset({"contact", "experience"})).html)
        assert not s.select("#contact") and not s.select(".box.role")

    def test_a_sparse_profile_still_makes_a_tidy_page(self):
        p = Profile(name="Sam Rivera", contact=Contact(email="sam@gmail.com"), projects=[Project(name="Tool")])
        s = soup(build(p, layout="bento").html)
        assert s.find("h1").get_text() == "Sam Rivera" and not s.select(".box.role") and not s.select(".box.skillset")

    def test_a_role_without_a_company_uses_its_title(self):
        p = full_profile().model_copy(
            update={"experience": [Experience(title="Freelance developer", dates=full_profile().experience[0].dates)]}
        )
        s = soup(build(p, layout="bento").html)
        assert s.select_one(".box.role .mono").get_text() == "FD"


# ── in a real browser ───────────────────────────────────────────────────────


class TestInBrowser:
    @pytest.mark.parametrize("layout", NEW)
    @pytest.mark.parametrize("scheme", ["light", "dark"])
    def test_with_photo_badge_and_city_axe_finds_nothing(self, browser, tmp_path, layout, scheme):  # noqa: F811
        from axe_playwright_python.sync_playwright import Axe

        f = tmp_path / "index.html"
        html = build(photo=image_bytes(), layout=layout, theme="auto", open_to_work=True, show_location=True).html
        f.write_text(html, encoding="utf-8")
        page = browser.new_page(color_scheme=scheme)
        page.goto(f.as_uri())
        found = (
            Axe()
            .run(
                page, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa", "best-practice"]}}
            )
            .response["violations"]
        )
        loaded = page.evaluate("[...document.images].every(i => i.complete && i.naturalWidth === 480)")
        page.close()
        assert not found, [(v["id"], [n["html"][:80] for n in v["nodes"]]) for v in found]
        assert loaded  # the strict CSP still lets the inline photo show

    @pytest.mark.parametrize("layout", NEW)
    @pytest.mark.parametrize("width", [320, 390, 768, 1280])
    def test_nothing_scrolls_sideways(self, browser, tmp_path, layout, width):  # noqa: F811
        f = tmp_path / "index.html"
        f.write_text(build(layout=layout, open_to_work=True, show_location=True).html, encoding="utf-8")
        page = browser.new_page(viewport={"width": width, "height": 800})
        page.goto(f.as_uri())
        over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        page.close()
        assert over <= 0, f"{over}px sideways at {width}px ({layout})"
