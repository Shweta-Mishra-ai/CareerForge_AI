"""AIClient cascade/retry/structured-output behaviour, with scripted fake providers (no network, no sleeping)."""

import pytest

from careerforge.ai.client import AIClient, Clock, RetryPolicy, Route, parse_json_object
from careerforge.ai.errors import (
    AIAuthError,
    AIBadRequest,
    AIExhausted,
    AIModelNotFound,
    AINotConfigured,
    AIOutputError,
    AIRateLimited,
    AIUnavailable,
)
from careerforge.ai.providers import Completion, Request


class Fake:
    """Provider whose replies are scripted per call: a str (text), a Completion, or an exception to raise."""

    def __init__(self, name, *script):
        self.name, self.script, self.calls = name, list(script), []

    def complete(self, model, req):
        self.calls.append((model, req))
        step = self.script.pop(0) if self.script else AIUnavailable("script exhausted")
        if isinstance(step, Exception):
            raise step
        return step if isinstance(step, Completion) else Completion(step, self.name, model)


class FakeClock(Clock):
    def __init__(self):
        self.now, self.slept = 0.0, []
        super().__init__(sleep=self._sleep, monotonic=lambda: self.now, uniform=lambda a, b: 0.0)

    def _sleep(self, s):
        self.slept.append(s)
        self.now += s


REQ = Request(system="s", user="u", max_tokens=1000)


def client(*routes, clock=None, **policy):
    return AIClient(list(routes), RetryPolicy(**policy), clock or FakeClock(), secrets=("sk-SECRETSECRET1234",))


def test_first_success_wins_and_no_sleep():
    a = Fake("a", "ok")
    c = client(Route(a, "m1"))
    assert c.complete(REQ).text == "ok" and c.clock.slept == []


def test_retryable_errors_back_off_exponentially_then_succeed():
    a = Fake("a", AIUnavailable("x"), AIRateLimited("y"), "ok")
    c = client(Route(a, "m1"), base_delay=1.0)
    assert c.complete(REQ).text == "ok"
    assert c.clock.slept == [1.0, 2.0] and len(a.calls) == 3


def test_retry_after_is_honoured_and_capped():
    a = Fake("a", AIRateLimited("y", retry_after=3.0), AIRateLimited("y", retry_after=999), "ok")
    c = client(Route(a, "m1"), max_delay=8.0)
    c.complete(REQ)
    assert c.clock.slept == [3.0, 8.0]


def test_after_retries_exhausted_it_moves_to_next_route():
    a = Fake("a", *[AIRateLimited("q")] * 3)
    b = Fake("b", "from-b")
    c = client(Route(a, "m1"), Route(b, "m2"))
    got = c.complete(REQ)
    assert (got.text, len(a.calls), len(b.calls)) == ("from-b", 3, 1)


def test_auth_error_disables_provider_without_retrying_and_skips_its_other_models():
    a = Fake("a", AIAuthError("API key rejected (401)"))
    b = Fake("b", "ok")
    c = client(Route(a, "m1"), Route(a, "m2"), Route(b, "m3"))
    assert c.complete(REQ).text == "ok"
    assert len(a.calls) == 1  # no retry, and m2 skipped


def test_model_not_found_skips_to_next_model_of_same_provider():
    a = Fake("a", AIModelNotFound("gone"), "ok")
    c = client(Route(a, "old"), Route(a, "new"))
    got = c.complete(REQ)
    assert got.model == "new" and c.clock.slept == []


def test_bad_request_is_not_retried():
    a = Fake("a", AIBadRequest("nope"))
    with pytest.raises(AIExhausted):
        client(Route(a, "m1")).complete(REQ)
    assert len(a.calls) == 1


def test_all_failed_raises_loud_error_with_redacted_attempts():
    a = Fake("a", AIAuthError("bad key sk-SECRETSECRET1234"))
    with pytest.raises(AIExhausted) as ei:
        client(Route(a, "m1")).complete(REQ)
    assert "SECRETSECRET" not in str(ei.value) and "rejected the API key" in str(ei.value)
    assert ei.value.attempts and "SECRETSECRET" not in repr(ei.value.attempts)


def test_deadline_stops_retrying():
    a = Fake("a", *[AIUnavailable("x")] * 10)
    c = client(Route(a, "m1"), attempts_per_route=10, base_delay=5.0, max_delay=5.0, deadline_s=12.0)
    with pytest.raises(AIExhausted):
        c.complete(REQ)
    assert c.clock.now <= 12.0


def test_no_routes_means_not_configured():
    with pytest.raises(AINotConfigured):
        client().complete(REQ)


class TestStructured:
    def test_valid_json_returned_with_completion(self):
        a = Fake("a", 'Here: {"x": 1}')
        value, comp = client(Route(a, "m")).structured(REQ, parse_json_object)
        assert value == {"x": 1} and comp.provider == "a"

    def test_repair_retry_includes_the_rejection_reason(self):
        a = Fake("a", "not json at all", '{"x": 1}')
        value, _ = client(Route(a, "m")).structured(REQ, parse_json_object)
        assert value == {"x": 1}
        assert "rejected" in a.calls[1][1].user and a.calls[1][1].user.startswith("u")

    def test_gives_up_after_one_repair_with_loud_error(self):
        a = Fake("a", "garbage", "still garbage")
        with pytest.raises(AIOutputError):
            client(Route(a, "m")).structured(REQ, parse_json_object)
        assert len(a.calls) == 2

    def test_truncated_output_retries_with_bigger_token_budget(self):
        a = Fake("a", Completion('{"x": [1, 2', "a", "m", truncated=True), '{"x": [1, 2]}')
        value, _ = client(Route(a, "m")).structured(REQ, parse_json_object)
        assert value == {"x": [1, 2]}
        assert a.calls[1][1].max_tokens == 2000 and a.calls[1][1].user == "u"  # same prompt, bigger budget

    def test_token_budget_never_exceeds_cap(self):
        a = Fake("a", *[Completion('{"x": [', "a", "m", truncated=True)] * 3)
        c = client(Route(a, "m"))
        c.max_tokens_cap = 1500
        with pytest.raises(AIOutputError):
            c.structured(REQ, parse_json_object, max_repairs=2)
        assert max(call[1].max_tokens for call in a.calls) <= 1500

    def test_custom_parser_value_error_triggers_repair(self):
        def parse(text):
            if "good" not in text:
                raise ValueError("missing the word good")
            return text

        a = Fake("a", "bad", "good")
        value, _ = client(Route(a, "m")).structured(REQ, parse)
        assert value == "good" and "missing the word good" in a.calls[1][1].user

    def test_non_object_json_rejected(self):
        a = Fake("a", "[1,2]", '{"ok": true}')
        value, _ = client(Route(a, "m")).structured(REQ, parse_json_object)
        assert value == {"ok": True}

    def test_unclosed_garbage_gets_feedback_not_just_more_tokens(self):
        a = Fake("a", "oops {not json", '{"x": 1}')
        value, _ = client(Route(a, "m")).structured(REQ, parse_json_object)
        retry = a.calls[1][1]
        assert value == {"x": 1} and "rejected" in retry.user and retry.max_tokens == 2000

    def test_cut_off_at_the_cap_asks_for_shorter_output(self):
        a = Fake("a", Completion('{"x": [', "a", "m", truncated=True), '{"x": 1}')
        c = client(Route(a, "m"))
        c.max_tokens_cap = 1000  # REQ already uses 1000
        c.structured(REQ, parse_json_object)
        assert "shorter" in a.calls[1][1].user and a.calls[1][1].max_tokens == 1000
