"""Job search: public job-board APIs, merged, de-duplicated and ranked with the same engine as the ATS report.

NOT verified against the live services (the build sandbox cannot reach them): response field names follow the
shapes the original CareerBoost code relied on. Failures are reported per provider, never swallowed, and results are
cached for an hour out of courtesy to the free APIs. Remotive asks that you credit it as the source, so every Job
carries `source` and its original `url`.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import requests
from bs4 import BeautifulSoup

from careerforge.ats import match as mt
from careerforge.ats.jd import parse_job_description
from careerforge.models import Profile
from careerforge.text import clean_text, normalize_url

MAX_BYTES = 2_000_000
CACHE_TTL_S = 3600.0
DESCRIPTION_LIMIT = 2000
USER_AGENT = "CareerForge-AI/0.2 (job search; +https://github.com/Shweta-Mishra-ai/CareerForge_AI)"


@dataclass(frozen=True)
class Job:
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str
    type: str = ""
    salary: str = ""
    posted: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RankedJob:
    job: Job
    score: int  # 0-100: 70% keyword coverage + 30% role alignment (same engine as the ATS report)
    matched: tuple[str, ...]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class SearchResult:
    jobs: tuple[Job, ...]
    errors: dict[str, str] = field(default_factory=dict)  # provider name -> user-presentable reason


class Provider(Protocol):
    name: str

    def search(self, query: str, limit: int) -> list[Job]: ...


class ProviderError(Exception):
    """A provider failed in a way worth showing the user."""


def _text(html: object, limit: int = DESCRIPTION_LIMIT) -> str:
    raw = str(html or "")
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(["p", "div", "br", "li", "ul", "h1", "h2", "h3", "h4"]):
        tag.insert_before("\n")
    return clean_text(soup.get_text(""), multiline=True)[:limit]


def _url(value: object) -> str:
    try:
        return normalize_url(value if isinstance(value, str) else "")
    except ValueError:
        return ""


def _str(value: object, limit: int = 200) -> str:
    return clean_text(value)[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _day(value: object) -> str:
    m = re.match(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    try:
        return date.fromisoformat(m.group(0)).isoformat() if m else ""
    except ValueError:
        return ""


def _get_json(session: requests.Session, url: str, params: dict, timeout: float, name: str) -> object:
    try:
        resp = session.get(
            url,
            params=params,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            stream=True,
        )
    except requests.exceptions.RequestException as exc:
        raise ProviderError(f"{name} could not be reached") from exc
    try:
        if resp.status_code == 429:
            raise ProviderError(f"{name} is rate-limiting requests; try again later")
        if resp.status_code in (401, 403):
            raise ProviderError(f"{name} rejected the request (check its API key)")
        if resp.status_code >= 400:
            raise ProviderError(f"{name} answered with an error ({resp.status_code})")
        body = b""
        for chunk in resp.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                raise ProviderError(f"{name} sent an unexpectedly large response")
        try:
            return json.loads(body.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise ProviderError(f"{name} returned an unreadable response") from exc
    finally:
        resp.close()


class _Base:
    def __init__(self, *, base_url: str, session: requests.Session | None = None, timeout: float = 10.0):
        self.base_url, self.timeout = base_url, timeout
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False


def _rows(data: object, key: str, name: str) -> list:
    rows = data.get(key) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ProviderError(f"{name} returned an unexpected response")
    return rows


class RemotiveProvider(_Base):
    name = "Remotive"

    def __init__(self, *, base_url: str = "https://remotive.com", **kw):
        super().__init__(base_url=base_url, **kw)

    def search(self, query: str, limit: int) -> list[Job]:
        params = {"search": query, "limit": limit}
        data = _get_json(self.session, f"{self.base_url}/api/remote-jobs", params, self.timeout, self.name)
        jobs = []
        for r in _rows(data, "jobs", self.name)[:limit]:
            if not isinstance(r, dict) or not _str(r.get("title")):
                continue
            tags = tuple(_str(t, 40).lower() for t in (r.get("tags") or []) if isinstance(t, str))[:8]
            jobs.append(
                Job(
                    title=_str(r.get("title")),
                    company=_str(r.get("company_name")),
                    location=_str(r.get("candidate_required_location")) or "Remote",
                    description=_text(r.get("description")),
                    url=_url(r.get("url")),
                    source=self.name,
                    type=_str(r.get("job_type")),
                    salary=_str(r.get("salary")),
                    posted=_day(r.get("publication_date")),
                    tags=tags,
                )
            )
        return jobs


class JobicyProvider(_Base):
    name = "Jobicy"

    def __init__(self, *, base_url: str = "https://jobicy.com", **kw):
        super().__init__(base_url=base_url, **kw)

    def search(self, query: str, limit: int) -> list[Job]:
        params = {"count": limit, "tag": query}
        data = _get_json(self.session, f"{self.base_url}/api/v2/remote-jobs", params, self.timeout, self.name)
        jobs = []
        for r in _rows(data, "jobs", self.name)[:limit]:
            if not isinstance(r, dict) or not _str(r.get("jobTitle")):
                continue
            kind = r.get("jobType")
            jobs.append(
                Job(
                    title=_str(r.get("jobTitle")),
                    company=_str(r.get("companyName")),
                    location="Remote - " + (_str(r.get("jobGeo")) or "Worldwide"),
                    description=_text(r.get("jobDescription")),
                    url=_url(r.get("url")),
                    source=self.name,
                    type=_str(", ".join(kind) if isinstance(kind, list) else kind),
                    salary=_str(r.get("annualSalaryMin")),
                    posted=_day(r.get("pubDate")),
                )
            )
        return jobs


class AdzunaProvider(_Base):
    """Needs a free app_id/app_key from Adzuna. Without keys it is simply not used (the old app sent empty keys)."""

    name = "Adzuna"

    def __init__(
        self, app_id: str, app_key: str, *, country: str = "in", base_url: str = "https://api.adzuna.com", **kw
    ):
        if not (app_id and app_key):
            raise ValueError("Adzuna needs both app_id and app_key")
        super().__init__(base_url=base_url, **kw)
        self.app_id, self.app_key, self.country = app_id, app_key, country.lower()

    def search(self, query: str, limit: int) -> list[Job]:
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": limit,
            "what": query,
            "content-type": "application/json",
        }
        url = f"{self.base_url}/v1/api/jobs/{self.country}/search/1"
        data = _get_json(self.session, url, params, self.timeout, self.name)
        jobs = []
        for r in _rows(data, "results", self.name)[:limit]:
            if not isinstance(r, dict) or not _str(r.get("title")):
                continue
            company = r.get("company") if isinstance(r.get("company"), dict) else {}
            place = r.get("location") if isinstance(r.get("location"), dict) else {}
            lo, hi = r.get("salary_min"), r.get("salary_max")
            numeric = isinstance(lo, (int, float)) and isinstance(hi, (int, float))
            jobs.append(
                Job(
                    title=_str(r.get("title")),
                    company=_str(company.get("display_name")),
                    location=_str(place.get("display_name")),
                    description=_text(r.get("description")),
                    url=_url(r.get("redirect_url")),
                    source=self.name,
                    salary=f"{int(lo)}-{int(hi)}" if numeric else "",
                    posted=_day(r.get("created")),
                )
            )
        return jobs


_cache: dict[tuple, tuple[float, list[Job]]] = {}


def clear_cache() -> None:
    _cache.clear()


def search_all(
    providers: list[Provider], query: str, *, limit: int = 12, now: Callable[[], float] = time.monotonic
) -> SearchResult:
    """Query every provider; one failing never hides the others. Results are de-duplicated and cached for an hour."""
    query = clean_text(query)[:100]
    if not query:
        return SearchResult(())
    errors: dict[str, str] = {}
    collected: list[Job] = []
    for provider in providers:
        key = (provider.name, query.lower(), limit)
        hit = _cache.get(key)
        if hit and now() - hit[0] < CACHE_TTL_S:
            collected += hit[1]
            continue
        try:
            jobs = provider.search(query, limit)
        except ProviderError as exc:
            errors[provider.name] = str(exc)
            continue
        _cache[key] = (now(), jobs)
        collected += jobs
    seen: set[tuple[str, str]] = set()
    unique: list[Job] = []
    for job in collected:
        ident = (job.title.lower(), job.company.lower())
        if ident in seen or not job.url:
            continue
        seen.add(ident)
        unique.append(job)
    return SearchResult(tuple(unique), errors)


def rank_jobs(profile: Profile, jobs: tuple[Job, ...] | list[Job], *, min_score: int = 0) -> list[RankedJob]:
    """Score each job with the ATS engine (70% keyword coverage, 30% role alignment), best first."""
    p = profile.exportable()
    ranked = []
    for job in jobs:
        jd = parse_job_description(f"{job.title}\n{job.description}")
        hits, misses = mt.match_requirements(p, jd)
        coverage = mt.coverage_score(hits, misses)
        role, _ = mt.role_alignment(p, jd)
        parts = [(0.7, coverage), (0.3, role)]
        usable = [(w, v) for w, v in parts if v is not None]
        score = round(sum(w * v for w, v in usable) / sum(w for w, _ in usable)) if usable else 0
        if score >= min_score:
            ranked.append(
                RankedJob(job, score, tuple(m.requirement.term for m in hits[:8]), tuple(r.term for r in misses[:8]))
            )
    return sorted(ranked, key=lambda r: -r.score)


def suggest_queries(profile: Profile, limit: int = 4) -> list[str]:
    """Search phrases from the CV: its headline / recent titles. No skill-to-title guessing tables."""
    p = profile.exportable()
    candidates = [p.headline, *(e.title for e in p.experience[:3])]
    out: list[str] = []
    for c in candidates:
        c = clean_text(c)
        if c and c.lower() not in {o.lower() for o in out}:
            out.append(c)
    return out[:limit]
