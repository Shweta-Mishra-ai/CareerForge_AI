import pdfplumber
import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
import random

def extract_pdf_text(uploaded_file):
    text = []
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            # Extract text preserving layout where possible
            page_text = page.extract_text(layout=True)
            if page_text:
                text.append(page_text)
    return "\n".join(text)

def scrape_url_text(url):
    """
    Aggressively tries to fetch public LinkedIn profile data using
    multiple realistic browser headers to bypass bot detection.
    Falls back gracefully to name extraction from the URL slug.
    """
    # Rotate through realistic browser User-Agents
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    ]
    
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }

    try:
        session = requests.Session()
        # First visit the LinkedIn homepage to get cookies like a real browser
        session.get("https://www.linkedin.com", headers=headers, timeout=8)
        
        # Now fetch the actual profile page
        response = session.get(url, headers=headers, timeout=10, allow_redirects=True)
        soup = BeautifulSoup(response.text, 'html.parser')

        extracted_data = []

        # Try og: meta tags (LinkedIn sometimes serves these for public profiles)
        meta_title = soup.find("meta", property="og:title")
        meta_desc = soup.find("meta", property="og:description")
        
        if meta_title and meta_title.get("content"):
            extracted_data.append(f"Profile Name/Headline: {meta_title.get('content')}")
        if meta_desc and meta_desc.get("content"):
            extracted_data.append(f"Summary: {meta_desc.get('content')}")

        # Try standard title tag
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            extracted_data.append(f"Page Title: {title_tag.string}")

        # Try to get any visible text before the auth wall kicks in
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        
        page_text = soup.get_text(separator=' ', strip=True)
        
        # Filter out pure authwall redirects
        if len(page_text) > 200 and "authwall" not in page_text.lower()[:200]:
            extracted_data.append(f"Page Content:\n{page_text[:2000]}")

        if extracted_data:
            return "\n".join(extracted_data)
        
    except Exception:
        pass
    
    # Final fallback: extract name from the URL slug itself and pass it to the AI
    return _name_from_url(url)


def _name_from_url(url):
    """Extract the person's name from the LinkedIn URL slug as a last resort."""
    try:
        path = urllib.parse.urlparse(url).path
        slug = path.strip("/").split("/")[-1]
        clean_name = re.sub(r'[^a-zA-Z\s]', ' ', slug.replace('-', ' ')).strip().title()
        return f"Name: {clean_name}\nLinkedIn URL: {url}\nNote: Only the name could be extracted from the URL."
    except Exception:
        return "Name: Candidate\nNote: Could not extract data from URL."
