"""A broken or mis-formatted secrets file must be reported, not silently turn the AI off."""

import os

import pytest
import streamlit as st
from streamlit import config
from streamlit.runtime.secrets import Secrets

from careerforge.ui import state

MISSING = None
BAD_TOML = 'GEMINI_API_KEY = "abc"\nGROQ = = x\n'
NESTED = '[general]\nGEMINI_API_KEY = "abc-nested"\nGROQ_API_KEY = "def"\n'
GOOD = 'GEMINI_API_KEY = "abc-good"\n'
GOOGLE_NAME = 'GOOGLE_API_KEY = "abc-google"\n'


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    previous = config.get_option("secrets.files")
    for name in (*state._KEY_NAMES, *state._GEMINI_ALIASES):
        monkeypatch.delenv(name, raising=False)
    state._warned.clear()

    def use(content):
        path = tmp_path / "secrets.toml"
        if content is not None:
            path.write_text(content)
        config.set_option("secrets.files", [str(path)])
        monkeypatch.setattr(st, "secrets", Secrets())

    yield use
    config.set_option("secrets.files", previous)


def test_no_secrets_file_is_normal_and_silent(secrets, caplog):
    secrets(MISSING)
    assert state._site_config() == {} and state.config_problems() == []
    assert "configuration problem" not in caplog.text


def test_a_good_file_is_read(secrets):
    secrets(GOOD)
    assert state._site_config() == {"GEMINI_API_KEY": "abc-good"} and state.config_problems() == []


def test_a_file_that_is_not_valid_toml_is_reported_without_echoing_its_content(secrets, caplog):
    secrets(BAD_TOML)
    assert state._site_config() == {}
    (problem,) = state.config_problems()
    assert "could not be parsed" in problem and "abc" not in problem and "GROQ" not in problem
    assert "configuration problem" in caplog.text and "abc" not in caplog.text


def test_keys_under_a_section_header_are_reported_by_name_not_value(secrets):
    secrets(NESTED)
    assert state._site_config() == {}  # they really are ignored...
    (problem,) = state.config_problems()  # ...and now the operator is told why
    assert "GEMINI_API_KEY, GROQ_API_KEY" in problem and "[general]" in problem
    assert "abc-nested" not in problem and "def" not in problem.replace("definitely", "")


def test_the_problem_is_logged_once_per_process_not_on_every_rerun(secrets, caplog):
    secrets(BAD_TOML)
    for _ in range(5):
        state.config_problems()
    assert caplog.text.count("configuration problem") == 1


def test_google_api_key_is_accepted_as_the_gemini_key(secrets):
    secrets(GOOGLE_NAME)
    assert state._site_config() == {"GEMINI_API_KEY": "abc-google"}


def test_the_gemini_name_wins_over_the_google_name(secrets):
    secrets(GOOD + GOOGLE_NAME)
    assert state._site_config()["GEMINI_API_KEY"] == "abc-good"


def test_environment_variables_still_work_and_google_name_works_there_too(secrets, monkeypatch):
    secrets(MISSING)
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-env")
    assert state._site_config() == {"GROQ_API_KEY": "from-env", "GEMINI_API_KEY": "google-env"}
    assert os.environ["GROQ_API_KEY"] == "from-env"


def test_the_ai_settings_use_the_alias(secrets):
    secrets(GOOGLE_NAME)
    assert state.ai_settings().gemini_api_key == "abc-google"
