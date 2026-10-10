"""Headless smoke test: the Streamlit app boots and renders its first screen (no browser, no network)."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _app_with_secrets():
    at = AppTest.from_file(APP, default_timeout=30)
    at.secrets["GEMINI_API_KEY"] = "test-not-real"
    at.secrets["GROQ_API_KEY"] = "test-not-real"
    return at


def test_app_boots_without_exception():
    at = _app_with_secrets().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("CareerForge AI" in m.value for m in at.markdown)


def test_generate_without_input_shows_error_and_does_not_crash():
    at = _app_with_secrets().run()
    at.button[0].click().run()  # "Generate CV" with nothing uploaded
    assert not at.exception, [e.value for e in at.exception]
    assert any("upload" in e.value.lower() for e in at.error)
