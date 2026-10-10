"""Hostile or huge input must not make a session hang. Limits are generous (CI machines are slow); the broken
versions took tens of seconds to minutes on these exact inputs."""

import time

import pytest
from test_render_cv import experienced

from careerforge.ats.jd import parse_job_description
from careerforge.ats.report import analyze
from careerforge.ingest.pipeline import ingest_upload
from careerforge.ingest.rules import read_cv

N = 30_000
HOSTILE = {
    "one long word": "a" * N,
    "one long unicode word": "é" * N,
    "dashes": "-" * N,
    "digits and spaces": "1 " * (N // 2) + "x",
    "at signs": "a@" * (N // 2),
    "open parens": "(" * N,
    "repeated dates": "Jan 2020 - " * (N // 11),
    "repeated headings": "EXPERIENCE\n" * (N // 11),
    "repeated bullets": "- a\n" * (N // 4),
    "phone-like runs": "+1 (555) 555-5555 " * (N // 18),
    "semicolons": "; " * (N // 2),
    "spaced letters": "S K I L L S  " * (N // 12),
    "only newlines": "\n" * N,
}


def timed(fn, *args):
    start = time.perf_counter()
    fn(*args)
    return time.perf_counter() - start


@pytest.mark.parametrize("name", HOSTILE)
def test_the_rule_reader_stays_fast_on_hostile_text(name):
    assert timed(read_cv, HOSTILE[name]) < 5


@pytest.mark.parametrize("name", ["one long word", "semicolons", "repeated dates", "digits and spaces", "at signs"])
def test_job_posting_analysis_stays_fast_on_hostile_text(name):
    assert timed(parse_job_description, HOSTILE[name]) < 8
    assert timed(analyze, experienced(), HOSTILE[name]) < 8


def test_a_five_megabyte_text_upload_is_read_in_bounded_time():
    blob = ("Engineer at Acme Corp 2019 - 2021 Python Kubernetes\n" * 100_000).encode()
    assert len(blob) > 5_000_000
    start = time.perf_counter()
    result = ingest_upload("big.txt", blob, None)
    assert time.perf_counter() - start < 20  # reading is capped at 200,000 characters
    assert any("very long" in w for w in result.warnings)
