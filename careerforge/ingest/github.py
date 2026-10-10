"""GitHub profile import (public REST API).

Principles (each fixes a flaw in the old importer):
* Only what GitHub states. No name guessed from the username, no filler like "A Python project", and the
  user's languages are offered as skill *suggestions* - never silently added.
* Projects only. GitHub says nothing about employment, so experience is never produced from it.
* Honest limits: unauthenticated API access is rate limited (the error says when it resets), only the most
  recently pushed 100 repositories are read, and ownership of the account cannot be verified without OAuth -
  the UI must tell users to import only their own account.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import requests

from careerforge import skills as taxonomy
from careerforge.ingest.errors import FetchFailed, IngestError
from careerforge.models import Profile, Project
from careerforge.text import clean_text, normalize_url

API = "https://api.github.com"
_USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_RESERVED = {
    *("orgs", "settings", "login", "explore", "topics", "marketplace", "sponsors", "features", "about", "pricing"),
    *("enterprise", "collections", "trending", "search", "notifications", "pulls", "issues"),
}


@dataclass(frozen=True)
class GitHubImport:
    username: str
    name: str = ""
    bio: str = ""
    location: str = ""
    website: str = ""
    company: str = ""
    profile_url: str = ""
    public_repos: int = 0
    followers: int = 0
    total_stars: int = 0
    projects: tuple[Project, ...] = ()
    languages: tuple[str, ...] = ()  # known skills seen in the user's own (non-fork) repos, most used first
    warnings: tuple[str, ...] = field(default_factory=tuple)


def parse_github_user(value: str) -> str:
    """Accept 'octocat', '@octocat', 'github.com/octocat', 'https://github.com/octocat/repo'. Raises IngestError."""
    text = clean_text(value).lstrip("@")
    if not text:
        raise IngestError("Enter a GitHub username or profile link")
    if "/" in text or "." in text:
        parts = urlsplit(text if "://" in text else f"https://{text}")
        host = (parts.hostname or "").lower()
        if host not in ("github.com", "www.github.com"):
            raise IngestError("That is not a github.com link")
        segments = [s for s in parts.path.split("/") if s]
        text = segments[0] if segments else ""
    if not _USERNAME.fullmatch(text) or text.lower() in _RESERVED:
        raise IngestError("That does not look like a valid GitHub username")
    return text


def _get(session: requests.Session, url: str, headers: dict[str, str], timeout: float) -> requests.Response:
    try:
        resp = session.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise FetchFailed("GitHub could not be reached right now. Try again in a moment") from exc
    if resp.status_code == 404:
        raise FetchFailed("That GitHub user was not found")
    if resp.status_code in (403, 429):
        if resp.headers.get("X-RateLimit-Remaining") == "0":
            when = ""
            reset = resp.headers.get("X-RateLimit-Reset", "")
            if reset.isdigit():
                when = f" It resets at {datetime.fromtimestamp(int(reset), UTC):%H:%M} UTC."
            raise FetchFailed(f"GitHub's request limit for this server has been reached.{when} Try again later")
        raise FetchFailed("GitHub refused the request")
    if resp.status_code == 401:
        raise FetchFailed("The configured GitHub token was rejected")
    if resp.status_code >= 400:
        raise FetchFailed(f"GitHub answered with an error ({resp.status_code})")
    return resp


def _json(resp: requests.Response) -> object:
    try:
        return resp.json()
    except requests.exceptions.JSONDecodeError as exc:  # NOT ValueError: our own FetchFailed is one
        raise FetchFailed("GitHub returned an unreadable response") from exc


def _s(value: object, limit: int) -> str:
    return clean_text(value)[:limit] if isinstance(value, str) else ""


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _project(repo: dict) -> Project | None:
    name = _s(repo.get("name"), 150)
    if not name:
        return None
    tech = [t for t in [repo.get("language"), *(repo.get("topics") or [])] if isinstance(t, str)]
    known = [t for t in taxonomy.dedupe(tech) if taxonomy.lookup(t)]
    try:
        url = normalize_url(repo.get("html_url") or "", ("github.com",))
    except ValueError:
        url = ""
    return Project(name=name, description=_s(repo.get("description"), 600), tech=known[:10], url=url,
                   stars=_int(repo.get("stargazers_count")), origin="extracted")  # fmt: skip


def fetch_github(
    user: str,
    *,
    token: str | None = None,
    max_projects: int = 6,
    base_url: str = API,
    session: requests.Session | None = None,
    timeout: float = 8.0,
) -> GitHubImport:
    """Read a public GitHub profile + repositories. Raises IngestError subclasses with friendly messages."""
    username = parse_github_user(user)
    own_session = session is None
    session = session or requests.Session()
    if own_session:
        session.trust_env = False
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "CareerForge-AI/0.2",
               "X-GitHub-Api-Version": "2022-11-28"}  # fmt: skip
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        profile = _json(_get(session, f"{base_url}/users/{username}", headers, timeout))
        repos_url = f"{base_url}/users/{username}/repos?type=owner&sort=pushed&per_page=100"
        repos = _json(_get(session, repos_url, headers, timeout))
    finally:
        if own_session:
            session.close()
    if not isinstance(profile, dict) or not isinstance(repos, list):
        raise FetchFailed("GitHub returned an unexpected response")

    warnings: list[str] = []
    public_repos = _int(profile.get("public_repos"))
    if public_repos > 100:
        warnings.append(
            f"The account has {public_repos} public repositories; only the 100 most recently pushed were read"
        )

    own = [r for r in repos if isinstance(r, dict) and not r.get("fork") and not r.get("archived")
           and str(r.get("name", "")).lower() != username.lower()]  # fmt: skip
    own.sort(key=lambda r: (_int(r.get("stargazers_count")), str(r.get("pushed_at") or "")), reverse=True)
    projects = tuple(p for p in (_project(r) for r in own[:max_projects]) if p)
    counts = Counter(r["language"] for r in own if isinstance(r.get("language"), str))
    languages = tuple(n for n in taxonomy.dedupe([lang for lang, _ in counts.most_common()]) if taxonomy.lookup(n))

    try:
        website = normalize_url(profile.get("blog") or "")
    except ValueError:
        website = ""
    return GitHubImport(
        username=username, name=_s(profile.get("name"), 120), bio=_s(profile.get("bio"), 300),
        location=_s(profile.get("location"), 100), website=website, company=_s(profile.get("company"), 100),
        profile_url=f"https://github.com/{username}", public_repos=public_repos,
        followers=_int(profile.get("followers")), total_stars=sum(_int(r.get("stargazers_count")) for r in own),
        projects=projects, languages=languages, warnings=tuple(warnings),
    )  # fmt: skip


def merge_github(profile: Profile, imp: GitHubImport, *, add_skills: bool = False) -> Profile:
    """Fill gaps in `profile` from a GitHub import. Never overwrites, never touches experience or education."""
    data = profile.model_dump()
    if not data["name"] and imp.name:
        data["name"] = imp.name
    contact = data["contact"]
    contact["github"] = contact["github"] or imp.profile_url
    contact["location"] = contact["location"] or imp.location
    contact["website"] = contact["website"] or imp.website
    have = {p["name"].lower() for p in data["projects"]}
    for project in imp.projects:
        if project.name.lower() not in have:
            data["projects"].append(project.model_dump())
            have.add(project.name.lower())
    if add_skills:
        data["skills"] = taxonomy.dedupe([*data["skills"], *imp.languages])[:80]
    return Profile.model_validate(data)
