"""Model ranking, discovery, quota handling and the doctor command (real SDKs, fake HTTP server)."""

import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from careerforge.ai import models as model_mod
from careerforge.ai.client import AIClient, Clock, RetryPolicy, Route, build_client
from careerforge.ai.doctor import main as doctor_main
from careerforge.ai.doctor import run as doctor_run
from careerforge.ai.errors import AIAuthError, AIExhausted, AIQuotaExhausted, AIRateLimited
from careerforge.ai.models import discover, rank_gemini, rank_groq
from careerforge.ai.providers import GeminiProvider, GroqProvider, Request
from careerforge.ai.settings import AISettings, load_settings


@pytest.fixture(autouse=True)
def _fresh_cache():
    model_mod.clear_cache()
    yield
    model_mod.clear_cache()


class TestRankGemini:
    def test_stable_flash_first_newer_version_wins_previews_last(self):
        names = ["models/gemini-2.5-pro", "models/gemini-3-flash-preview", "models/gemini-2.5-flash-lite", "models/gemini-3-flash",
                 "models/gemini-2.5-flash", "models/gemini-flash-latest", "models/gemini-2.5-flash-001", "models/gemini-3-pro"]  # fmt: skip
        assert rank_gemini(names) == ["gemini-3-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-pro",
                                      "gemini-2.5-pro", "gemini-flash-latest", "gemini-2.5-flash-001", "gemini-3-flash-preview"]  # fmt: skip

    @pytest.mark.parametrize("name", ["gemini-2.5-flash-image", "gemini-2.5-flash-preview-tts", "gemini-embedding-001",
                                      "gemini-2.0-flash-live-001", "imagen-4.0-generate", "veo-3", "gemma-3-27b-it",
                                      "text-embedding-004", "gemini-2.5-computer-use-preview", "aqa", "gemini-exp-1206"])  # fmt: skip
    def test_non_text_or_unsuitable_models_excluded(self, name):
        assert rank_gemini([name]) == []

    def test_dedupes_and_ignores_prefix(self):
        assert rank_gemini(["models/gemini-2.5-flash", "gemini-2.5-flash"]) == ["gemini-2.5-flash"]

    def test_empty(self):
        assert rank_gemini([]) == []


class TestRankGroq:
    def test_preference_then_context_window_and_exclusions(self):
        models = [
            {"id": "whisper-large-v3", "active": True, "context_window": 448},
            {"id": "llama-3.1-8b-instant", "active": True, "context_window": 131072},
            {"id": "openai/gpt-oss-120b", "active": True, "context_window": 131072},
            {"id": "llama-3.3-70b-versatile", "active": True, "context_window": 131072},
            {"id": "meta-llama/llama-guard-4-12b", "active": True, "context_window": 131072},
            {"id": "groq/compound", "active": True, "context_window": 131072},
            {"id": "old-model", "active": False, "context_window": 131072},
            {"id": "tiny-model", "active": True, "context_window": 4096},
            {"id": "some-new-family", "active": True, "context_window": 262144},
            {"id": "playai-tts", "active": True},
        ]
        assert rank_groq(models) == [
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-120b",
            "llama-3.1-8b-instant",
            "some-new-family",
        ]

    def test_missing_fields_tolerated(self):
        assert rank_groq([{"id": "llama-3.3-70b-versatile"}, {"id": ""}, {}]) == ["llama-3.3-70b-versatile"]


# ── fake server serving both model lists and generation ──────────────────────


class Api:
    def __init__(self, routes):
        self.routes, self.seen = routes, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("content-length", 0) or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                outer.seen.append((self.command, self.path, body))
                key = (self.command, self.path.split("?")[0])
                step = outer.routes.get(key, (404, {"error": {"message": "no route"}}))
                if isinstance(step, list):
                    step = step.pop(0) if len(step) > 1 else step[0]
                status, payload = step
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def api():
    made = []

    def make(routes):
        a = Api(routes)
        made.append(a)
        return a

    yield make
    for a in made:
        a.close()


def gem_models(*names, field="supportedGenerationMethods", methods=("generateContent",)):
    return (200, {"models": [{"name": f"models/{n}", field: list(methods)} for n in names]})


GEN_OK = (
    200,
    {"candidates": [{"content": {"role": "model", "parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}]},
)


def groq_gen(text='{"ok": true}'):
    return (200, {"id": "x", "object": "chat.completion", "created": 1, "model": "m", "usage": {"total_tokens": 1},
                  "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]})  # fmt: skip


class TestProviderListing:
    def test_gemini_listing_filters_by_generate_content_and_follows_pages(self, api):
        a = api({("GET", "/v1beta/models"): [
            (200, {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                              {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]}],
                   "nextPageToken": "p2"}),
            gem_models("gemini-3-flash"),
        ]})  # fmt: skip
        names = GeminiProvider("KEY-GEM-123456", base_url=a.url, timeout_s=3).list_models()
        assert "gemini-2.5-flash" in names and "gemini-3-flash" in names and "text-embedding-004" not in names

    def test_gemini_sdk_field_name_actually_parsed(self, api):
        """Guards the assumption the filter relies on: the SDK maps the REST field to supported_actions."""
        a = api({("GET", "/v1beta/models"): gem_models("only-embed", methods=("embedContent",))})
        assert GeminiProvider("KEY-GEM-123456", base_url=a.url, timeout_s=3).list_models() == []

    def test_groq_listing_exposes_active_and_context(self, api):
        a = api({("GET", "/openai/v1/models"): (200, {"object": "list", "data": [
            {"id": "llama-3.3-70b-versatile", "object": "model", "created": 1, "owned_by": "Meta", "active": True, "context_window": 131072},
            {"id": "mystery", "object": "model", "created": 1, "owned_by": "x"}]})})  # fmt: skip
        got = GroqProvider("KEY-GROQ-123456", base_url=a.url, timeout_s=3).list_models()
        assert got[0] == {"id": "llama-3.3-70b-versatile", "active": True, "context_window": 131072}
        assert got[1]["id"] == "mystery" and got[1]["active"] is True

    def test_listing_errors_use_the_error_hierarchy(self, api):
        a = api({("GET", "/v1beta/models"): (403, {"error": {"message": "denied"}})})
        with pytest.raises(AIAuthError):
            GeminiProvider("KEY-GEM-123456", base_url=a.url, timeout_s=3).list_models()


class TestDiscoveryAndBuildClient:
    def settings(self, g=None, q=None, **kw):
        return AISettings(gemini_api_key="KEY-GEM-123456" if g else "", groq_api_key="KEY-GROQ-123456" if q else "",
                          gemini_base_url=g.url if g else None, groq_base_url=q.url if q else None, timeout_s=3, **kw)  # fmt: skip

    def test_routes_come_from_discovery_best_first_capped_at_five_per_provider(self, api):
        g = api(
            {
                ("GET", "/v1beta/models"): gem_models(
                    "gemini-2.5-pro",
                    "gemini-3-flash",
                    "gemini-2.5-flash",
                    "gemini-2.5-flash-lite",
                    "gemini-3-flash-preview",
                )
            }
        )
        q = api({("GET", "/openai/v1/models"): (200, {"object": "list", "data": [
            {"id": "llama-3.1-8b-instant", "object": "model", "created": 1, "owned_by": "x", "active": True, "context_window": 131072},
            {"id": "llama-3.3-70b-versatile", "object": "model", "created": 1, "owned_by": "x", "active": True, "context_window": 131072}]})})  # fmt: skip
        client = build_client(self.settings(g, q))
        assert [str(r) for r in client.routes] == [
            "gemini/gemini-3-flash", "gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash-lite", "gemini/gemini-2.5-pro",
            "gemini/gemini-3-flash-preview", "groq/llama-3.3-70b-versatile", "groq/llama-3.1-8b-instant",
        ]  # fmt: skip
        assert client.notes == []

    def test_user_pinned_models_skip_discovery_entirely(self, api):
        g = api({})
        client = build_client(self.settings(g, gemini_models=("my-model",)))
        assert [str(r) for r in client.routes] == ["gemini/my-model"] and g.seen == []

    def test_discovery_failure_falls_back_with_a_visible_note(self, api):
        g = api({("GET", "/v1beta/models"): (500, {"error": {"message": "down"}})})
        client = build_client(self.settings(g))
        assert [str(r) for r in client.routes][0].startswith("gemini/gemini-2.5") and len(client.routes) == 2
        assert any("Could not list Gemini" in n for n in client.notes) and any("unverified" in n for n in client.notes)

    def test_discovery_is_cached(self, api):
        g = api({("GET", "/v1beta/models"): gem_models("gemini-3-flash")})
        s = self.settings(g)
        build_client(s)
        build_client(s)
        assert sum(1 for m, p, _ in g.seen if m == "GET") == 1

    def test_cache_expires(self, api):
        g = api({("GET", "/v1beta/models"): gem_models("gemini-3-flash")})
        clock = [0.0]
        p = GeminiProvider("KEY-GEM-123456", base_url=g.url, timeout_s=3)
        discover(p, None, now=lambda: clock[0])
        clock[0] = model_mod.CACHE_TTL_S + 1
        discover(p, None, now=lambda: clock[0])
        assert sum(1 for m, _, _ in g.seen if m == "GET") == 2

    def test_empty_listing_noted(self, api):
        g = api({("GET", "/v1beta/models"): gem_models("gemini-embedding-001")})
        d = discover(GeminiProvider("KEY-GEM-123456", base_url=g.url, timeout_s=3), None)
        assert d.gemini == () and "no usable text models" in d.notes[0]

    def test_end_to_end_a_model_without_free_quota_is_skipped_quickly(self, api):
        """First discovered model has zero free quota (429, daily): no retries, next model answers."""
        g = api({("GET", "/v1beta/models"): gem_models("gemini-3-flash", "gemini-2.5-flash"),
                 ("POST", "/v1beta/models/gemini-3-flash:generateContent"): (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                     "message": "Quota exceeded for metric generate_content_free_tier_requests, limit: 0"}}),
                 ("POST", "/v1beta/models/gemini-2.5-flash:generateContent"): GEN_OK})  # fmt: skip
        client = build_client(
            self.settings(g), clock=Clock(sleep=lambda s: pytest.fail("must not back off"), monotonic=lambda: 0.0)
        )
        out = client.complete(Request(system="s", user="u"))
        assert out.model == "gemini-2.5-flash"
        assert sum(1 for m, p, _ in g.seen if m == "POST" and "gemini-3-flash" in p) == 1


class TestQuotaClassification:
    @pytest.mark.parametrize("message,exc", [
        ("Quota exceeded for metric x, limit: 0", AIQuotaExhausted),
        ("Rate limit reached for model on requests per day (RPD): Limit 1000, Used 1000", AIQuotaExhausted),
        ("Rate limit reached ... tokens per day (TPD): Limit 100000", AIQuotaExhausted),
        ("You exceeded your daily quota", AIQuotaExhausted),
        ("Rate limit reached on requests per minute (RPM): Limit 30", AIRateLimited),
        ("Resource has been exhausted (e.g. check quota).", AIRateLimited),
    ])  # fmt: skip
    def test_daily_or_zero_quota_is_not_retried_per_minute_limits_are(self, message, exc):
        from careerforge.ai.providers import _classify_status

        assert type(_classify_status(429, message)) is exc


class TestDoctor:
    def routes(self, gen_status=200):
        return {
            ("GET", "/v1beta/models"): gem_models("gemini-3-flash", "gemini-2.5-flash"),
            ("POST", "/v1beta/models/gemini-3-flash:generateContent"): GEN_OK if gen_status == 200 else (429, {"error": {"message": "limit: 0"}}),
            ("POST", "/v1beta/models/gemini-2.5-flash:generateContent"): GEN_OK,
            ("GET", "/openai/v1/models"): (200, {"object": "list", "data": [{"id": "llama-3.3-70b-versatile", "object": "model", "created": 1, "owned_by": "x", "active": True, "context_window": 131072}]}),
            ("POST", "/openai/v1/chat/completions"): groq_gen(),
        }  # fmt: skip

    def test_reports_working_models_and_paste_ready_settings(self, api):
        a = api(self.routes())
        s = AISettings(
            gemini_api_key="KEY-GEM-123456",
            groq_api_key="KEY-GROQ-123456",
            gemini_base_url=a.url,
            groq_base_url=a.url,
            timeout_s=3,
        )
        out = io.StringIO()
        assert doctor_run(s, out=out) == 0
        text = out.getvalue()
        assert "OK   gemini-3-flash" in text and "CAREERFORGE_GEMINI_MODELS=gemini-3-flash,gemini-2.5-flash" in text
        assert "CAREERFORGE_GROQ_MODELS=llama-3.3-70b-versatile" in text and "KEY-" not in text

    def test_failures_are_shown_and_excluded_from_the_suggestion(self, api):
        a = api(self.routes(gen_status=429))
        s = AISettings(gemini_api_key="KEY-GEM-123456", gemini_base_url=a.url, timeout_s=3)
        out = io.StringIO()
        assert doctor_run(s, out=out) == 0
        text = out.getvalue()
        assert "FAIL gemini-3-flash" in text and "CAREERFORGE_GEMINI_MODELS=gemini-2.5-flash\n" in text

    def test_nothing_working_returns_1_and_no_key_returns_2(self, api):
        a = api(
            {
                ("GET", "/v1beta/models"): gem_models("gemini-3-flash"),
                ("POST", "/v1beta/models/gemini-3-flash:generateContent"): (403, {"error": {"message": "no"}}),
            }
        )
        out = io.StringIO()
        assert doctor_run(AISettings(gemini_api_key="KEY-GEM-123456", gemini_base_url=a.url, timeout_s=3), out=out) == 1
        assert "No model answered" in out.getvalue()
        out2 = io.StringIO()
        assert doctor_run(AISettings(), out=out2) == 2 and "No API key" in out2.getvalue()

    def test_listing_failure_is_reported_without_leaking_the_key(self, api):
        a = api({("GET", "/v1beta/models"): (401, {"error": {"message": "bad KEY-GEM-123456"}})})
        out = io.StringIO()
        doctor_run(AISettings(gemini_api_key="KEY-GEM-123456", gemini_base_url=a.url, timeout_s=3), out=out)
        assert "Could not list models" in out.getvalue() and "KEY-GEM" not in out.getvalue()

    def test_cli_reads_secrets_file_and_env(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        (tmp_path / "s.toml").write_text('GEMINI_API_KEY = "KEY-FROM-FILE-123"\n')
        # no reachable server: must fail cleanly (listing error), not crash
        assert doctor_main(["--secrets", str(tmp_path / "s.toml"), "--top", "1"]) in (0, 1)
        assert "KEY-FROM-FILE" not in capsys.readouterr().out
        assert doctor_main(["--secrets", str(tmp_path / "missing.toml")]) == 2

    def test_load_settings_pins_from_env(self):
        s = load_settings({}, {"GROQ_API_KEY": "k", "CAREERFORGE_GROQ_MODELS": "a,b"})
        assert s.groq_models == ("a", "b") and s.gemini_models == ()


def test_discovery_does_not_block_startup_for_long(api):
    """A dead provider must not hang the app: connection refused returns quickly with a note."""
    start = time.monotonic()
    d = discover(GeminiProvider("KEY-GEM-123456", base_url="http://127.0.0.1:9", timeout_s=2), None)
    assert time.monotonic() - start < 5 and d.gemini == () and "Could not list" in d.notes[0]
    assert RetryPolicy().deadline_s >= 30  # unrelated sanity: cascade deadline is a separate bound


class TestRemembersDeadRoutes:
    """A model that is gone or out of quota is skipped for a while, so each request does not first fail on it."""

    def client(self, *replies, now=None):
        from helpers import ScriptedProvider

        provider = ScriptedProvider(*replies)
        t = now or [0.0]
        clock = Clock(sleep=lambda s: None, monotonic=lambda: t[0], uniform=lambda a, b: 0.0)
        routes = [Route(provider, "gone"), Route(provider, "ok")]
        return AIClient(routes, RetryPolicy(), clock), provider, t

    REQ = Request(system="s", user="u")

    def test_a_missing_model_is_not_asked_again_for_an_hour(self):
        from careerforge.ai.errors import AIModelNotFound

        client, provider, t = self.client(AIModelNotFound("no such model"), "a", "b", "c", "d")
        assert client.complete(self.REQ).model == "ok" and len(provider.requests) == 2
        assert client.complete(self.REQ).model == "ok" and len(provider.requests) == 3  # the gone one was skipped
        t[0] = 3599
        assert client.complete(self.REQ).model == "ok" and len(provider.requests) == 4
        t[0] = 3601  # the hour is over: it is tried again (and answers this time)
        assert client.complete(self.REQ).model == "gone"

    def test_a_model_out_of_quota_is_skipped_for_ten_minutes(self):
        from careerforge.ai.errors import AIQuotaExhausted

        client, provider, t = self.client(AIQuotaExhausted("daily"), "a", "b", "c")
        client.complete(self.REQ)
        t[0] = 599
        client.complete(self.REQ)
        assert len(provider.requests) == 3
        t[0] = 601
        assert client.complete(self.REQ).model == "gone"

    def test_when_every_route_is_marked_dead_they_are_tried_again_not_refused(self):
        from careerforge.ai.errors import AIModelNotFound

        client, provider, _ = self.client(AIModelNotFound("x"), AIModelNotFound("y"), "fine")
        with pytest.raises(AIExhausted):
            client.complete(self.REQ)
        assert client.complete(self.REQ).text == "fine"

    def test_a_retryable_failure_is_not_remembered(self):
        from careerforge.ai.errors import AIUnavailable

        client, provider, _ = self.client(*([AIUnavailable("busy")] * 3), "a", "b")
        client.complete(self.REQ)
        assert client.skip_until == {}


class TestCheckRoutes:
    def test_every_route_is_probed_and_reported_with_its_reason(self):
        from helpers import ScriptedProvider

        from careerforge.ai.doctor import check_routes
        from careerforge.ai.errors import AIModelNotFound

        provider = ScriptedProvider('{"ok": true}', AIModelNotFound("gone KEY-SECRET-1234"), "not json")
        clock = Clock(sleep=lambda s: None, monotonic=lambda: 0.0, uniform=lambda a, b: 0.0)
        client = AIClient(
            [Route(provider, "a"), Route(provider, "b"), Route(provider, "c")],
            RetryPolicy(),
            clock,
            ("KEY-SECRET-1234",),
        )
        checks = check_routes(client)
        assert [(c.route, c.ok) for c in checks] == [("fake/a", True), ("fake/b", False), ("fake/c", False)]
        assert "KEY-SECRET-1234" not in " ".join(c.detail for c in checks)  # keys never reach the screen
        assert all(c.seconds >= 0 for c in checks)


class TestProviderErrorPaths:
    """Error mapping on the paths the happy-path tests do not reach (real SDKs against a local fake server)."""

    GROQ_LIST = ("GET", "/openai/v1/models")
    GROQ_CHAT = ("POST", "/openai/v1/chat/completions")

    @pytest.mark.parametrize(
        "status,error",
        [
            (401, "AIAuthError"),
            (403, "AIAuthError"),
            (429, "AIRateLimited"),
            (500, "AIUnavailable"),
            (404, "AIModelNotFound"),
        ],
    )
    def test_groq_model_listing_maps_http_errors(self, api, status, error):
        from careerforge.ai import errors

        q = api({self.GROQ_LIST: (status, {"error": {"message": "nope"}})})
        with pytest.raises(getattr(errors, error)):
            GroqProvider("KEY-GROQ-123456", base_url=q.url, timeout_s=3).list_models()

    def test_groq_model_listing_when_the_service_is_unreachable(self):
        from careerforge.ai.errors import AIUnavailable

        with pytest.raises(AIUnavailable, match="Network problem"):
            GroqProvider("KEY-GROQ-123456", base_url="http://127.0.0.1:9", timeout_s=1).list_models()

    def test_groq_completion_when_the_service_is_unreachable(self):
        from careerforge.ai.errors import AIUnavailable

        with pytest.raises(AIUnavailable, match="Network problem"):
            GroqProvider("KEY-GROQ-123456", base_url="http://127.0.0.1:9", timeout_s=1).complete("m", Request("s", "u"))

    def test_groq_answer_with_no_choices_is_a_bad_request_not_an_empty_success(self, api):
        from careerforge.ai.errors import AIBadRequest

        q = api(
            {self.GROQ_CHAT: (200, {"id": "x", "object": "chat.completion", "created": 1, "model": "m", "choices": []})}
        )
        with pytest.raises(AIBadRequest, match="no answer"):
            GroqProvider("KEY-GROQ-123456", base_url=q.url, timeout_s=3).complete("m", Request("s", "u"))

    def test_gemini_refusal_without_text_is_reported_as_a_refusal(self, api):
        from careerforge.ai.errors import AIBadRequest

        body = {"candidates": [{"content": {"role": "model", "parts": []}, "finishReason": "SAFETY"}]}
        g = api({("POST", "/v1beta/models/m:generateContent"): (200, body)})
        with pytest.raises(AIBadRequest, match="declined"):
            GeminiProvider("KEY-GEM-123456", base_url=g.url, timeout_s=3).complete("m", Request("s", "u"))

    @pytest.mark.parametrize("header,expected", [("7", 7.0), ("500", 120.0), ("soon", None), (None, None)])
    def test_retry_after_is_parsed_capped_and_never_trusted_blindly(self, header, expected):
        from careerforge.ai.providers import _retry_after

        assert _retry_after({} if header is None else {"retry-after": header}) == expected
        assert _retry_after(object()) is None
