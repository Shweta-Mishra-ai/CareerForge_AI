"""Gaps found by mutation checks of the v2 code: provider flags and limits, rank caps, portfolio warnings."""

from datetime import date

import pytest
from test_grounding import faithful_standard
from test_jobs import _clean_cache, api  # noqa: F401
from test_render_portfolio import full_profile

from careerforge import jobs as J
from careerforge.jobs import (
    ArbeitnowProvider,
    GreenhouseProvider,
    JobicyProvider,
    LeverProvider,
    RemoteOkProvider,
    RemotiveProvider,
    providers_from_urls,
    rank_jobs,
    search_all,
    suggest_queries,
)
from careerforge.models import Education, Experience, Profile, Project
from careerforge.render.portfolio import PortfolioOptions, build_portfolio

TODAY = date(2026, 10, 10)


class TestProviderDetails:
    def test_remote_only_feeds_mark_their_jobs_remote(self, api):  # noqa: F811
        a = api(
            {
                "/api/remote-jobs": (200, {"jobs": [{"title": "Dev", "url": "https://remotive.com/1"}]}),
                "/api/v2/remote-jobs": (200, {"jobs": [{"jobTitle": "Dev", "url": "https://jobicy.com/1"}]}),
                "/api": (200, [{"position": "Dev", "url": "https://remoteok.com/1"}]),
            }
        )
        for provider in (
            RemotiveProvider(base_url=a.url),
            JobicyProvider(base_url=a.url),
            RemoteOkProvider(base_url=a.url),
        ):
            (job,) = provider.search("dev", 5)
            assert job.remote is True, provider.name

    def test_every_board_honours_the_limit_and_the_tag_caps(self, api):  # noqa: F811
        tags = [f"tag{i}" for i in range(12)] + ["t" * 100]
        many = lambda n: [{"position": f"Dev {i}", "url": f"https://remoteok.com/{i}", "tags": tags} for i in range(n)]  # noqa: E731
        (job, *_) = RemoteOkProvider(base_url=api({"/api": (200, many(5))}).url).search("dev", 5)
        assert len(job.tags) == 8
        arb = {"data": [{"title": f"Dev {i}", "url": f"https://x.example/{i}", "tags": tags} for i in range(6)]}
        found = ArbeitnowProvider(base_url=api({"/api/job-board-api": (200, arb)}).url).search("dev", 3)
        assert len(found) == 3 and len(found[0].tags) == 8
        gh = {
            "jobs": [
                {"title": f"Dev {i}", "absolute_url": f"https://boards.greenhouse.io/a/jobs/{i}"} for i in range(6)
            ]
        }
        assert len(GreenhouseProvider("a", base_url=api({"/v1/boards/a/jobs": (200, gh)}).url).search("dev", 4)) == 4
        lv = [{"text": f"Dev {i}", "hostedUrl": f"https://jobs.lever.co/a/{i}"} for i in range(6)]
        assert len(LeverProvider("a", base_url=api({"/v0/postings/a": (200, lv)}).url).search("dev", 2)) == 2

    def test_lever_falls_back_to_the_html_description(self, api):  # noqa: F811
        rows = [{"text": "Dev", "hostedUrl": "https://jobs.lever.co/a/1", "description": "<p>Python and Kafka</p>"}]
        (job,) = LeverProvider("a", base_url=api({"/v0/postings/a": (200, rows)}).url).search("dev", 5)
        assert job.description == "Python and Kafka"

    def test_malformed_rows_are_skipped_not_fatal(self, api):  # noqa: F811
        rows = [{"jobTitle": 5}, "x", {"jobTitle": "Dev", "url": "https://jobicy.com/1"}]
        found = JobicyProvider(base_url=api({"/api/v2/remote-jobs": (200, {"jobs": rows})}).url).search("dev", 5)
        assert [j.title for j in found] == ["5", "Dev"]  # a number is a usable title; the string row is skipped

    def test_adzuna_needs_numeric_salaries_for_a_range(self, api):  # noqa: F811
        rows = {
            "results": [{"title": "Dev", "redirect_url": "https://a.example/1", "salary_min": 10, "salary_max": "x"}]
        }
        (job,) = J.AdzunaProvider("i", "k", base_url=api({"/v1/api/jobs/in/search/1": (200, rows)}).url).search(
            "dev", 5
        )
        assert job.salary == ""

    def test_rejected_links_are_shortened_for_display(self):
        _, rejected = providers_from_urls(["https://x.example/" + "a" * 300])
        assert len(rejected[0]) == 100


class TestSearchAndRank:
    class One:
        name = "One"
        calls = 0

        def search(self, q, n):
            type(self).calls += 1
            return [J.Job("Dev", "c", "Remote", "", "https://x.example/1", "s")]

    def test_the_query_is_cut_to_100_characters(self):
        seen = []

        class Spy(self.One):
            def search(self, q, n):
                seen.append(q)
                return []

        search_all([Spy()], "q" * 300)
        assert seen == ["q" * 100]

    def test_the_cache_expires_exactly_at_the_ttl(self):
        self.One.calls = 0
        search_all([self.One()], "dev", now=lambda: 0.0)
        search_all([self.One()], "dev", now=lambda: J.CACHE_TTL_S - 1)
        assert self.One.calls == 1
        search_all([self.One()], "dev", now=lambda: J.CACHE_TTL_S)
        assert self.One.calls == 2

    def test_matched_and_missing_lists_are_capped_at_eight(self):
        names = ["Python", "Go", "PostgreSQL", "Redis", "Kafka", "Docker", "Kubernetes", "AWS", "FastAPI", "Flask"]
        profile = Profile(name="A B", skills=names)
        job = J.Job("Dev", "c", "Remote", "Requirements: " + ", ".join(names), "https://x.example/1", "s")
        none = J.Job("Dev", "c", "Remote", "Requirements: Terraform, Ansible, Spark, Hadoop, Airflow, Snowflake, Tableau, Jenkins, MongoDB, Cassandra", "https://x.example/2", "s")  # fmt: skip
        assert len(rank_jobs(profile, [job], today=TODAY)[0].matched) == 8
        assert len(rank_jobs(profile, [none], today=TODAY)[0].missing) == 8

    def test_ideas_come_from_the_headline_and_three_recent_titles_only(self):
        p = Profile(
            name="A B", headline="Head",
            experience=[Experience(title=t, company="c") for t in ("T1", "T2", "T3", "T4", "T5")],
        )  # fmt: skip
        assert suggest_queries(p, limit=10) == ["Head", "T1", "T2", "T3"]
        assert len(suggest_queries(p)) == 4

    def test_seniority_uses_years_from_the_cv_dates(self):
        from careerforge.models import DateRange

        p = Profile(
            name="A B",
            experience=[Experience(title="Dev", company="c", dates=DateRange(start="2019-04", end="2026-10"))],
        )  # 91 months = 7.6 years -> the senior band (6-9 years)
        job = J.Job("Senior Dev", "c", "Remote", "Requirements: Python", "https://x.example/1", "s")
        part = next(x for x in rank_jobs(p, [job], today=TODAY)[0].parts if x.key == "seniority")
        assert part.score == 100 and "8 years" in part.detail

    def test_default_today_is_the_real_date(self):
        job = J.Job("Dev", "c", "Remote", "", "https://x.example/1", "s", posted=date.today().isoformat())
        part = next(x for x in rank_jobs(faithful_standard(), [job])[0].parts if x.key == "freshness")
        assert part.score == 100
        assert J.filter_jobs(rank_jobs(faithful_standard(), [job]), posted_within_days=1) != []


class TestPortfolioDetails:
    def build(self, profile, **kw):
        return build_portfolio(profile, PortfolioOptions(**kw), today=TODAY)

    def test_no_projects_and_no_experience_warns_but_one_of_them_does_not(self):
        base = Profile(
            name="Sam Rivera", contact=full_profile().contact, education=[Education(degree="BSc", institution="Uni")]
        )
        assert any("looks empty" in w for w in self.build(base).warnings)
        with_project = base.model_copy(update={"projects": [Project(name="Tool")]})
        assert not any("looks empty" in w for w in self.build(with_project).warnings)
        with_job = base.model_copy(update={"experience": [Experience(title="Dev", company="Acme")]})
        assert not any("looks empty" in w for w in self.build(with_job).warnings)

    def test_the_about_warning_depends_on_the_summary_and_on_hiding_it(self):
        p = full_profile().model_copy(update={"summary": ""})
        assert any("About section" in w for w in self.build(p).warnings)
        assert not any("About section" in w for w in self.build(p, hidden=frozenset({"about"})).warnings)
        assert not any("About section" in w for w in self.build(full_profile()).warnings)

    def test_at_most_five_schools_are_listed_in_the_structured_data(self):
        import json

        from test_render_portfolio import soup

        schools = [Education(degree="BSc", institution=f"School {i}") for i in range(8)]
        html = self.build(full_profile().model_copy(update={"education": schools})).html
        assert len(json.loads(soup(html).find("script").string)["alumniOf"]) == 5

    def test_the_readme_lists_the_sitemap_only_when_it_exists(self):
        assert "sitemap.xml" not in self.build(full_profile()).readme
        assert "sitemap.xml" in self.build(full_profile(), site_url="https://jane.example.com/").readme
        assert (
            "sitemap.xml" not in self.build(full_profile(), site_url="https://jane.example.com/", noindex=True).readme
        )

    def test_zip_entries_have_a_fixed_date_and_permissions(self):
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(self.build(full_profile()).zip_bytes())) as z:
            for info in z.infolist():
                assert info.date_time == (2020, 1, 1, 0, 0, 0) and (info.external_attr >> 16) == 0o644

    def test_a_site_built_without_today_uses_the_real_date(self):
        built = build_portfolio(full_profile(), PortfolioOptions(site_url="https://jane.example.com/"))
        assert date.today().isoformat() in built.files()["sitemap.xml"].decode()


class TestThemeBoundaries:
    def test_text_on_the_accent_is_white_or_black_whichever_reads_better(self):
        from careerforge.render.themes import THEMES, with_accent

        assert with_accent(THEMES["light"], "#1d4ed8").accent_text == "#ffffff"
        assert with_accent(THEMES["dark"], "#7dd3fc").accent_text == "#000000"

    def test_an_accent_just_under_the_threshold_is_refused_and_just_over_is_accepted(self):
        from careerforge.render.options import contrast_ratio
        from careerforge.render.themes import MIN_CONTRAST, THEMES, with_accent

        bg = THEMES["light"].surface  # the darker of the two backgrounds a link is drawn on
        ratios = {}
        for grey in range(0x40, 0xA0):
            colour = f"#{grey:02x}{grey:02x}{grey:02x}"
            ratios[colour] = contrast_ratio(colour, bg)
        ok = [c for c, r in ratios.items() if r >= MIN_CONTRAST]
        bad = [c for c, r in ratios.items() if r < MIN_CONTRAST]
        assert ok and bad
        edge_ok = min(ok, key=lambda c: ratios[c])
        edge_bad = max(bad, key=lambda c: ratios[c])
        assert with_accent(THEMES["light"], edge_ok).accent == edge_ok
        with pytest.raises(ValueError):
            with_accent(THEMES["light"], edge_bad)
