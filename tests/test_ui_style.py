"""The app's look: the stylesheet is fixed text, the sidebar says what to do next, Start shows the three steps."""

import re

import pytest
from test_render_cv import experienced
from ui_helpers import new_app, open_page

from careerforge.models import Profile
from careerforge.ui import style


def html_of(at) -> list[str]:
    return [h.proto.body for h in at.get("html")]


class TestNextStep:
    def test_no_profile_points_to_start(self):
        assert style.next_step(False, False)[0] == "Start"

    def test_a_profile_that_cannot_be_exported_points_to_review(self):
        assert style.next_step(True, False)[0] == "Review & edit"

    def test_a_ready_profile_points_to_the_export_page(self):
        assert style.next_step(True, True)[0] == "CV"

    @pytest.mark.parametrize("state", [(False, False), (True, False), (True, True)])
    def test_the_advice_is_plain_fixed_text(self, state):
        page, todo = style.next_step(*state)
        assert not re.search(r"[<>{}&]", page.replace("&", "") + todo)


class TestSidebar:
    def test_it_shows_the_next_step_for_every_state(self):
        empty = new_app().run()
        assert any("Next: Start" in h for h in html_of(empty))
        ready = new_app(experienced()).run()
        assert any("Next: CV<" in h for h in html_of(ready))
        blocked = new_app(Profile(name="Sam Rivera")).run()
        assert any("Next: Review" in h for h in html_of(blocked))
        assert not empty.exception and not ready.exception and not blocked.exception

    def test_a_hostile_profile_name_never_reaches_the_raw_html(self):
        at = new_app(experienced().model_copy(update={"name": "<img src=x onerror=alert(1)>"})).run()
        assert not at.exception
        assert not any("onerror" in h for h in html_of(at))


class TestStartPage:
    def test_the_three_steps_are_shown(self):
        at = new_app().run()
        steps = [h for h in html_of(at) if 'class="cf-steps"' in h]
        assert len(steps) == 1 and steps[0].count("<li>") == 3
        assert "Add your details" in steps[0] and "Download and apply" in steps[0]

    def test_other_pages_do_not_repeat_them(self):
        at = open_page(new_app(experienced()).run(), "review")
        assert not any('class="cf-steps"' in h for h in html_of(at))


class TestStylesheet:
    def test_it_is_injected_once_per_run_and_hidden_from_layout(self):
        css = [h for h in html_of(new_app().run()) if h.startswith("<style>")]
        assert len(css) == 1 and ':has(> [data-testid="stHtml"] style:only-child)' in css[0]

    def test_it_loads_nothing_from_anywhere(self):
        assert not re.search(r"url\(|@import|https?:|//\w", style.CSS)

    def test_it_is_fixed_text(self):
        assert "{user" not in style.CSS and "<script" not in style.CSS.lower()
        assert "<script" not in style.STEPS.lower() and "{" not in style.STEPS

    def test_motion_is_opt_in(self):
        before, _, after = style.CSS.partition("prefers-reduced-motion: no-preference")
        assert not re.search(r"(?<![-\w])transform\s*:|transition", before) and "translateY" in after

    def test_the_logo_is_a_local_file_with_a_text_alternative(self):
        from pathlib import Path

        logo = Path(style.LOGO)
        assert logo.is_absolute() and logo.exists()
        svg = logo.read_text()
        assert 'aria-label="CareerForge AI"' in svg and "<script" not in svg and "href" not in svg
