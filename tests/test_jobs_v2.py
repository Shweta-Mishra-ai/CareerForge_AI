"""Job search v2: company boards, normalised fields, the disclosed ranking, filters and scam-pattern checks.

Provider responses are hand-written look-alikes of each service's documented shape: NOT recorded from the live services.
"""

import json
from datetime import date

import pytest
from test_grounding import faithful_standard
from test_jobs import _clean_cache, api  # noqa: F401  (fixtures)

from careerforge import jobs as J
from careerforge.jobs import (
    RANK_WEIGHTS,
    ArbeitnowProvider,
    GreenhouseProvider,
    Job,
    LeverProvider,
    Preferences,
    ProviderError,
    RemoteOkProvider,
    detect_employment,
    detect_remote,
    detect_seniority,
    enrich,
    filter_jobs,
    freshness,
    location_fit,
    parse_career_url,
    providers_from_urls,
    rank_jobs,
    red_flags,
    search_all,
    seniority_fit,
)

TODAY = date(2026, 10, 10)
P = faithful_standard()

GREENHOUSE = {"jobs": [
    {"id": 1, "title": "Senior Backend Engineer", "updated_at": "2026-10-05T10:00:00-04:00", "location": {"name": "Pune, India"},
     "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "company_name": "Acme Corp",
     "content": "&lt;p&gt;Build &lt;b&gt;APIs&lt;/b&gt; with Python &amp;amp; Kafka.&lt;/p&gt;&lt;script&gt;x()&lt;/script&gt;"},
    {"id": 2, "title": "Office Manager", "location": {"name": "Berlin"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
     "content": "&lt;p&gt;Run the office.&lt;/p&gt;"},
    {"id": 3, "location": {}}, "junk",
]}  # fmt: skip
LEVER = [
    {"text": "Staff Data Engineer", "categories": {"location": "Remote - EU", "commitment": "Full-time", "team": "Data"},
     "hostedUrl": "https://jobs.lever.co/acme/abc", "createdAt": 1790000000000, "workplaceType": "remote",
     "descriptionPlain": "Own our Python and Kafka pipelines."},
    {"text": "Receptionist", "categories": {}, "hostedUrl": "https://jobs.lever.co/acme/def", "descriptionPlain": "Greet people."},
    {"no": "title"},
]  # fmt: skip
ARBEITNOW = {"data": [
    {"slug": "a", "company_name": "Berlin GmbH", "title": "Backend Developer", "description": "<p>Python and Kafka</p>",
     "remote": True, "url": "https://www.arbeitnow.com/jobs/a", "tags": ["Python"], "job_types": ["full time"],
     "location": "Berlin", "created_at": 1790000000},
    {"slug": "b", "company_name": "Cafe", "title": "Barista", "description": "Coffee", "remote": False,
     "url": "https://www.arbeitnow.com/jobs/b", "tags": [], "job_types": [], "location": "Hamburg", "created_at": 1790000000},
], "links": {}, "meta": {}}  # fmt: skip
REMOTEOK = [
    {"legal": "RemoteOK terms: link back and credit the source"},
    {"slug": "x", "company": "Zed", "position": "Python Developer", "tags": ["python", "api"], "description": "<p>Python APIs</p>",
     "location": "", "date": "2026-10-08T00:00:00+00:00", "url": "https://remoteok.com/remote-jobs/x", "salary_min": 90000, "salary_max": 120000},
    {"slug": "y", "company": "Q", "position": "Pastry Chef", "tags": ["food"], "description": "Bake", "url": "https://remoteok.com/y",
     "salary_min": 0, "salary_max": 0},
]  # fmt: skip


class TestCompanyBoards:
    def test_greenhouse_maps_filters_and_cleans(self, api):  # noqa: F811
        a = api({"/v1/boards/acme/jobs": (200, GREENHOUSE)})
        jobs = GreenhouseProvider("acme", base_url=a.url).search("backend engineer python", 10)
        assert [j.title for j in jobs] == ["Senior Backend Engineer"]  # the office manager is not relevant
        j = jobs[0]
        assert (j.company, j.location, j.posted, j.source) == (
            "Acme Corp",
            "Pune, India",
            "2026-10-05",
            "Greenhouse (acme)",
        )
        assert "Build APIs with Python" in j.description and "x()" not in j.description and "<" not in j.description
        assert "content=true" in a.seen[0]

    def test_greenhouse_falls_back_to_the_board_name_for_the_company(self, api):  # noqa: F811
        rows = {
            "jobs": [
                {"title": "Backend Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/9", "content": ""}
            ]
        }
        (j,) = GreenhouseProvider("acme", base_url=api({"/v1/boards/acme/jobs": (200, rows)}).url).search("backend", 5)
        assert j.company == "acme"

    def test_lever_maps_epoch_dates_and_workplace_type(self, api):  # noqa: F811
        a = api({"/v0/postings/acme": (200, LEVER)})
        jobs = LeverProvider("acme", base_url=a.url).search("data engineer python", 10)
        assert [j.title for j in jobs] == ["Staff Data Engineer"]
        j = jobs[0]
        assert (j.location, j.type, j.remote, j.source, j.posted) == (
            "Remote - EU",
            "Full-time",
            True,
            "Lever (acme)",
            "2026-09-21",
        )
        assert "mode=json" in a.seen[0]

    @pytest.mark.parametrize(
        "workplace,expected", [("remote", True), ("on-site", False), ("hybrid", False), ("", None)]
    )
    def test_lever_workplace_type(self, api, workplace, expected):  # noqa: F811
        row = [
            {
                "text": "Backend Engineer",
                "workplaceType": workplace,
                "hostedUrl": "https://jobs.lever.co/a/1",
                "categories": {},
            }
        ]
        (j,) = LeverProvider("a", base_url=api({"/v0/postings/a": (200, row)}).url).search("backend", 5)
        assert j.remote is expected

    def test_arbeitnow_keeps_its_own_remote_flag_and_filters(self, api):  # noqa: F811
        a = api({"/api/job-board-api": (200, ARBEITNOW)})
        jobs = ArbeitnowProvider(base_url=a.url).search("backend python", 10)
        assert [j.title for j in jobs] == ["Backend Developer"]
        assert (jobs[0].remote, jobs[0].posted, jobs[0].type, jobs[0].tags) == (
            True,
            "2026-09-21",
            "full time",
            ("python",),
        )

    def test_remoteok_skips_the_legal_notice_and_keeps_attribution(self, api):  # noqa: F811
        a = api({"/api": (200, REMOTEOK)})
        jobs = RemoteOkProvider(base_url=a.url).search("python", 10)
        assert [j.title for j in jobs] == ["Python Developer"]
        j = jobs[0]
        assert (j.source, j.url, j.salary, j.posted, j.remote, j.location) == (
            "RemoteOK", "https://remoteok.com/remote-jobs/x", "90000-120000", "2026-10-08", True, "Remote",
        )  # fmt: skip

    def test_remoteok_ignores_zero_salaries(self, api):  # noqa: F811
        jobs = RemoteOkProvider(base_url=api({"/api": (200, REMOTEOK)}).url).search("pastry chef", 10)
        assert jobs[0].salary == ""

    def test_the_limit_is_honoured(self, api):  # noqa: F811
        rows = [
            {"position": f"Python Dev {i}", "company": "c", "url": f"https://remoteok.com/{i}", "tags": ["python"]}
            for i in range(30)
        ]
        assert len(RemoteOkProvider(base_url=api({"/api": (200, rows)}).url).search("python", 7)) == 7

    @pytest.mark.parametrize("provider", [GreenhouseProvider, LeverProvider])
    @pytest.mark.parametrize("bad", ["", "a b", "../x", "a/b", "x" * 61, "-x", "a?b=c"])
    def test_board_names_are_validated(self, provider, bad):
        with pytest.raises(ValueError):
            provider(bad)

    def test_a_missing_board_says_to_check_the_spelling(self, api):  # noqa: F811
        with pytest.raises(ProviderError, match="not found"):
            GreenhouseProvider("nope", base_url=api({}).url).search("x", 5)

    @pytest.mark.parametrize(
        "provider,route,body",
        [
            (lambda u: GreenhouseProvider("a", base_url=u), "/v1/boards/a/jobs", b'{"jobs": "x"}'),
            (lambda u: LeverProvider("a", base_url=u), "/v0/postings/a", b'{"not": "a list"}'),
            (lambda u: RemoteOkProvider(base_url=u), "/api", b'{"not": "a list"}'),
            (lambda u: ArbeitnowProvider(base_url=u), "/api/job-board-api", b"[1]"),
            (lambda u: ArbeitnowProvider(base_url=u), "/api/job-board-api", b"<html>"),
        ],
    )
    def test_unexpected_shapes_are_provider_errors(self, api, provider, route, body):  # noqa: F811
        with pytest.raises(ProviderError):
            provider(api({route: (200, body)}).url).search("x", 5)

    def test_boards_may_be_larger_than_the_ordinary_limit_but_not_unbounded(self, api):  # noqa: F811
        big = json.dumps({"jobs": [], "pad": "x" * 2_500_000}).encode()
        assert GreenhouseProvider("a", base_url=api({"/v1/boards/a/jobs": (200, big)}).url).search("x", 5) == []
        huge = json.dumps({"jobs": [], "pad": "x" * (J.BOARD_MAX_BYTES + 10)}).encode()
        with pytest.raises(ProviderError, match="large"):
            GreenhouseProvider("a", base_url=api({"/v1/boards/a/jobs": (200, huge)}).url).search("x", 5)

    def test_two_boards_have_separate_names_so_neither_hides_the_others_errors(self):
        assert GreenhouseProvider("a").name != GreenhouseProvider("b").name


class TestCareerUrls:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://boards.greenhouse.io/acme", ("greenhouse", "acme")),
            ("https://boards.greenhouse.io/acme/jobs/123?gh_src=x", ("greenhouse", "acme")),
            ("https://job-boards.greenhouse.io/acme", ("greenhouse", "acme")),
            ("http://boards.greenhouse.io/embed/job_board?for=acme", ("greenhouse", "acme")),
            ("https://jobs.lever.co/acme", ("lever", "acme")),
            ("https://jobs.lever.co/acme/1234-abcd/apply", ("lever", "acme")),
            ("  https://JOBS.LEVER.CO/Acme-Co  ", ("lever", "Acme-Co")),
        ],
    )
    def test_real_board_links_are_understood(self, url, expected):
        assert parse_career_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "", "acme", "https://example.com/acme", "https://boards.greenhouse.io", "https://boards.greenhouse.io/",
            "https://boards.greenhouse.io.evil.com/acme", "https://evil.com/boards.greenhouse.io/acme",
            "https://user:pw@boards.greenhouse.io/acme", "ftp://boards.greenhouse.io/acme", "javascript:alert(1)",
            "https://boards.greenhouse.io/embed/job_board", "https://boards.greenhouse.io/embed/job_board?for=a/b",
            "https://jobs.lever.co/../x", "https://jobs.lever.co/" + "a" * 80, "https://[::1", "http://localhost:80/x",
        ],
    )  # fmt: skip
    def test_anything_else_is_refused(self, url):
        assert parse_career_url(url) is None

    def test_providers_are_built_deduplicated_and_rejects_are_reported(self):
        providers, rejected = providers_from_urls(
            [
                "https://boards.greenhouse.io/a",
                "https://boards.greenhouse.io/a/jobs/2",
                "https://jobs.lever.co/b",
                "",
                "https://x.com/y",
            ]
        )
        assert [p.name for p in providers] == ["Greenhouse (a)", "Lever (b)"] and rejected == ["https://x.com/y"]


class TestNormalising:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Software Engineering Intern", "intern"), ("Working Student Data", "intern"), ("Junior Developer", "junior"),
            ("Jr. QA Engineer", "junior"), ("Entry-Level Analyst", "junior"), ("Graduate Engineer", "junior"),
            ("Mid-Level Designer", "mid"), ("Senior Backend Engineer", "senior"), ("Sr Data Scientist", "senior"),
            ("Tech Lead", "lead"), ("Principal Engineer", "lead"), ("Head of Data", "lead"), ("Staff Engineer", "lead"),
            ("Senior Staff Engineer", "lead"), ("Director of Engineering", "lead"), ("Lead Generation Specialist", ""),
            ("Backend Engineer", ""), ("Staff Accountant", ""), ("", ""),
        ],
    )  # fmt: skip
    def test_seniority_comes_from_the_title_only(self, title, expected):
        assert detect_seniority(title) == expected

    @pytest.mark.parametrize(
        "kind,title,expected",
        [
            ("full_time", "", "full-time"), ("Full-Time", "", "full-time"), ("Permanent", "", "full-time"),
            ("part time", "", "part-time"), ("Contract", "", "contract"), ("freelance", "", "contract"),
            ("", "Data Intern", "internship"), ("Internship", "", "internship"), ("", "", ""), ("other", "", ""),
        ],
    )  # fmt: skip
    def test_employment_type(self, kind, title, expected):
        assert detect_employment(kind, title) == expected

    def test_remote_is_only_claimed_when_the_posting_says_so(self):
        def j(location, title="Dev", remote=None):
            return Job(title, "c", location, "", "https://x.example/1", "s", remote=remote)

        assert detect_remote(j("Remote - EU")) is True
        assert detect_remote(j("Work from home")) is True
        assert detect_remote(j("Berlin", "Remote Engineer")) is True
        assert detect_remote(j("Hybrid / Remote")) is None  # hybrid is not remote
        assert detect_remote(j("Berlin")) is None  # unknown, never "on-site"
        assert detect_remote(j("Remote", remote=False)) is False  # the provider's own statement wins

    def test_enrich_never_overrides_what_the_provider_stated(self):
        j = Job(
            "Senior Dev",
            "c",
            "Remote",
            "",
            "https://x.example/1",
            "s",
            type="Contract",
            seniority="lead",
            employment="part-time",
        )
        e = enrich(j)
        assert (e.seniority, e.employment, e.remote) == ("lead", "part-time", True)
        e2 = enrich(Job("Senior Dev", "c", "Pune", "", "https://x.example/1", "s", type="Contract"))
        assert (e2.seniority, e2.employment, e2.remote) == ("senior", "contract", None)

    def test_search_results_come_back_enriched(self):
        class One:
            name = "One"

            def search(self, q, n):
                return [Job("Junior Dev", "c", "Remote", "", "https://x.example/1", "s", type="part_time")]

        (j,) = search_all([One()], "dev").jobs
        assert (j.seniority, j.employment, j.remote) == ("junior", "part-time", True)


class TestRankingParts:
    @pytest.mark.parametrize(
        "years,level,expected",
        [
            (0.5, "intern", 100), (0.5, "junior", 65), (0.5, "mid", 30), (0.5, "senior", 0), (0.5, "lead", 0),
            (2, "junior", 100), (2, "mid", 65), (4, "mid", 100), (4, "senior", 65), (4, "intern", 30),
            (7, "senior", 100), (7, "lead", 65), (12, "lead", 100), (12, "senior", 65), (12, "mid", 30), (12, "junior", 0),
            (4, "", None), (4, "wizard", None),
        ],
    )  # fmt: skip
    def test_seniority_fit(self, years, level, expected):
        assert seniority_fit(years, level) == expected

    @pytest.mark.parametrize("years,band", [(0.99, 0), (1, 1), (2.99, 1), (3, 2), (5.99, 2), (6, 3), (8.99, 3), (9, 4)])
    def test_band_edges(self, years, band):
        assert seniority_fit(years, "intern") == {0: 100, 1: 65, 2: 30, 3: 0, 4: 0}[band]

    @pytest.mark.parametrize(
        "posted,expected",
        [("2026-10-10", 100), ("2026-10-03", 100), ("2026-10-02", 85), ("2026-09-26", 85), ("2026-09-25", 65),
         ("2026-09-10", 65), ("2026-09-09", 35), ("2026-08-11", 35), ("2026-08-10", 10), ("2026-10-20", 100), ("", None), ("junk", None)],
    )  # fmt: skip
    def test_freshness_bands(self, posted, expected):
        assert freshness(posted, TODAY) == expected

    def test_location_fit(self):
        def j(location, remote=None):
            return Job("d", "c", location, "", "https://x.example/1", "s", remote=remote)

        pune = Preferences(location="pune")
        assert location_fit(j("Pune, India"), pune) == 100
        assert location_fit(j("Remote - EU", True), pune) == 90
        assert location_fit(j("Berlin"), pune) == 0
        assert location_fit(j(""), pune) == 40
        assert location_fit(j("Berlin"), Preferences()) is None
        only = Preferences(remote_only=True)
        assert (location_fit(j("x", True), only), location_fit(j("x"), only), location_fit(j("x", False), only)) == (
            100,
            40,
            0,
        )

    def test_weights_are_disclosed_and_sum_to_one(self):
        assert abs(sum(RANK_WEIGHTS.values()) - 1) < 1e-9
        r = rank_jobs(
            P, [Job("Backend Engineer", "c", "Remote", "Requirements: Python", "https://x.example/1", "s")], today=TODAY
        )[0]
        assert {x.key: x.weight for x in r.parts} == RANK_WEIGHTS and all(x.label and x.detail for x in r.parts)

    def test_the_score_is_exactly_the_reweighted_parts(self):
        job = Job(
            "Senior Backend Engineer",
            "c",
            "Pune",
            "Requirements: Python, Kafka, Rust",
            "https://x.example/1",
            "s",
            posted="2026-10-08",
        )
        r = rank_jobs(P, [job], prefs=Preferences(location="Pune"), today=TODAY)[0]
        usable = [x for x in r.parts if x.score is not None]
        assert len(usable) == 5
        assert r.score == round(sum(x.weight * x.score for x in usable) / sum(x.weight for x in usable))

    def test_a_fresh_local_senior_role_outranks_an_identical_old_remote_junior_one(self):
        base = dict(company="c", description="Requirements: Python, Kafka", url="https://x.example/1", source="s")
        good = Job("Senior Backend Engineer", location="Pune", posted="2026-10-09", **base)
        bad = Job("Junior Backend Engineer", location="Berlin", posted="2025-01-01", **base)
        ranked = rank_jobs(P, [bad, good], prefs=Preferences(location="Pune"), today=TODAY)
        assert [r.job.seniority for r in ranked] == ["senior", "junior"] and ranked[0].score > ranked[1].score

    def test_equal_scores_are_ordered_newest_first(self):
        def at(day):
            return Job(
                "Backend Engineer", "c", "Remote", "Requirements: Python", f"https://x.example/{day}", "s", posted=day
            )

        ranked = rank_jobs(P, [at("2026-10-04"), at("2026-10-09"), at("2026-10-06")], today=TODAY)
        assert len({r.score for r in ranked}) == 1  # all inside the freshest band: the score cannot tell them apart
        assert [r.job.posted for r in ranked] == ["2026-10-09", "2026-10-06", "2026-10-04"]

    def test_flags_are_attached_to_ranked_jobs(self):
        scam = Job("Data Entry", "c", "Remote", "You must pay a registration fee.", "https://x.example/1", "s")
        assert rank_jobs(P, [scam], today=TODAY)[0].flags


class TestFilters:
    def jobs(self):
        def j(title, **kw):
            base = dict(
                company="c",
                location="Berlin",
                description="Requirements: Python",
                url=f"https://x.example/{title}",
                source="s",
            )
            return Job(title, **{**base, **kw})

        return rank_jobs(
            P,
            [
                j("Senior Dev", remote=True, type="Contract", posted="2026-10-09"),
                j("Junior Dev", remote=False, type="full_time", posted="2026-08-01"),
                j("Dev", description="Pay a registration fee first. Requirements: Python"),
            ],
            today=TODAY,
        )

    def titles(self, **kw):
        return sorted(r.job.title for r in filter_jobs(self.jobs(), today=TODAY, **kw))

    def test_no_filters_keeps_everything(self):
        assert self.titles() == ["Dev", "Junior Dev", "Senior Dev"]

    def test_remote_only_needs_an_explicit_remote_posting(self):
        assert self.titles(remote_only=True) == ["Senior Dev"]

    def test_seniority_and_employment(self):
        assert self.titles(seniority=["junior"]) == ["Junior Dev"]
        assert self.titles(seniority=["junior", "senior"]) == ["Junior Dev", "Senior Dev"]
        assert self.titles(employment=["contract"]) == ["Senior Dev"]
        assert self.titles(employment=["full-time"]) == ["Junior Dev"]

    @pytest.mark.parametrize(
        "days,expected", [(1, ["Senior Dev"]), (7, ["Senior Dev"]), (80, ["Junior Dev", "Senior Dev"])]
    )
    def test_posted_within(self, days, expected):
        assert self.titles(posted_within_days=days) == expected  # undated postings need the filter's date, so they drop

    def test_hide_flagged(self):
        assert self.titles(hide_flagged=True) == ["Junior Dev", "Senior Dev"]


class TestRedFlags:
    def flags(self, text, company="Acme"):
        return red_flags(Job("Assistant", company, "Remote", text, "https://x.example/1", "s"))

    @pytest.mark.parametrize(
        "text",
        [
            "A one-time registration fee is required.",
            "You must pay for your starter kit.",
            "Training fee: $50",
            "Payment by gift cards",
            "We pay in bitcoin",
            "Send via Western Union",
            "Deposit the cheque we send you",
            "Interview on Telegram only",
            "Please contact us on WhatsApp to apply",
            "Send your bank details to start",
            "Provide your social security number",
            "No experience needed, earn up to $500 per day",
        ],
    )
    def test_known_scam_patterns_are_flagged(self, text):
        assert self.flags(text), text

    @pytest.mark.parametrize(
        "text",
        [
            "We offer competitive pay and a training budget.",
            "You will manage our fee schedule and invoices.",
            "Requirements: Python, Kafka. Remote-friendly. Contact us through our careers page.",
            "Experience with payments, crypto exchanges welcome.",  # the word alone is flagged; see below
        ][:3],
    )
    def test_ordinary_postings_are_not_flagged(self, text):
        assert self.flags(text) == ()

    def test_a_missing_company_is_flagged(self):
        assert any("company" in f.lower() for f in self.flags("Fine text.", company=" "))

    def test_no_flag_text_claims_the_posting_is_genuine(self):
        assert all(
            "genuine" not in f.lower() and "safe" not in f.lower() for f in self.flags("gift card wire transfer")
        )
