"""
core/scraper.py
===============
Data extraction layer — PDF + URL scraping.

CHANGES from original:
- pdfplumber kept (better than PyPDF2 for layout-heavy PDFs)
- URL scraper logic preserved, just cleaner structure
- _name_from_url() same logic, just cleaner
- No st imports — pure utility module
"""

import random
import re
import urllib.parse

import pdfplumber
import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────

REQUEST_TIMEOUT = 10  # seconds

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]

_BASE_HEADERS = {
    "Accept":                  "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language":         "en-US,en;q=0.9",
    "Accept-Encoding":         "gzip, deflate, br",
    "DNT":                     "1",
    "Connection":              "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest":          "document",
    "Sec-Fetch-Mode":          "navigate",
    "Sec-Fetch-Site":          "none",
    "Sec-Fetch-User":          "?1",
    "Cache-Control":           "max-age=0",
}


# ─────────────────────────────────────────────────────
# PDF EXTRACTION
# ─────────────────────────────────────────────────────

def extract_pdf_text(uploaded_file) -> str:
    """
    Extract text from a PDF using pdfplumber.
    layout=True preserves column order for multi-column CVs.
    """
    pages = []
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text(layout=True)
            if page_text:
                pages.append(page_text)
    return "\n".join(pages)


# ─────────────────────────────────────────────────────
# URL SCRAPING
# ─────────────────────────────────────────────────────

def scrape_url_text(url: str) -> str:
    """
    Try to scrape a public profile URL.

    Strategy:
      1. Visit LinkedIn homepage to get cookies (anti-bot bypass)
      2. Fetch actual profile with randomised UA + full browser headers
      3. Extract og: meta tags + visible page text
      4. If authwall detected or text too short → fallback to name-from-slug

    Returns whatever text could be extracted (never raises).
    """
    headers = {**_BASE_HEADERS, "User-Agent": random.choice(_USER_AGENTS)}

    try:
        session = requests.Session()
        # Warm up session with real cookies
        session.get("https://www.linkedin.com", headers=headers, timeout=8)

        response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        soup = BeautifulSoup(response.text, "html.parser")

        extracted = []

        # og: meta tags (sometimes served even for public profiles)
        og_title = soup.find("meta", property="og:title")
        og_desc  = soup.find("meta", property="og:description")
        if og_title and og_title.get("content"):
            extracted.append(f"Profile: {og_title['content']}")
        if og_desc and og_desc.get("content"):
            extracted.append(f"Summary: {og_desc['content']}")

        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            extracted.append(f"Page Title: {title_tag.string}")

        # Strip scripts/styles before getting visible text
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        page_text = soup.get_text(separator=" ", strip=True)

        # Only use page text if it's real content (not just the authwall)
        is_authwall = "authwall" in page_text.lower()[:300]
        if len(page_text) > 200 and not is_authwall:
            extracted.append(f"Page Content:\n{page_text[:2000]}")

        if extracted:
            return "\n".join(extracted)

    except Exception:
        pass  # Fall through to slug fallback

    return _name_from_url(url)


# ─────────────────────────────────────────────────────
# FALLBACK
# ─────────────────────────────────────────────────────

def _name_from_url(url: str) -> str:
    """
    Last resort: extract a name hint from the LinkedIn URL slug.
    e.g. linkedin.com/in/john-doe-123 → "John Doe"
    """
    try:
        path = urllib.parse.urlparse(url).path
        slug = path.strip("/").split("/")[-1]
        # Remove trailing numbers/IDs (e.g. john-doe-123a → john-doe)
        slug = re.sub(r"[^a-zA-Z\-]", "", slug)
        clean_name = slug.replace("-", " ").strip().title()
        if clean_name:
            return (
                f"Name: {clean_name}\n"
                f"LinkedIn URL: {url}\n"
                f"Note: Only the name could be extracted from the URL. "
                f"For best results, please use the PDF upload method."
            )
    except Exception:
        pass
    return (
        "Name: Candidate\n"
        "Note: Could not extract data from this URL. "
        "Please use the PDF upload method instead."
    )
