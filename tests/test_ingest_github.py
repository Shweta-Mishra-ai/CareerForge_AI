import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from careerforge.ingest.errors import FetchFailed, IngestError
from careerforge.ingest.github import fetch_github, merge_github, parse_github_user
from careerforge.models import Contact, Profile, Project

USER = {"login": "priya-demo", "name": "Priya Nair", "bio": "Backend engineer", "location": "Bengaluru, India",
        "blog": "priya.dev", "company": "@finlytics", "public_repos": 5, "followers": 42}  # fmt: skip


def repo(name, stars=0, lang="Python", topics=(), fork=False, archived=False, desc="", pushed="2025-01-01T00:00:00Z"):
    return {"name": name, "description": desc or None, "language": lang, "stargazers_count": stars, "fork": fork,
            "archived": archived, "topics": list(topics), "pushed_at": pushed, "html_url": f"https://github.com/priya-demo/{name}"}  # fmt: skip


REPOS = [repo("tracker", 30, "TypeScript", ["react", "hacktoberfest"], desc="Expense tracker"), repo("etl-tool", 5, "Python", ["airflow"]),
         repo("fork-of-big", 9000, "Go", fork=True), repo("old-thing", 100, "Java", archived=True),
         repo("priya-demo", 1, "Markdown"), repo("dotfiles", 0, "Shell")]  # fmt: skip


class Api:
    def __init__(self, routes):
        self.routes, self.seen = routes, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen.append(
                    {"path": self.path, "auth": self.headers.get("Authorization"), "ua": self.headers.get("User-Agent")}
                )
                status, headers, body = outer.routes.get(self.path.split("?")[0], (404, {}, {"message": "Not Found"}))
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
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
        a = Api(routes)
        made.append(a)
        return a

    yield make
    for a in made:
        a.close()


def ok_routes(user=USER, repos=REPOS):
    return {"/users/priya-demo": (200, {}, user), "/users/priya-demo/repos": (200, {}, repos)}


class TestParse:
    @pytest.mark.parametrize("raw", ["priya-demo", "@priya-demo", "github.com/priya-demo", "https://github.com/priya-demo/",
                                     "https://www.github.com/priya-demo/some-repo/issues", " priya-demo "])  # fmt: skip
    def test_accepts(self, raw):
        assert parse_github_user(raw) == "priya-demo"

    @pytest.mark.parametrize("raw", ["", "https://gitlab.com/x", "https://evil.com/github.com/x", "-bad", "bad-", "a--b",
                                     "x" * 40, "has space", "github.com/orgs/foo", "github.com/", "../etc", "user/../x?"])  # fmt: skip
    def test_rejects(self, raw):
        with pytest.raises(IngestError):
            parse_github_user(raw)


class TestFetch:
    def test_projects_exclude_forks_archived_and_profile_readme_ranked_by_stars(self, api):
        a = api(ok_routes())
        imp = fetch_github("priya-demo", base_url=a.url)
        assert [p.name for p in imp.projects] == ["tracker", "etl-tool", "dotfiles"]
        assert imp.projects[0].description == "Expense tracker" and imp.projects[0].stars == 30
        assert imp.projects[0].url == "https://github.com/priya-demo/tracker"
        assert (imp.name, imp.location, imp.website, imp.followers) == (
            "Priya Nair",
            "Bengaluru, India",
            "https://priya.dev",
            42,
        )

    def test_no_invented_descriptions_or_skills_from_noise(self, api):
        imp = fetch_github("priya-demo", base_url=api(ok_routes()).url)
        assert imp.projects[1].description == ""  # old code wrote "A Python project"
        assert imp.projects[0].tech == ["TypeScript", "React"]  # 'hacktoberfest' is not a skill
        assert all(p.origin == "extracted" for p in imp.projects)

    def test_languages_are_suggestions_ordered_by_use_and_filtered_to_known_skills(self, api):
        imp = fetch_github("priya-demo", base_url=api(ok_routes()).url)
        assert imp.languages[0] in ("TypeScript", "Python") and "Go" not in imp.languages  # Go only came from a fork
        assert "Markdown" not in imp.languages

    def test_name_is_never_guessed_from_the_username(self, api):
        imp = fetch_github("priya-demo", base_url=api(ok_routes({**USER, "name": None})).url)
        assert imp.name == ""

    def test_token_sent_only_when_given(self, api):
        a = api(ok_routes())
        fetch_github("priya-demo", base_url=a.url)
        fetch_github("priya-demo", base_url=a.url, token="ghp_secret")
        assert (
            a.seen[0]["auth"] is None and a.seen[2]["auth"] == "Bearer ghp_secret" and "CareerForge" in a.seen[0]["ua"]
        )

    def test_over_100_repos_warns(self, api):
        imp = fetch_github("priya-demo", base_url=api(ok_routes({**USER, "public_repos": 340})).url)
        assert "340" in imp.warnings[0]

    def test_hostile_values_are_neutralised(self, api):
        evil = [{**repo("ok"), "description": "x‮<script>alert(1)</script>" + "y" * 900, "html_url": "javascript:alert(1)",
                 "stargazers_count": "lots", "topics": [5, None, "python"]}]  # fmt: skip
        imp = fetch_github("priya-demo", base_url=api(ok_routes({**USER, "blog": "javascript:alert(1)"}, evil)).url)
        p = imp.projects[0]
        assert len(p.description) <= 600 and "‮" not in p.description and p.url == "" and p.stars == 0
        assert imp.website == ""

    @pytest.mark.parametrize("status,headers,msg", [
        (404, {}, "not found"),
        (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1893456000"}, "limit .* resets at"),
        (429, {"X-RateLimit-Remaining": "0"}, "limit"),
        (403, {}, "refused"), (401, {}, "token was rejected"), (500, {}, "error"),
    ])  # fmt: skip
    def test_errors_are_friendly(self, api, status, headers, msg):
        a = api({"/users/priya-demo": (status, headers, {"message": "x"})})
        with pytest.raises(FetchFailed, match=msg):
            fetch_github("priya-demo", base_url=a.url)

    def test_garbage_json_and_wrong_shapes(self, api):
        with pytest.raises(FetchFailed):
            fetch_github("priya-demo", base_url=api({"/users/priya-demo": (200, {}, b"<html>")}).url)
        with pytest.raises(FetchFailed, match="unexpected"):
            fetch_github("priya-demo", base_url=api(ok_routes(repos={"not": "a list"})).url)

    def test_timeout_and_unreachable(self):
        with pytest.raises(FetchFailed, match="could not be reached"):
            fetch_github("priya-demo", base_url="http://127.0.0.1:9", timeout=1)


class TestMerge:
    def imp(self, api):
        return fetch_github("priya-demo", base_url=api(ok_routes()).url)

    def test_fills_gaps_only(self, api):
        base = Profile(
            name="Priya N.", contact=Contact(location="Pune"), projects=[Project(name="Tracker", description="mine")]
        )
        out = merge_github(base, self.imp(api))
        assert out.name == "Priya N." and out.contact.location == "Pune"  # not overwritten
        assert out.contact.github == "https://github.com/priya-demo" and out.contact.website == "https://priya.dev"
        assert [p.name for p in out.projects] == [
            "Tracker",
            "etl-tool",
            "dotfiles",
        ]  # 'tracker' already present (case-insensitive)
        assert out.projects[0].description == "mine"

    def test_never_creates_experience_or_education(self, api):
        out = merge_github(Profile(), self.imp(api), add_skills=True)
        assert out.experience == [] and out.education == [] and out.certifications == []

    def test_skills_only_added_on_request(self, api):
        imp = self.imp(api)
        assert merge_github(Profile(), imp).skills == []
        assert set(imp.languages) <= set(merge_github(Profile(), imp, add_skills=True).skills)

    def test_input_not_mutated(self, api):
        base = Profile(name="A")
        merge_github(base, self.imp(api))
        assert base.projects == [] and base.contact.github == ""


def test_timing_budget_is_bounded(api):
    start = time.monotonic()
    fetch_github("priya-demo", base_url=api(ok_routes()).url)
    assert time.monotonic() - start < 2
