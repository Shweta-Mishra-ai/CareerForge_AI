"""Characterisation tests for core/ai_engine.py parsing (replaced in Phase 2). No network, no LLM calls."""

import pytest

from core.ai_engine import _to_html, clean_and_parse_json


def test_markdown_fenced_json_is_parsed():
    out = clean_and_parse_json('```json\n{"name": "A", "skills": ["x", "y"]}\n```')
    assert out["name"] == "A"
    assert out["skills"] == "x, y"  # list -> comma string


def test_missing_keys_get_defaults():
    out = clean_and_parse_json('{"name": "A"}')
    assert out["headline"] == "Professional" and out["contact"] == "" and out["summary"] == ""


def test_experience_dict_list_becomes_html():
    html = _to_html([{"title": "Dev", "company": "Acme", "dates": "2020", "bullets": ["did x"]}])
    assert "<b>Dev at Acme (2020)</b>" in html and "<li>did x</li>" in html


def test_garbage_response_returns_fallback_dict_instead_of_raising():
    out = clean_and_parse_json("totally not json")
    assert out["name"] == "Candidate" and "Extraction Error" in out["experience"]


@pytest.mark.xfail(reason="AUDIT #3: parse failure is swallowed, so the UI shows a success banner (needs loud errors)")
def test_garbage_response_raises():
    with pytest.raises(ValueError):
        clean_and_parse_json("totally not json")


@pytest.mark.xfail(reason="AUDIT #9: '85%' score stays a string, so new - old raises TypeError in app.py")
def test_analysis_scores_are_coerced_to_int():
    out = clean_and_parse_json('{"old_ats_score": "85%", "new_ats_score": 90}', is_analysis=True)
    assert isinstance(out["old_ats_score"], int) and out["old_ats_score"] == 85


@pytest.mark.xfail(reason="AUDIT: tailored_cv from the LLM is not given the defaults the base CV gets")
def test_tailored_cv_gets_required_keys():
    out = clean_and_parse_json('{"tailored_cv": {"name": "X"}}', is_analysis=True)
    assert {"headline", "contact", "skills", "summary"} <= set(out["tailored_cv"])
