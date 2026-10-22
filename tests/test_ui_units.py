"""Pure pieces of the UI layer: error messages, escaping, file names, AI configuration and quota."""

import re

import pytest
from streamlit.testing.v1 import AppTest

from careerforge.ai import errors as ai
from careerforge.ai.extract import NotEnoughText
from careerforge.ingest.errors import EmptyDocument, FileTooLarge, UnsafeURL
from careerforge.models import Profile, ProfileError
from careerforge.readiness import NotReady, check
from careerforge.ui import state as _state
from careerforge.ui.errors import AIBudgetExceeded, explain
from careerforge.ui.text import md_escape
from careerforge.ui.widgets import safe_file_stem

REAL_CACHED_CLIENT = _state._cached_client  # captured before any fixture patches it
SECRET = "AIzaSyA-very-secret-key-1234567890abcdef"


class TestExplain:
    @pytest.mark.parametrize(
        "exc,fragment",
        [
            (ai.AINotConfigured("x"), "AI is not set up"),
            (ai.AIAuthError("x"), "rejected the API key"),
            (ai.AIQuotaExhausted("x"), "out of quota"),
            (ai.AIRateLimited("x"), "out of quota"),
            (ai.AIUnavailable("x"), "could not be reached"),
            (ai.AIOutputError("x"), "unusable"),
            (ai.AIBadRequest("x"), "refused the request"),
            (ai.AIError("x"), "AI request failed"),
            (AIBudgetExceeded("This session has used its 30 shared AI actions."), "30 shared AI actions"),
            (NotEnoughText("x"), "too little text"),
            (FileTooLarge("The file is larger than 10 MB"), "larger than 10 MB"),
            (EmptyDocument("No text"), "No text"),
            (UnsafeURL("blocked"), "blocked"),
            (ProfileError("contact.email: Not a valid email address"), "Not a valid email"),
        ],
    )
    def test_each_known_failure_has_a_clear_message(self, exc, fragment):
        assert fragment in explain(exc)

    def test_exhausted_distinguishes_network_key_and_quota_problems(self):
        net = ai.AIExhausted("all failed", [("g/m", "AIUnavailable: down"), ("q/m", "AIUnavailable: down")])
        key = ai.AIExhausted("rejected", [("g/m", "AIAuthError: bad")])
        quota = ai.AIExhausted("all failed", [("g/m", "AIQuotaExhausted: daily"), ("q/m", "AIUnavailable: x")])
        assert "could not be reached" in explain(net)
        assert "rejected the API key" in explain(key)
        assert "out of quota" in explain(quota)

    def test_not_ready_lists_the_blockers(self):
        with pytest.raises(NotReady) as e:
            from careerforge.render.text_export import render_cv_txt

            render_cv_txt(Profile())
        message = explain(e.value)
        assert "Add your real full name" in message and "Add an email address" in message

    def test_unexpected_errors_are_generic_and_never_leak_internals_or_keys(self, caplog):
        message = explain(RuntimeError(f"boom with {SECRET} and /home/user/secret/path.py"))
        assert message.startswith("Something unexpected went wrong (RuntimeError)")
        assert SECRET not in message and "/home" not in message and "Traceback" not in message
        assert "unexpected error" in caplog.text  # details go to the log only

    def test_provider_messages_are_redacted_before_they_get_here(self):
        # the AI layer redacts keys in the exceptions it raises; explain() must not add them back
        exc = ai.AIExhausted("All AI providers failed", [("g/m", ai.redact(f"AIUnavailable: key={SECRET}", (SECRET,)))])
        assert SECRET not in explain(exc) and SECRET not in "".join(w for _, w in exc.attempts)


class TestMarkdownEscape:
    NASTY = [
        "<script>alert(1)</script>",
        "[click](javascript:alert(1))",
        "![x](http://evil/x.png)",
        "**bold** _it_ `code` ~~strike~~",
        "$$\\int x$$ and $5 and $6",
        ":smile: :material/delete:",
        "# heading\n> quote\n- list\n1. one",
        "a | b | c",
        "<img src=x onerror=alert(1)>",
        "&amp; &lt;",
        "\\already escaped\\",
    ]

    @pytest.mark.parametrize("text", NASTY)
    def test_every_markdown_and_html_character_is_neutralised(self, text):
        out = md_escape(text)
        # every special character in the output is preceded by a backslash
        assert not re.search(r"(?<!\\)[<>\[\]()*_`#|~$&:!{}+.-]", out.replace("\\\\", "")), out

    def test_plain_text_is_unchanged_apart_from_punctuation(self):
        assert md_escape("Hello World 42") == "Hello World 42"

    def test_non_strings_are_accepted(self):
        assert md_escape(42) == "42" and md_escape(None) == "None"

    def test_rendered_by_streamlit_it_has_no_html_or_links(self):
        def app():
            import streamlit as st

            from careerforge.ui.text import md_escape

            st.markdown(md_escape("[x](http://evil) <b>y</b> **z**"))

        at = AppTest.from_function(app).run()
        assert at.markdown[0].value == r"\[x\]\(http\://evil\) \<b\>y\</b\> \*\*z\*\*"


class TestFileNames:
    @pytest.mark.parametrize(
        "name,stem",
        [
            ("Priya Nair", "Priya_Nair"),
            ("../../etc/passwd", "etc_passwd"),
            ("Zoë Ångström", "Zo_ngstr_m"),
            ("A" * 200, "A" * 60),
            ("", "cv"),
            ("***", "cv"),
            ("  a/b\\c:d  ", "a_b_c_d"),
            ("李小龍", "cv"),
        ],
    )
    def test_stem_is_a_safe_ascii_filename_part(self, name, stem):
        assert safe_file_stem(name) == stem
        assert re.fullmatch(r"[A-Za-z0-9_]+", safe_file_stem(name))


# ── AI configuration and quota (exercised through a tiny app so session_state is real) ──


def ai_probe():
    import streamlit as st

    from careerforge.ui import state

    s = state.ai_settings()
    st.session_state["probe"] = {
        "gemini": s.gemini_api_key,
        "groq": s.groq_api_key,
        "models": s.gemini_models,
        "url": s.gemini_base_url,
        "configured": state.ai_configured(),
        "left": state.ai_calls_left(),
        "limit": state.ai_limit(),
    }


@pytest.fixture
def probe(ui_env):
    def run(site=None, user=None, calls=0):
        ui_env.site(**(site or {}))
        at = AppTest.from_function(ai_probe)
        if user:
            at.session_state["user_keys"] = user
        at.session_state["ai_calls"] = calls
        return at.run().session_state["probe"]

    return run


class TestAiConfig:
    def test_nothing_configured(self, probe):
        p = probe()
        assert not p["configured"] and p["gemini"] == "" and p["left"] == 30

    def test_site_keys_are_used_with_a_shared_quota(self, probe):
        p = probe(site={"GEMINI_API_KEY": "site-key"}, calls=4)
        assert p["configured"] and p["gemini"] == "site-key" and p["left"] == 26

    def test_the_visitors_own_key_replaces_the_sites_and_removes_the_limit(self, probe):
        p = probe(site={"GEMINI_API_KEY": "site-key", "GROQ_API_KEY": "site-groq"}, user={"GROQ_API_KEY": "mine"})
        assert p["gemini"] == "" and p["groq"] == "mine" and p["left"] is None  # keys never mixed

    def test_pinned_models_and_proxy_urls_still_come_from_the_site(self, probe):
        p = probe(
            site={
                "GEMINI_API_KEY": "k",
                "CAREERFORGE_GEMINI_MODELS": "m1, m2",
                "CAREERFORGE_GEMINI_BASE_URL": "http://localhost:9/",
            },
            user={"GEMINI_API_KEY": "mine"},
        )
        assert p["models"] == ("m1", "m2") and p["url"] == "http://localhost:9"

    def test_quota_limit_is_configurable_and_bad_values_fall_back(self, probe):
        assert probe(site={"CAREERFORGE_SESSION_AI_LIMIT": "5", "GEMINI_API_KEY": "k"})["left"] == 5
        assert probe(site={"CAREERFORGE_SESSION_AI_LIMIT": "lots", "GEMINI_API_KEY": "k"})["left"] == 30
        assert probe(site={"GEMINI_API_KEY": "k"}, calls=99)["left"] == 0  # never negative

    def test_a_non_http_base_url_is_rejected(self):
        from careerforge.ai.settings import load_settings

        with pytest.raises(ValueError, match="must start with http"):
            load_settings({"CAREERFORGE_GEMINI_BASE_URL": "file:///etc/passwd"}, env={})
        assert load_settings({}, env={}).gemini_base_url is None


def test_the_real_site_config_reads_secrets_then_environment(monkeypatch):
    """Unpatched `_site_config`: environment variables are used when there is no secrets entry."""
    from careerforge.ui import state

    def reader():
        import streamlit as st

        from careerforge.ui import state

        st.session_state["cfg"] = state._site_config()

    monkeypatch.setenv("GROQ_API_KEY", "env-groq")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-be-read")
    at = AppTest.from_function(reader)
    at.secrets["GEMINI_API_KEY"] = "secret-gemini"
    at.run()
    cfg = at.session_state["cfg"]
    assert cfg["GEMINI_API_KEY"] == "secret-gemini" and cfg["GROQ_API_KEY"] == "env-groq"
    assert "UNRELATED_SECRET" not in cfg and "UNRELATED_SECRET" not in str(cfg)
    assert state.site_secret.__doc__


def test_a_profile_is_required_by_every_data_page():
    from ui_helpers import new_app, open_page

    at = new_app().run()
    for name in ["review", "match", "tailor", "insights", "cv", "portfolio", "linkedin", "write", "jobs"]:
        open_page(at, name)
        assert not at.exception, name
        assert any("Start by adding" in i.value for i in at.info), name
        assert not at.text_area and not [b for b in at.button if "Save" in b.label], name


def test_check_is_used_for_the_sidebar_status():
    assert check(Profile()).ready is False


# ── a visitor's own key must never reach the shared, server-wide cache ──────


def client_probe():
    import streamlit as st

    from careerforge.ui import state

    client = state.ai_client()
    st.session_state["probe"] = {"id": id(client), "same_again": client is state.ai_client()}


@pytest.fixture
def builds(monkeypatch, ui_env):
    from careerforge.ui import state

    monkeypatch.setattr(state, "_cached_client", REAL_CACHED_CLIENT)  # ui_env had replaced it with a stub
    made = []

    def fake_build(*args):
        made.append(args)
        return object()

    monkeypatch.setattr(state, "_build_client", fake_build)
    state._cached_client.clear()
    yield made
    state._cached_client.clear()


def test_the_owners_client_is_cached_across_visitors(ui_env, builds):
    ui_env.site(GEMINI_API_KEY="owner-key")
    first = AppTest.from_function(client_probe).run().session_state["probe"]
    second = AppTest.from_function(client_probe).run().session_state["probe"]
    assert len(builds) == 1 and first["id"] == second["id"]  # one shared client, built once


def test_a_visitors_own_key_stays_in_their_session_and_out_of_the_shared_cache(ui_env, builds):
    ui_env.site(GEMINI_API_KEY="owner-key")
    mine = AppTest.from_function(client_probe)
    mine.session_state["user_keys"] = {"GEMINI_API_KEY": "visitor-secret-key"}
    first = mine.run().session_state["probe"]
    assert first["same_again"]  # reused within the session
    assert [a[0] for a in builds] == ["visitor-secret-key"]
    # a different visitor, and the owner's cache, never see that key or that client
    other = AppTest.from_function(client_probe).run().session_state["probe"]
    assert builds[-1][0] == "owner-key" and other["id"] != first["id"]
    assert [a[0] for a in builds].count("owner-key") == 1  # only the owner's client went through the shared cache


def test_changing_the_visitors_key_builds_a_new_client(ui_env, builds):
    at = AppTest.from_function(client_probe)
    at.session_state["user_keys"] = {"GEMINI_API_KEY": "key-one-123456"}
    at.run()
    at.session_state["user_keys"] = {"GEMINI_API_KEY": "key-two-123456"}
    at.run()
    assert [a[0] for a in builds] == ["key-one-123456", "key-two-123456"]
