"""Characterisation tests for core/scraper.py (replaced in Phase 3). Network is never touched."""

import pytest

from core.scraper import _name_from_url


def test_name_from_linkedin_slug():
    assert "John Doe" in _name_from_url("https://www.linkedin.com/in/john-doe-123")


def test_name_from_garbage_url_falls_back():
    assert "Candidate" in _name_from_url("https://example.com/")


@pytest.mark.xfail(reason="AUDIT #2: slug-only stub is long enough to pass the 50-char gate, so the LLM builds a CV from a name")
def test_slug_only_result_is_too_thin_to_generate_from():
    assert len(_name_from_url("https://www.linkedin.com/in/john-doe-123").strip()) < 50
