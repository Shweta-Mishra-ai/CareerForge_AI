"""Job search: public job-board APIs, merged, de-duplicated, normalised and ranked against the CV.

NOT verified against the live services (the build sandbox cannot reach them): response field names follow each
provider's public documentation or the shapes the original CareerBoost code relied on, and every parser is tested only
against hand-written look-alike responses. Failures are reported per provider, never swallowed, and results are cached
for an hour out of courtesy to the free APIs. Remotive and RemoteOK ask that you credit them and link back, so every
Job carries `source` and its original `url`.

Company boards (Greenhouse, Lever) are searched by pasting the company's own careers-page link: the board name is read
from the link by `parse_career_url`, which accepts only those two services' real hosts.
"""

from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

import requests
from bs4 import BeautifulSoup

from careerforge.ats import match as mt
from careerforge.ats.jd import parse_job_description
from careerforge.models import Profile
from careerforge.nlp import content_tokens, stem
from careerforge.text import clean_text, normalize_url

MAX_BYTES = 2_000_000
BOARD_MAX_BYTES = 8_000_000  # a company board with full descriptions can be several MB
CACHE_TTL_S = 3600.0
DESCRIPTION_LIMIT = 2000
USER_AGENT = "CareerForge-AI/0.3 (job search; +https://github.com/Shweta-Mishra-ai/CareerForge_AI)"

SENIORITY_ORDER = ("intern", "junior", "mid", "senior", "lead")
EMPLOYMENT_TYPES = ("full-time", "part-time", "contract", "internship")


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
    remote: bool | None = None  # None = the posting does not say
    seniority: str = ""  # one of SENIORITY_ORDER, or "" when the title does not say
    employment: str = ""  # one of EMPLOYMENT_TYPES, or "" when not stated


@dataclass(frozen=True)
class Preferences:
    """What the user wants. Anything left empty is not scored (the other parts are re-weighted)."""

    location: str = ""
    remote_only: bool = False


@dataclass(frozen=True)
class RankPart:
    key: str
    label: str
    score: int | None  # 0-100, or None when it could not be measured for this posting
    weight: float
    detail: str = ""


@dataclass(frozen=True)
class RankedJob:
    job: Job
    score: int  # 0-100: the weighted parts below, re-weighted over the parts that could be measured
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    parts: tuple[RankPart, ...] = ()
    flags: tuple[str, ...] = ()  # things to check before applying (see `red_flags`)


@dataclass(frozen=True)
class SearchResult:
    jobs: tuple[Job, ...]
    errors: dict[str, str] = field(default_factory=dict)  # provider name -> user-presentable reason


class Provider(Protocol):
    name: str

    def search(self, query: str, limit: int) -> list[Job]: ...


class ProviderError(Exception):
    """A provider failed in a way worth showing the user."""


# --------------------------------------------------------------------------------------------- small parsers


def _text(raw: object, limit: int = DESCRIPTION_LIMIT) -> str:
    soup = BeautifulSoup(str(raw or ""), "html.parser")
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


def _epoch_day(value: object) -> str:
    """A Unix timestamp in seconds or milliseconds -> 'YYYY-MM-DD' ('' when it is not a plausible date)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return ""
    seconds = value / 1000 if value > 1e11 else value
    try:
        return datetime.fromtimestamp(seconds, UTC).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _get_json(
    session: requests.Session, url: str, params: dict, timeout: float, name: str, *, max_bytes: int = MAX_BYTES
) -> object:
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
        if resp.status_code == 404:
            raise ProviderError(f"{name} was not found (check the spelling of the company link)")
        if resp.status_code >= 400:
            raise ProviderError(f"{name} answered with an error ({resp.status_code})")
        body = b""
        for chunk in resp.iter_content(65536):
            body += chunk
            if len(body) > max_bytes:
                raise ProviderError(f"{name} sent an unexpectedly large response")
        try:
            return json.loads(body.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise ProviderError(f"{name} returned an unreadable response") from exc
    finally:
        resp.close()


def _rows(data: object, key: str, name: str) -> list:
    rows = data.get(key) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ProviderError(f"{name} returned an unexpected response")
    return rows


def _list(data: object, name: str) -> list:
    if not isinstance(data, list):
        raise ProviderError(f"{name} returned an unexpected response")
    return data


def _relevant(query: str, job: Job) -> bool:
    """For boards that cannot filter on the server: keep a posting when most of the query's words appear in it."""
    wanted = {stem(t) for t in content_tokens(query)}
    if not wanted:
        return True
    have = {stem(t) for t in content_tokens(f"{job.title} {' '.join(job.tags)} {job.description}")}
    return len(wanted & have) >= max(1, round(len(wanted) * 0.6))


class _Base:
    def __init__(self, *, base_url: str, session: requests.Session | None = None, timeout: float = 10.0):
        self.base_url, self.timeout = base_url, timeout
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False


# --------------------------------------------------------------------------------------------- providers


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
                    remote=True,
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
                    remote=True,
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


class ArbeitnowProvider(_Base):
    """Arbeitnow's public job-board feed. It has no search parameter, so the feed is filtered here."""

    name = "Arbeitnow"

    def __init__(self, *, base_url: str = "https://www.arbeitnow.com", **kw):
        super().__init__(base_url=base_url, **kw)

    def search(self, query: str, limit: int) -> list[Job]:
        data = _get_json(
            self.session, f"{self.base_url}/api/job-board-api", {}, self.timeout, self.name, max_bytes=BOARD_MAX_BYTES
        )
        jobs = []
        for r in _rows(data, "data", self.name):
            if not isinstance(r, dict) or not _str(r.get("title")):
                continue
            kinds = r.get("job_types")
            remote = r.get("remote")
            job = Job(
                title=_str(r.get("title")),
                company=_str(r.get("company_name")),
                location=_str(r.get("location")),
                description=_text(r.get("description")),
                url=_url(r.get("url")),
                source=self.name,
                type=_str(", ".join(k for k in kinds if isinstance(k, str)) if isinstance(kinds, list) else ""),
                posted=_epoch_day(r.get("created_at")),
                tags=tuple(_str(t, 40).lower() for t in (r.get("tags") or []) if isinstance(t, str))[:8],
                remote=remote if isinstance(remote, bool) else None,
            )
            if _relevant(query, job):
                jobs.append(job)
            if len(jobs) == limit:
                break
        return jobs


class RemoteOkProvider(_Base):
    """RemoteOK's public feed. Its terms ask you to link to the posting and name RemoteOK as the source: every Job
    keeps its own `url` and `source`. The first element of the feed is a legal notice, not a job."""

    name = "RemoteOK"

    def __init__(self, *, base_url: str = "https://remoteok.com", **kw):
        super().__init__(base_url=base_url, **kw)

    def search(self, query: str, limit: int) -> list[Job]:
        data = _get_json(self.session, f"{self.base_url}/api", {}, self.timeout, self.name, max_bytes=BOARD_MAX_BYTES)
        jobs = []
        for r in _list(data, self.name):
            if not isinstance(r, dict) or not _str(r.get("position")):
                continue  # the legal-notice element and anything malformed
            lo, hi = r.get("salary_min"), r.get("salary_max")
            numeric = all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in (lo, hi))
            job = Job(
                title=_str(r.get("position")),
                company=_str(r.get("company")),
                location=_str(r.get("location")) or "Remote",
                description=_text(r.get("description")),
                url=_url(r.get("url")),
                source=self.name,
                salary=f"{int(lo)}-{int(hi)}" if numeric else "",
                posted=_day(r.get("date")),
                tags=tuple(_str(t, 40).lower() for t in (r.get("tags") or []) if isinstance(t, str))[:8],
                remote=True,
            )
            if _relevant(query, job):
                jobs.append(job)
            if len(jobs) == limit:
                break
        return jobs


_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,59}")


class GreenhouseProvider(_Base):
    """One company's Greenhouse board (`boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true`)."""

    def __init__(self, token: str, *, base_url: str = "https://boards-api.greenhouse.io", **kw):
        if not _SLUG.fullmatch(token or ""):
            raise ValueError("That is not a Greenhouse board name")
        super().__init__(base_url=base_url, **kw)
        self.token = token
        self.name = f"Greenhouse ({token})"

    def search(self, query: str, limit: int) -> list[Job]:
        url = f"{self.base_url}/v1/boards/{self.token}/jobs"
        data = _get_json(self.session, url, {"content": "true"}, self.timeout, self.name, max_bytes=BOARD_MAX_BYTES)
        jobs = []
        for r in _rows(data, "jobs", self.name):
            if not isinstance(r, dict) or not _str(r.get("title")):
                continue
            place = r.get("location") if isinstance(r.get("location"), dict) else {}
            job = Job(
                title=_str(r.get("title")),
                company=_str(r.get("company_name")) or self.token,
                location=_str(place.get("name")),
                # Greenhouse sends the description as HTML that has itself been HTML-escaped
                description=_text(html.unescape(str(r.get("content") or ""))),
                url=_url(r.get("absolute_url")),
                source=self.name,
                posted=_day(r.get("updated_at")),
            )
            if _relevant(query, job):
                jobs.append(job)
            if len(jobs) == limit:
                break
        return jobs


class LeverProvider(_Base):
    """One company's Lever board (`api.lever.co/v0/postings/<site>?mode=json`)."""

    def __init__(self, site: str, *, base_url: str = "https://api.lever.co", **kw):
        if not _SLUG.fullmatch(site or ""):
            raise ValueError("That is not a Lever board name")
        super().__init__(base_url=base_url, **kw)
        self.site = site
        self.name = f"Lever ({site})"

    def search(self, query: str, limit: int) -> list[Job]:
        url = f"{self.base_url}/v0/postings/{self.site}"
        data = _get_json(self.session, url, {"mode": "json"}, self.timeout, self.name, max_bytes=BOARD_MAX_BYTES)
        jobs = []
        for r in _list(data, self.name):
            if not isinstance(r, dict) or not _str(r.get("text")):
                continue
            cats = r.get("categories") if isinstance(r.get("categories"), dict) else {}
            where = _str(r.get("workplaceType")).lower()
            job = Job(
                title=_str(r.get("text")),
                company=self.site,
                location=_str(cats.get("location")),
                description=_text(r.get("descriptionPlain") or r.get("description")),
                url=_url(r.get("hostedUrl")),
                source=self.name,
                type=_str(cats.get("commitment")),
                posted=_epoch_day(r.get("createdAt")),
                remote=True if where == "remote" else (False if where in ("on-site", "onsite", "hybrid") else None),
            )
            if _relevant(query, job):
                jobs.append(job)
            if len(jobs) == limit:
                break
        return jobs


_GREENHOUSE_HOSTS = frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io"})
_LEVER_HOSTS = frozenset({"jobs.lever.co"})


def parse_career_url(url: str) -> tuple[str, str] | None:
    """('greenhouse' | 'lever', board name) from a company's careers-page link, or None.

    Only the two services' real hosts over http(s) are accepted, so a pasted link can never make the app contact an
    arbitrary host. Examples: https://boards.greenhouse.io/acme, https://jobs.lever.co/acme/1234-abcd.
    """
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        return None
    segments = [s for s in parts.path.split("/") if s]
    if host in _GREENHOUSE_HOSTS:
        if segments[:2] == ["embed", "job_board"]:
            slug = (parse_qs(parts.query).get("for") or [""])[0]
        else:
            slug = segments[0] if segments else ""
        kind = "greenhouse"
    elif host in _LEVER_HOSTS:
        slug, kind = (segments[0] if segments else ""), "lever"
    else:
        return None
    return (kind, slug) if _SLUG.fullmatch(slug) else None


def providers_from_urls(urls: Iterable[str]) -> tuple[list[Provider], list[str]]:
    """(providers, links that were not a Greenhouse or Lever board). Duplicates are collapsed."""
    providers: list[Provider] = []
    rejected: list[str] = []
    seen: set[tuple[str, str]] = set()
    for raw in urls:
        if not raw.strip():
            continue
        parsed = parse_career_url(raw)
        if parsed is None:
            rejected.append(raw.strip()[:100])
        elif parsed not in seen:
            seen.add(parsed)
            kind, slug = parsed
            providers.append(GreenhouseProvider(slug) if kind == "greenhouse" else LeverProvider(slug))
    return providers, rejected


# --------------------------------------------------------------------------------------------- normalising

_INTERN = re.compile(r"\b(?:intern(?:ship)?|working student|apprentice)\b", re.I)
_JUNIOR = re.compile(r"\b(?:junior|jr\.?|entry[- ]level|graduate|trainee|fresher)\b", re.I)
_MID = re.compile(r"\b(?:mid[- ]level|intermediate)\b", re.I)
_SENIOR = re.compile(r"\b(?:senior|sr\.?)\b", re.I)
_LEAD = re.compile(
    r"\b(?:lead(?! generation)|principal|head of|director|vp|vice president|chief"
    r"|staff (?:engineer|software|developer|scientist|architect|designer))\b",
    re.I,
)


def detect_seniority(title: str) -> str:
    """Seniority named in a job title ('' when it names none): never inferred from the description."""
    for level, pattern in (
        ("intern", _INTERN),
        ("junior", _JUNIOR),
        ("lead", _LEAD),
        ("senior", _SENIOR),
        ("mid", _MID),
    ):
        if pattern.search(title or ""):
            return level
    return ""


def detect_employment(kind: str, title: str = "") -> str:
    low = f"{kind} {title}".lower()
    if "intern" in low:
        return "internship"
    if any(w in low for w in ("contract", "freelance", "temporary")):
        return "contract"
    if "part" in low and "time" in low:
        return "part-time"
    if "full" in low or "permanent" in low:
        return "full-time"
    return ""


def detect_remote(job: Job) -> bool | None:
    if job.remote is not None:
        return job.remote
    low = f"{job.location} {job.title}".lower()
    if re.search(r"\b(?:remote|work from home|wfh|anywhere)\b", low) and "hybrid" not in low:
        return True
    return None


def enrich(job: Job) -> Job:
    """Fill in remote / seniority / employment from the fields the provider gave. Never overrides what it stated."""
    return replace(
        job,
        remote=detect_remote(job),
        seniority=job.seniority or detect_seniority(job.title),
        employment=job.employment or detect_employment(job.type, job.title),
    )


# Patterns from consumer-protection advice on job scams (e.g. the US FTC): payment up front, cheques, gift cards or
# crypto, chat-app-only recruiting, bank or ID details before an offer. They are prompts to check, not a verdict.
_FLAGS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:registration|training|processing|application|starter[- ]kit|equipment)\s+(?:fee|cost|deposit)\b"
            r"|\b(?:you (?:will )?(?:need|have) to|must|required to) pay\b"
            r"|\bpay (?:a|the|for)\b.{0,30}\b(?:fee|kit|training)\b",
            re.I,
        ),
        "Asks you to pay a fee. Legitimate employers do not charge to hire you.",
    ),
    (
        re.compile(r"\b(?:gift cards?|wire transfer|western union|bitcoin|crypto(?:currency)?|money order)\b", re.I),
        "Mentions gift cards, wire transfers or crypto: a common sign of a scam.",
    ),
    (
        re.compile(
            r"\b(?:deposit|cash) (?:the |a )?che(?:que|ck)\b|\bche(?:que|ck) (?:will be )?(?:sent|mailed)\b", re.I
        ),
        "Mentions sending you a cheque to deposit: a known scam pattern.",
    ),
    (
        re.compile(
            r"\b(?:telegram|whatsapp|signal)\b.{0,60}\b(?:interview|apply|contact|message)\b|"
            r"\b(?:interview|apply|contact|message)\b.{0,60}\b(?:telegram|whatsapp|signal)\b",
            re.I,
        ),
        "Asks you to continue on a chat app. Check the company on its own website first.",
    ),
    (
        re.compile(r"\b(?:bank (?:account|details)|social security|ssn|passport (?:copy|number)|aadhaar)\b", re.I),
        "Asks for bank or ID details. Share these only after a signed offer from a company you verified.",
    ),
    (
        re.compile(
            r"\b(?:no experience (?:needed|required)|earn up to)\b.{0,80}"
            r"\$?\d[\d,]*\s*(?:/|per|a)\s*(?:day|hour|week)\b",
            re.I,
        ),
        "Promises high pay for no experience. Check the company carefully.",
    ),
)


def red_flags(job: Job) -> tuple[str, ...]:
    """Reasons to double-check a posting before applying. Empty means none of these patterns appeared, which is NOT
    proof that the posting is genuine."""
    text = f"{job.title}\n{job.description}\n{job.salary}"
    flags = [message for pattern, message in _FLAGS if pattern.search(text)]
    if not job.company.strip():
        flags.append("No company name is given. Find out who is hiring before you share anything.")
    return tuple(flags)


# --------------------------------------------------------------------------------------------- search


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
        unique.append(enrich(job))
    return SearchResult(tuple(unique), errors)


# --------------------------------------------------------------------------------------------- ranking

# Design choices, shown to the user next to every score. They are NOT fitted to outcomes: nobody published data that
# would let anyone fit them. Parts that cannot be measured for a posting are dropped and the rest re-weighted.
RANK_WEIGHTS = {"skills": 0.5, "role": 0.2, "seniority": 0.1, "freshness": 0.1, "location": 0.1}
RANK_LABELS = {
    "skills": "Skills the posting asks for",
    "role": "Role matches your titles",
    "seniority": "Seniority fits your experience",
    "freshness": "How recently it was posted",
    "location": "Matches your location preference",
}
FRESHNESS_BANDS = ((7, 100), (14, 85), (30, 65), (60, 35))  # (days at most, score); older scores 10
SENIORITY_FIT = {0: 100, 1: 65, 2: 30}  # distance in levels -> score; 3 or more scores 0


def _candidate_level(years: float) -> int:
    return 0 if years < 1 else 1 if years < 3 else 2 if years < 6 else 3 if years < 9 else 4


def seniority_fit(years: float, level: str) -> int | None:
    if level not in SENIORITY_ORDER:
        return None
    return SENIORITY_FIT.get(abs(_candidate_level(years) - SENIORITY_ORDER.index(level)), 0)


def freshness(posted: str, today: date) -> int | None:
    if not posted:
        return None
    try:
        age = max(0, (today - date.fromisoformat(posted)).days)
    except ValueError:
        return None
    return next((score for days, score in FRESHNESS_BANDS if age <= days), 10)


def location_fit(job: Job, prefs: Preferences) -> int | None:
    wanted = clean_text(prefs.location).lower()
    if prefs.remote_only:
        return {True: 100, None: 40, False: 0}[job.remote]
    if not wanted:
        return None
    if wanted in job.location.lower():
        return 100
    if job.remote:
        return 90
    return 40 if not job.location else 0


def rank_jobs(
    profile: Profile,
    jobs: tuple[Job, ...] | list[Job],
    *,
    min_score: int = 0,
    prefs: Preferences | None = None,
    today: date | None = None,
) -> list[RankedJob]:
    """Score each job from several measurable parts (see RANK_WEIGHTS), best first."""
    p = profile.exportable()
    today = today or date.today()
    prefs = prefs or Preferences()
    years = mt.experience_months(p, today) / 12
    ranked = []
    for job in jobs:
        job = enrich(job)
        jd = parse_job_description(f"{job.title}\n{job.description}")
        hits, misses = mt.match_requirements(p, jd)
        measured: dict[str, tuple[int | None, str]] = {
            "skills": (mt.coverage_score(hits, misses), f"{len(hits)} of {len(hits) + len(misses)} requirements"),
            "role": (mt.role_alignment(p, jd)[0], "your titles against the posting's"),
            "seniority": (seniority_fit(years, job.seniority), f"{job.seniority or 'not stated'} vs {years:.0f} years"),
            "freshness": (freshness(job.posted, today), job.posted or "no date given"),
            "location": (location_fit(job, prefs), job.location or "no location given"),
        }
        parts = tuple(RankPart(k, RANK_LABELS[k], v, RANK_WEIGHTS[k], d) for k, (v, d) in measured.items())
        usable = [(x.weight, x.score) for x in parts if x.score is not None]
        score = round(sum(w * v for w, v in usable) / sum(w for w, _ in usable)) if usable else 0
        if score >= min_score:
            ranked.append(
                RankedJob(
                    job,
                    score,
                    tuple(m.requirement.term for m in hits[:8]),
                    tuple(r.term for r in misses[:8]),
                    parts,
                    red_flags(job),
                )
            )
    return sorted(ranked, key=lambda r: (-r.score, -int(r.job.posted.replace("-", "") or 0), r.job.title))


def filter_jobs(
    ranked: list[RankedJob],
    *,
    remote_only: bool = False,
    seniority: Iterable[str] = (),
    employment: Iterable[str] = (),
    posted_within_days: int | None = None,
    hide_flagged: bool = False,
    today: date | None = None,
) -> list[RankedJob]:
    """Narrow ranked results. A posting that does not state a field is kept unless the filter needs that field."""
    today = today or date.today()
    levels, kinds = set(seniority), set(employment)
    out = []
    for r in ranked:
        j = r.job
        if remote_only and j.remote is not True:
            continue
        if levels and j.seniority not in levels:
            continue
        if kinds and j.employment not in kinds:
            continue
        if posted_within_days is not None and not (
            j.posted and (today - date.fromisoformat(j.posted)).days <= posted_within_days
        ):
            continue
        if hide_flagged and r.flags:
            continue
        out.append(r)
    return out


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
