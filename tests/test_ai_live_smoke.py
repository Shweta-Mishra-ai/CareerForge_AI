"""MANUAL live smoke test - the only check that touches real provider APIs.

Run it yourself when you have keys (it makes ~1 tiny request per discovered model and costs ~nothing).
For a readable report with paste-ready settings, prefer:  python -m careerforge.ai.doctor

    GEMINI_API_KEY=... GROQ_API_KEY=... pytest -m live -s tests/test_ai_live_smoke.py

It verifies what the offline tests cannot: that the default model names are still served and that real
responses parse. Skipped automatically when no key is set; excluded from CI.
"""

import os

import pytest

from careerforge.ai.client import AIClient, RetryPolicy, build_client, parse_json_object
from careerforge.ai.errors import AIError
from careerforge.ai.providers import Request
from careerforge.ai.settings import load_settings

pytestmark = pytest.mark.live
SETTINGS = load_settings(env=os.environ)
REQ = Request(system="Reply with one JSON object.", user='Return {"ok": true}', max_tokens=64)


def _routes():
    """Routes exactly as the app builds them (discovery included), so this tests what users will really get."""
    if not SETTINGS.configured:
        return []
    return build_client(SETTINGS).routes


@pytest.mark.skipif(not SETTINGS.configured, reason="set GEMINI_API_KEY and/or GROQ_API_KEY to run")
@pytest.mark.parametrize("route", _routes(), ids=str)
def test_each_configured_model_is_served_and_returns_json(route):
    try:
        value, _ = AIClient([route], RetryPolicy(attempts_per_route=1)).structured(REQ, parse_json_object)
    except AIError as exc:
        pytest.fail(f"{route}: {exc}")
    assert value.get("ok") is True
