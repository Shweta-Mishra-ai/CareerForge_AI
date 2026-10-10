"""Job providers against a fake server (shapes from the original app's observed responses; NOT live-verified)."""

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_grounding import faithful_standard

from careerforge import jobs as J
from careerforge.jobs import (
    AdzunaProvider,
    JobicyProvider,
    ProviderError,
    RemotiveProvider,
    rank_jobs,
    search_all,
    suggest_queries,
)
from careerforge.models import Profile

TODAY = date(2026, 10, 10)


class Api:
    def __init__(self, routes):
        self.routes, self.seen = routes, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen.append(self.path)
                status, body = outer.routes.get(self.path.split("?")[0], (404, {}))
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

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
        made.append(Api(routes))
        return made[-1]

    yield make
    for a in made:
        a.close()


@pytest.fixture(autouse=True)
def _clean_cache():
    J.clear_cache()
    yield
    J.clear_cache()


REMOTIVE = {"jobs": [
    {"title": "Senior Python Developer", "company_name": "Acme", "candidate_required_location": "Worldwide", "job_type": "full_time",
     "salary": "$100k", "tags": ["Python", "Django", 5], "description": "<p>Build <b>APIs</b> with Python, Django and PostgreSQL.</p><ul><li>Kafka</li></ul><script>x()</script>",
     "url": "https://remotive.com/remote-jobs/1", "publication_date": "2026-10-01T10:00:00"},
    {"title": "Bad Url Job", "company_name": "Evil", "url": "javascript:alert(1)", "description": ""},
    {"company_name": "No Title"}, "junk",
]}  # fmt: skip
JOBICY = {"jobs": [{"jobTitle": "Backend Engineer", "companyName": "Beta", "jobGeo": "EMEA", "jobType": ["Full-Time"], "annualSalaryMin": 90000,
                    "jobDescription": "Python and Kafka services", "url": "https://jobicy.com/jobs/2", "pubDate": "2026-10-02 08:00:00"}]}  # fmt: skip
ADZUNA = {"results": [{"title": "Data Engineer", "company": {"display_name": "Gamma"}, "location": {"display_name": "Pune"}, "description": "SQL and Python",
                       "redirect_url": "https://www.adzuna.in/land/ad/3", "created": "2026-10-03T00:00:00Z", "salary_min": 500000.0, "salary_max": 900000.0}]}  # fmt: skip


class TestProviders:
    def test_remotive_maps_and_sanitises(self, api):
        a = api({"/api/remote-jobs": (200, REMOTIVE)})
        jobs = RemotiveProvider(base_url=a.url).search("python", 10)
        assert [j.title for j in jobs] == ["Senior Python Developer", "Bad Url Job"]
        first = jobs[0]
        assert first.company == "Acme" and first.posted == "2026-10-01" and first.tags == ("python", "django")
        assert (
            "script" not in first.description
            and "x()" not in first.description
            and "Build APIs with Python" in first.description
        )
        assert "• " not in first.description and "Kafka" in first.description
        assert jobs[1].url == ""  # javascript: link dropped
        assert "search=python" in a.seen[0] and "limit=10" in a.seen[0]

    def test_jobicy_and_adzuna(self, api):
        a = api({"/api/v2/remote-jobs": (200, JOBICY), "/v1/api/jobs/in/search/1": (200, ADZUNA)})
        (j,) = JobicyProvider(base_url=a.url).search("python", 5)
        assert (j.title, j.location, j.type, j.salary, j.posted) == (
            "Backend Engineer",
            "Remote - EMEA",
            "Full-Time",
            "90000",
            "2026-10-02",
        )
        (z,) = AdzunaProvider("id", "key", base_url=a.url).search("data", 5)
        assert (z.company, z.location, z.salary, z.source) == ("Gamma", "Pune", "500000-900000", "Adzuna")
        assert "app_id=id" in a.seen[-1] and "what=data" in a.seen[-1]

    def test_adzuna_refuses_to_run_without_keys_instead_of_sending_empty_ones(self):
        for args in (("", ""), ("id", ""), ("", "key")):
            with pytest.raises(ValueError):
                AdzunaProvider(*args)

    @pytest.mark.parametrize(
        "status,msg", [(429, "rate-limiting"), (403, "API key"), (500, "error"), (404, "not found")]
    )
    def test_http_errors_become_provider_errors(self, api, status, msg):
        a = api({"/api/remote-jobs": (status, {})})
        with pytest.raises(ProviderError, match=msg):
            RemotiveProvider(base_url=a.url).search("x", 5)

    @pytest.mark.parametrize("body", [b"<html>", b"[1,2]", b'{"jobs": "nope"}', b'{"other": 1}'])
    def test_garbage_responses_are_provider_errors(self, api, body):
        a = api({"/api/remote-jobs": (200, body)})
        with pytest.raises(ProviderError):
            RemotiveProvider(base_url=a.url).search("x", 5)

    def test_unreachable_and_oversized(self, api):
        with pytest.raises(ProviderError, match="could not be reached"):
            RemotiveProvider(base_url="http://127.0.0.1:9", timeout=1).search("x", 5)
        a = api({"/api/remote-jobs": (200, b'{"jobs": [], "pad": "' + b"x" * 2_100_000 + b'"}')})
        with pytest.raises(ProviderError, match="large"):
            RemotiveProvider(base_url=a.url).search("x", 5)

    def test_hostile_text_is_inert_plain_text(self, api):
        evil = {
            "jobs": [
                {
                    "title": "<img src=x onerror=alert(1)>",
                    "description": "<script>steal()</script>‮Text",
                    "url": "https://ok.example/1",
                }
            ]
        }
        (j,) = RemotiveProvider(base_url=api({"/api/remote-jobs": (200, evil)}).url).search("x", 5)
        assert "steal" not in j.description and "‮" not in j.description and j.title == "<img src=x onerror=alert(1)>"


class Fake:
    def __init__(self, name, jobs=(), error=None):
        self.name, self.jobs, self.error, self.calls = name, list(jobs), error, 0

    def search(self, query, limit):
        self.calls += 1
        if self.error:
            raise ProviderError(self.error)
        return self.jobs


def job(title, company, url="https://x.example/1", desc="", source="A"):
    return J.Job(title, company, "Remote", desc, url, source)


class TestSearchAll:
    def test_one_failing_provider_does_not_hide_the_others(self):
        res = search_all([Fake("A", [job("Dev", "X")]), Fake("B", error="B is down")], "dev")
        assert len(res.jobs) == 1 and res.errors == {"B": "B is down"}

    def test_duplicates_across_sources_and_urlless_jobs_are_removed(self):
        res = search_all(
            [Fake("A", [job("Dev", "X")]), Fake("B", [job("dev", "x", source="B"), job("Ops", "Y", url="")])], "dev"
        )
        assert [(j.title, j.source) for j in res.jobs] == [("Dev", "A")]

    def test_results_are_cached_for_an_hour_then_refetched(self):
        p, t = Fake("A", [job("Dev", "X")]), [0.0]
        search_all([p], "Dev", now=lambda: t[0])
        search_all([p], "dev", now=lambda: t[0] + 10)
        assert p.calls == 1
        search_all([p], "dev", now=lambda: t[0] + J.CACHE_TTL_S + 1)
        assert p.calls == 2

    def test_errors_are_not_cached(self):
        p = Fake("A", error="down")
        search_all([p], "dev")
        search_all([p], "dev")
        assert p.calls == 2

    def test_blank_query_does_nothing(self):
        p = Fake("A", [job("Dev", "X")])
        assert search_all([p], "   ").jobs == () and p.calls == 0


class TestRanking:
    P = faithful_standard()
    GOOD = job(
        "Senior Backend Engineer", "A", desc="Requirements: Python, Kafka, PostgreSQL, Redis and Kubernetes experience."
    )
    BAD = job("Graphic Designer", "B", desc="Requirements: Photoshop, Illustrator, Figma and typography.")

    def test_relevant_jobs_rank_first_with_evidence(self):
        ranked = rank_jobs(self.P, [self.BAD, self.GOOD])
        assert [r.job.company for r in ranked] == ["A", "B"] and ranked[0].score >= 80 and ranked[1].score < 30
        assert {"Python", "Kafka"} <= set(ranked[0].matched) and "Figma" in ranked[1].missing

    def test_min_score_filters(self):
        assert [r.job.company for r in rank_jobs(self.P, [self.BAD, self.GOOD], min_score=50)] == ["A"]

    def test_skills_part_is_the_ats_keyword_score(self):
        from datetime import date

        from careerforge.ats.report import analyze

        text = f"{self.GOOD.title}\n{self.GOOD.description}"
        kw = analyze(self.P, text, today=date(2026, 10, 10)).component("keywords").score
        skills = next(x for x in rank_jobs(self.P, [self.GOOD])[0].parts if x.key == "skills")
        assert skills.score == kw

    def test_score_is_renormalised_when_the_job_title_gives_no_role_signal(self):
        titleless = job("Senior", "T", desc="Requirements: Python")  # a seniority word only: no role signal
        with_title = job("Backend Engineer", "T", desc="Requirements: Python")
        r = rank_jobs(self.P, [titleless], today=TODAY)[0]
        role = next(x for x in r.parts if x.key == "role")
        usable = [x for x in r.parts if x.score is not None]
        assert role.score is None
        assert r.score == round(sum(x.weight * x.score for x in usable) / sum(x.weight for x in usable))
        assert rank_jobs(self.P, [with_title], today=TODAY)[0].score > 0

    def test_jobs_with_no_extractable_requirements_get_a_finite_score(self):
        r = rank_jobs(self.P, [job("Cook", "C", desc="Come and enjoy our kitchen.")])
        assert 0 <= r[0].score <= 100


def test_suggest_queries_come_from_the_cv_without_duplicates():
    assert suggest_queries(faithful_standard())[:2] == ["Senior Backend Engineer", "Software Engineer"]
    assert suggest_queries(Profile()) == []
