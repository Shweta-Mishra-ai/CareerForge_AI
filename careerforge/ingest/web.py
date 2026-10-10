"""Safe fetching of user-supplied web pages (job postings etc.).

The old fetchers requested any URL a user typed, following redirects, with no limits - a server-side request
forgery hole on any hosted deployment (cloud metadata, internal admin pages). Defences here:

* http/https only, ports 80/443 only, no credentials in the URL, length limit
* the hostname is resolved by us and EVERY address must be globally routable (so 127.1, 2130706433, 0x7f.1,
  ::ffff:127.0.0.1, 169.254.169.254, 10/8, 100.64/10 ... are all refused)
* the connection is PINNED to a validated address (SNI and certificate checks still use the hostname), so DNS
  rebinding between "check" and "connect" is impossible
* redirects are followed by hand, each hop re-validated, max 3
* size cap while streaming, content-type allow-list, timeouts, no cookies, no environment proxies
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from careerforge.ingest.errors import FetchFailed, SourceNotSupported, UnsafeURL
from careerforge.text import clean_text

USER_AGENT = "CareerForgeBot/0.2 (+https://github.com/Shweta-Mishra-ai/CareerForge_AI; user-initiated fetch)"
MAX_URL_LENGTH = 2048
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

Resolver = Callable[[str, int], list[str]]


@dataclass(frozen=True)
class FetchPolicy:
    allow_private: bool = False  # tests only; never exposed in the UI
    ports: tuple[int, ...] | None = (80, 443)
    max_bytes: int = 1_500_000
    timeout: float = 10.0
    max_redirects: int = 3
    verify: bool | str = True  # tests may pass a CA bundle path


DEFAULT_POLICY = FetchPolicy()


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchFailed("That address could not be found") from exc
    return list(dict.fromkeys(info[4][0] for info in infos))


def is_public_ip(value: str) -> bool:
    """True only for globally routable addresses (unwraps IPv4-mapped and NAT64 forms first)."""
    try:
        ip = ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast


def check_url(
    url: str, policy: FetchPolicy = DEFAULT_POLICY, resolver: Resolver = system_resolver
) -> tuple[str, str, int, list[str]]:
    """Validate a URL. Returns (url, host, port, validated_ips) or raises UnsafeURL."""
    if not url or len(url) > MAX_URL_LENGTH or re.search(r"[\s<>\"'`\\]", url):
        raise UnsafeURL("That is not a valid web address")
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise UnsafeURL("Only http:// and https:// addresses can be fetched")
    if parts.username or parts.password:
        raise UnsafeURL("Addresses with embedded credentials are not allowed")
    try:
        host, port = parts.hostname, parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise UnsafeURL("That is not a valid web address") from exc
    if not host:
        raise UnsafeURL("That is not a valid web address")
    if policy.ports is not None and port not in policy.ports:
        raise UnsafeURL("That port is not allowed")
    ips = resolver(host.rstrip("."), port)
    if not ips:
        raise FetchFailed("That address could not be found")
    if not policy.allow_private and not all(is_public_ip(ip) for ip in ips):
        raise UnsafeURL("That address points to a private or internal network and cannot be fetched")
    return url, host.rstrip("."), port, ips


class _PinnedAdapter(HTTPAdapter):
    """Connects to a fixed IP while keeping SNI and certificate verification bound to the real hostname."""

    def __init__(self, hostname: str):
        self._hostname = hostname
        super().__init__(max_retries=0)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):  # noqa: ANN001, ANN003
        pool_kwargs["server_hostname"] = self._hostname
        pool_kwargs["assert_hostname"] = self._hostname
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


@dataclass(frozen=True)
class FetchedPage:
    url: str
    status: int
    content_type: str
    body: bytes


def _request_once(url: str, host: str, port: int, ip: str, policy: FetchPolicy) -> requests.Response:
    parts = urlsplit(url)
    literal = f"[{ip}]" if ":" in ip else ip
    netloc = f"{literal}:{port}"
    pinned = parts._replace(netloc=netloc).geturl()
    default_port = 443 if parts.scheme.lower() == "https" else 80
    session = requests.Session()
    session.trust_env = False  # no proxies/netrc from the environment
    session.mount(f"{parts.scheme.lower()}://", _PinnedAdapter(host))
    headers = {
        "Host": host if port == default_port else f"{host}:{port}",
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }
    return session.get(pinned, headers=headers, stream=True, allow_redirects=False, timeout=policy.timeout,
                       verify=policy.verify)  # fmt: skip


def fetch_page(url: str, policy: FetchPolicy = DEFAULT_POLICY, resolver: Resolver = system_resolver) -> FetchedPage:
    """Fetch one page safely. Raises UnsafeURL / FetchFailed / SourceNotSupported with user-presentable messages."""
    _refuse_linkedin(url)
    current = url
    for _hop in range(policy.max_redirects + 1):
        current, host, port, ips = check_url(current, policy, resolver)
        _refuse_linkedin(current)
        resp = None
        last_error: Exception | None = None
        for ip in ips[:2]:
            try:
                resp = _request_once(current, host, port, ip, policy)
                break
            except requests.exceptions.SSLError as exc:
                raise FetchFailed("The site's secure connection (HTTPS certificate) could not be verified") from exc
            except requests.exceptions.RequestException as exc:
                last_error = exc
        if resp is None:
            raise FetchFailed("The site could not be reached or took too long to answer") from last_error
        try:
            if resp.status_code in (301, 302, 303, 307, 308):
                target = resp.headers.get("Location")
                if not target:
                    raise FetchFailed("The site sent an invalid redirect")
                current = urljoin(current, target)
                continue
            return _read_body(resp, current, policy)
        finally:
            resp.close()
    raise FetchFailed("The site redirected too many times")


def _read_body(resp: requests.Response, url: str, policy: FetchPolicy) -> FetchedPage:
    status = resp.status_code
    if status in (401, 403, 999):
        raise FetchFailed("This page needs a login or blocks automated access. Paste the text instead")
    if status == 404 or status == 410:
        raise FetchFailed("That page was not found")
    if status == 429:
        raise FetchFailed("The site is rate-limiting requests right now. Try again later or paste the text")
    if status >= 400:
        raise FetchFailed(f"The site answered with an error ({status})")
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if ctype and ctype not in _TEXT_TYPES:
        hint = " Download it and upload it as a file instead." if ctype == "application/pdf" else ""
        raise FetchFailed(f"That address is not a web page ({ctype}).{hint}")
    declared = resp.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > policy.max_bytes:
        raise FetchFailed("That page is too large to read")
    chunks, size = [], 0
    for chunk in resp.iter_content(chunk_size=65536):
        size += len(chunk)
        if size > policy.max_bytes:
            raise FetchFailed("That page is too large to read")
        chunks.append(chunk)
    return FetchedPage(url, status, ctype or "text/html", b"".join(chunks))


def _refuse_linkedin(url: str) -> None:
    host = (urlsplit(url).hostname or "").lower()
    if host == "linkedin.com" or host.endswith(".linkedin.com") or host == "lnkd.in":
        raise SourceNotSupported(
            "LinkedIn does not allow automated reading of its pages. Use your profile's 'Save to PDF', your LinkedIn "
            "data export (.zip), or paste the text instead"
        )


# ── page -> text ────────────────────────────────────────────────────────────

_NOISE = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "iframe")
_WALL = re.compile(
    r"authwall|captcha|are you a robot|enable javascript|access denied"
    r"|(?:sign|log) in to (?:view|continue)",
    re.I,
)


_BLOCKS = (
    "p",
    "div",
    "section",
    "article",
    "ul",
    "ol",
    "table",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "br",
    "blockquote",
)


def _visible_text(root: BeautifulSoup) -> str:
    """Text with line breaks only at block elements, so inline tags (<b>, <a>, <span>) don't split sentences."""
    for tag in root.find_all(_BLOCKS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    for li in root.find_all("li"):
        li.insert_before("\n• ")
        li.insert_after("\n")
    return root.get_text("")


def _html_to_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    return [ln for ln in (clean_text(x) for x in _visible_text(root).split("\n")) if ln]


def _jsonld_job(soup: BeautifulSoup) -> dict | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                kind = node.get("@type")
                if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                    return node
                stack.extend(node.get("@graph", []) if isinstance(node.get("@graph"), list) else [])
    return None


def _flat(value: object) -> str:
    """JSON-LD values are strings, {'name': ...} objects or lists of either."""
    if isinstance(value, dict):
        return clean_text(value.get("name") or value.get("value") or "")
    if isinstance(value, list):
        return ", ".join(x for x in (_flat(v) for v in value) if x)
    return clean_text(value)


def _jsonld_location(place: object) -> str:
    if isinstance(place, list) and place:
        place = place[0]
    address = place.get("address") if isinstance(place, dict) else None
    if isinstance(address, dict):
        keys = ("addressLocality", "addressRegion", "addressCountry")
        return ", ".join(x for x in (_flat(address.get(k)) for k in keys) if x)
    return _flat(place)


def _jsonld_text(job: dict) -> str:
    description = _visible_text(BeautifulSoup(str(job.get("description") or ""), "html.parser"))
    fields = [
        ("Job title", _flat(job.get("title"))),
        ("Company", _flat(job.get("hiringOrganization"))),
        ("Location", _jsonld_location(job.get("jobLocation"))),
        ("Employment type", _flat(job.get("employmentType"))),
        ("Skills", _flat(job.get("skills"))),
        ("Qualifications", _flat(job.get("qualifications"))),
        ("Experience", _flat(job.get("experienceRequirements"))),
    ]
    header = [f"{label}: {value}" for label, value in fields if value]
    return "\n".join([*header, "", clean_text(description, multiline=True)]).strip()


def page_to_text(page: FetchedPage, *, max_chars: int = 30000) -> str:
    """Readable text of a fetched page; prefers structured JobPosting data when the site provides it."""
    html = page.body.decode(page_encoding(page), errors="replace")
    if page.content_type == "text/plain":
        return clean_text(html, multiline=True)[:max_chars]
    soup = BeautifulSoup(html, "html.parser")
    if job := _jsonld_job(soup):
        text = _jsonld_text(job)
        if len(text) > 80:
            return text[:max_chars]
    text = "\n".join(_html_to_lines(html))
    return text[:max_chars]


def page_encoding(page: FetchedPage) -> str:
    m = re.search(rb"charset=['\"]?([\w-]+)", page.body[:2048], re.I)
    return m.group(1).decode("ascii", "ignore") if m else "utf-8"


def fetch_job_text(url: str, policy: FetchPolicy = DEFAULT_POLICY, resolver: Resolver = system_resolver) -> str:
    """Job posting URL -> plain text. Raises with an explanation when the page is a login wall or has no content."""
    text = page_to_text(fetch_page(url, policy, resolver))
    looks_like_wall = len(text) < 200 and _WALL.search(text)
    if looks_like_wall or len(text) < 60:
        raise FetchFailed(
            "No readable job description was found on that page (it may need a login or JavaScript). "
            "Paste the text instead"
        )
    return text
