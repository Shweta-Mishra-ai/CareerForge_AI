"""Real Gemini/Groq SDKs against a local fake HTTP server.

What this proves: our request construction, header/auth handling, response parsing, error mapping and the
absence of hidden SDK retries - using the genuine SDK code paths, with no network and no API key.
What it does NOT prove: that the live services behave exactly like this fake (wire formats are taken from the
public API shapes). Treat a live smoke test as a separate, manual step.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from careerforge.ai.client import AIClient, Clock, RetryPolicy, Route, parse_json_object
from careerforge.ai.errors import (
    AIAuthError,
    AIBadRequest,
    AIExhausted,
    AIModelNotFound,
    AIRateLimited,
    AIUnavailable,
)
from careerforge.ai.providers import GeminiProvider, GroqProvider, Request

REQ = Request(system="SYS-PROMPT", user="USER-TEXT", max_tokens=77)


def gemini_ok(text, finish="STOP"):
    return 200, {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}]}


def groq_ok(text, finish="stop"):
    return 200, {
        "id": "x", "object": "chat.completion", "created": 1, "model": "m",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }  # fmt: skip


class FakeServer:
    def __init__(self):
        self.script, self.seen = [], []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
                outer.seen.append(
                    {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
                )
                step = outer.script.pop(0) if outer.script else (500, {"error": {"message": "script exhausted"}})
                status, payload, *rest = step
                extra = rest[0] if rest else {}
                if extra.get("sleep"):
                    time.sleep(extra["sleep"])
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                for k, v in extra.get("headers", {}).items():
                    self.send_header(k, v)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.close()


@pytest.fixture
def gemini(server):
    return GeminiProvider("KEY-GEM-123456", base_url=server.url, timeout_s=3)


@pytest.fixture
def groq(server):
    return GroqProvider("KEY-GROQ-123456", base_url=server.url, timeout_s=3)


class TestGemini:
    def test_request_shape_and_success(self, server, gemini):
        server.script = [gemini_ok('{"a": 1}')]
        out = gemini.complete("gemini-test", REQ)
        assert (out.text, out.provider, out.model, out.truncated) == ('{"a": 1}', "gemini", "gemini-test", False)
        seen = server.seen[0]
        assert seen["path"].endswith("/models/gemini-test:generateContent")
        assert seen["headers"]["x-goog-api-key"] == "KEY-GEM-123456"
        body = seen["body"]
        assert body["systemInstruction"]["parts"][0]["text"] == "SYS-PROMPT"
        assert body["contents"][0]["parts"][0]["text"] == "USER-TEXT"
        assert body["generationConfig"]["maxOutputTokens"] == 77
        assert body["generationConfig"]["responseMimeType"] == "application/json"

    def test_max_tokens_finish_reason_marks_truncated(self, server, gemini):
        server.script = [gemini_ok('{"a": [1', finish="MAX_TOKENS")]
        assert gemini.complete("m", REQ).truncated is True

    def test_thought_parts_are_not_returned_as_answer(self, server, gemini):
        parts = [{"text": "private reasoning", "thought": True}, {"text": '{"ok": true}'}]
        server.script = [
            (200, {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}]})
        ]
        assert gemini.complete("m", REQ).text == '{"ok": true}'

    def test_blocked_prompt_is_bad_request(self, server, gemini):
        server.script = [(200, {"promptFeedback": {"blockReason": "SAFETY"}})]
        with pytest.raises(AIBadRequest, match="SAFETY"):
            gemini.complete("m", REQ)

    @pytest.mark.parametrize(
        "status,message,exc",
        [
            (401, "unauthorized", AIAuthError),
            (403, "forbidden", AIAuthError),
            (400, "API key not valid. Please pass a valid API key.", AIAuthError),
            (404, "models/gone is not found for API version v1beta", AIModelNotFound),
            (429, "Resource has been exhausted (e.g. check quota).", AIRateLimited),
            (500, "internal", AIUnavailable),
            (503, "overloaded", AIUnavailable),
            (400, "Invalid JSON payload received.", AIBadRequest),
        ],
    )
    def test_error_mapping(self, server, gemini, status, message, exc):
        server.script = [(status, {"error": {"code": status, "message": message, "status": "X"}})]
        with pytest.raises(exc):
            gemini.complete("m", REQ)
        assert len(server.seen) == 1  # exactly one HTTP request: the SDK adds no hidden retries

    def test_timeout_is_unavailable(self, server):
        slow = GeminiProvider("KEY-GEM-123456", base_url=server.url, timeout_s=0.3)
        server.script = [(200, {}, {"sleep": 1.5})]
        with pytest.raises(AIUnavailable):
            slow.complete("m", REQ)

    def test_connection_refused_is_unavailable(self):
        dead = GeminiProvider("KEY-GEM-123456", base_url="http://127.0.0.1:9", timeout_s=2)
        with pytest.raises(AIUnavailable):
            dead.complete("m", REQ)


class TestGroq:
    def test_request_shape_and_success(self, server, groq):
        server.script = [groq_ok('{"a": 1}')]
        out = groq.complete("llama-test", REQ)
        assert (out.text, out.provider, out.model, out.truncated) == ('{"a": 1}', "groq", "llama-test", False)
        seen = server.seen[0]
        assert seen["path"].endswith("/chat/completions")
        assert seen["headers"]["authorization"] == "Bearer KEY-GROQ-123456"
        body = seen["body"]
        assert body["model"] == "llama-test" and body["max_tokens"] == 77
        assert body["messages"] == [
            {"role": "system", "content": "SYS-PROMPT"},
            {"role": "user", "content": "USER-TEXT"},
        ]
        assert body["response_format"] == {"type": "json_object"}

    def test_json_mode_can_be_disabled(self, server, groq):
        server.script = [groq_ok("plain text")]
        groq.complete("m", Request(system="s", user="u", json_mode=False))
        assert "response_format" not in server.seen[0]["body"]

    def test_length_finish_reason_marks_truncated(self, server, groq):
        server.script = [groq_ok('{"a": [1', finish="length")]
        assert groq.complete("m", REQ).truncated is True

    @pytest.mark.parametrize(
        "status,message,exc",
        [
            (401, "Invalid API Key", AIAuthError),
            (403, "forbidden", AIAuthError),
            (404, "The model `x` does not exist", AIModelNotFound),
            (400, "The model `llama-old` has been decommissioned", AIModelNotFound),
            (429, "Rate limit reached", AIRateLimited),
            (500, "oops", AIUnavailable),
            (400, "messages too long", AIBadRequest),
        ],
    )
    def test_error_mapping(self, server, groq, status, message, exc):
        server.script = [(status, {"error": {"message": message, "type": "t"}})]
        with pytest.raises(exc):
            groq.complete("m", REQ)
        assert len(server.seen) == 1

    def test_retry_after_header_is_parsed(self, server, groq):
        server.script = [(429, {"error": {"message": "slow down"}}, {"headers": {"retry-after": "7"}})]
        with pytest.raises(AIRateLimited) as ei:
            groq.complete("m", REQ)
        assert ei.value.retry_after == 7.0

    def test_empty_content_returns_empty_text_for_caller_to_reject(self, server, groq):
        server.script = [groq_ok("")]
        assert groq.complete("m", REQ).text == ""


class NoSleep(Clock):
    def __init__(self):
        self.t = 0.0
        super().__init__(
            sleep=lambda s: setattr(self, "t", self.t + s), monotonic=lambda: self.t, uniform=lambda a, b: 0.0
        )


def test_cascade_across_real_sdks_gemini_quota_then_groq(server):
    """Gemini exhausted (429 x3) -> falls through to Groq, which answers. Counts requests per route."""
    gem_server, groq_server = server, FakeServer()
    try:
        gem_server.script = [(429, {"error": {"message": "quota"}})] * 3
        groq_server.script = [groq_ok('{"name": "Priya"}')]
        client = AIClient(
            [Route(GeminiProvider("KEY-GEM-123456", base_url=gem_server.url, timeout_s=3), "g1"),
             Route(GroqProvider("KEY-GROQ-123456", base_url=groq_server.url, timeout_s=3), "l1")],
            RetryPolicy(base_delay=1.0), NoSleep(), secrets=("KEY-GEM-123456", "KEY-GROQ-123456"),
        )  # fmt: skip
        value, comp = client.structured(REQ, parse_json_object)
        assert value == {"name": "Priya"} and comp.provider == "groq"
        assert (len(gem_server.seen), len(groq_server.seen)) == (3, 1)
        assert client.clock.t == 3.0  # 1s + 2s backoff between the three Gemini attempts
    finally:
        groq_server.close()


def test_bad_keys_everywhere_raise_clear_error_and_leak_nothing(server):
    server.script = [(401, {"error": {"message": "bad key KEY-GEM-123456"}})]
    client = AIClient(
        [Route(GeminiProvider("KEY-GEM-123456", base_url=server.url, timeout_s=3), "g1")],
        RetryPolicy(), NoSleep(), secrets=("KEY-GEM-123456",),
    )  # fmt: skip
    with pytest.raises(AIExhausted) as ei:
        client.complete(REQ)
    assert "rejected the API key" in str(ei.value) and "KEY-GEM" not in str(ei.value)


def test_full_extraction_through_the_real_groq_sdk(server, fixture_text):
    """Document text -> real Groq SDK -> fake server -> grounded Profile. One request, injection line never sent."""
    from careerforge.ai.extract import extract_profile

    reply = {
        "name": "Arjun Mehta", "contact": {"email": "arjun.mehta@example.com", "github": "github.com/arjun-demo"},
        "skills": ["Python", "React", "Rust"],
        "education": [{"degree": "B.Tech Information Technology", "institution": "Demo Institute of Technology", "start": "2021", "end": "2025"}],
        "projects": [{"name": "Expense Tracker", "tech": ["React", "Node.js", "MongoDB"], "bullets": ["Built a full-stack web app to track expenses with charts."]}],
    }  # fmt: skip
    server.script = [groq_ok(json.dumps(reply))]
    client = AIClient([Route(GroqProvider("KEY-GROQ-123456", base_url=server.url, timeout_s=3), "llama-test")],
                      RetryPolicy(), NoSleep())  # fmt: skip
    res = extract_profile(client, fixture_text("cv_fresher.txt"))
    assert len(server.seen) == 1
    sent = server.seen[0]["body"]
    assert sent["temperature"] == 0.0 and "<source>" in sent["messages"][1]["content"]
    assert res.profile.name == "Arjun Mehta" and "Rust" not in res.profile.skills  # 'Rust' is not in the document
    assert [f.text for f in res.grounding.of("skill")] == ["Rust"]
