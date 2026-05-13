"""Indeed job scraper via RSS feed.

Indeed's RSS endpoint:
  https://www.indeed.com/rss?q=<query>&l=<location>&radius=<miles>&jt=fulltime

This is best-effort: Indeed has rate-limited and occasionally blocked RSS.
Errors are non-fatal; caller should catch and log.

We run several targeted queries to maximise coverage for Ethan's profile,
then deduplicate by job ID (extracted from the RSS link).
"""

import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import List
from urllib.parse import urlencode

import httpx

from ..models import JobPosting

log = logging.getLogger("email_agent.indeed")

BASE_URL = "https://www.indeed.com/rss"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# Queries to run. (query, location) pairs. Empty location = remote/anywhere.
_QUERIES: List[tuple[str, str]] = [
    ("\"product manager\" AI data platform", "Boston, MA"),
    ("\"senior product manager\" AI machine learning", "Boston, MA"),
    ("\"product manager\" applied AI LLM", "Boston, MA"),
    ("\"product manager\" data platform GTM", "Boston, MA"),
    ("\"product manager\" AI data platform", ""),         # remote
    ("\"applied AI product manager\"", ""),
    ("\"data platform product manager\"", ""),
    ("\"GTM product manager\" AI", ""),
]


def fetch_all(radius_miles: int = 50) -> List[JobPosting]:
    """Run all configured queries and return deduplicated postings."""
    seen_ids: set[str] = set()
    out: List[JobPosting] = []

    for query, location in _QUERIES:
        try:
            jobs = _fetch_one(query, location, radius_miles)
            for j in jobs:
                if j.external_id not in seen_ids:
                    seen_ids.add(j.external_id)
                    out.append(j)
            time.sleep(1.5)  # be polite between requests
        except Exception as e:
            log.warning("Indeed RSS query failed (q=%r l=%r): %s", query, location, e)

    log.info("Indeed: pulled %d unique postings across %d queries", len(out), len(_QUERIES))
    return out


def _fetch_one(query: str, location: str, radius: int) -> List[JobPosting]:
    params: dict = {
        "q": query,
        "sort": "date",
        "fromage": "7",   # last 7 days
    }
    if location:
        params["l"] = location
        params["radius"] = str(radius)

    url = f"{BASE_URL}?{urlencode(params)}"
    r = httpx.get(url, headers=HEADERS, timeout=20.0, follow_redirects=True)
    r.raise_for_status()
    return _parse_rss(r.text)


def _parse_rss(xml_text: str) -> List[JobPosting]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.warning("Indeed RSS parse error: %s", e)
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    out: List[JobPosting] = []
    for item in channel.findall("item"):
        title = _text(item, "title")
        link = _text(item, "link")
        company = _extract_company(item)
        location = _extract_location(item)
        description = _strip_html(_text(item, "description"))
        external_id = _extract_id(link) or hashlib.md5(link.encode()).hexdigest()[:16]

        if not title or not link:
            continue

        out.append(
            JobPosting(
                company=company or "Unknown (Indeed)",
                title=title,
                url=link,
                location=location,
                description=description,
                source="indeed",
                external_id=external_id,
            )
        )
    return out


def _text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _extract_company(item: ET.Element) -> str:
    # Indeed puts company in <source> or buries it in <title> as "Job Title - Company"
    source = item.find("source")
    if source is not None and source.text:
        return source.text.strip()
    title = _text(item, "title")
    # format: "Job Title - Company Name"
    parts = title.rsplit(" - ", 1)
    if len(parts) == 2:
        return parts[-1].strip()
    return ""


def _extract_location(item: ET.Element) -> str:
    # Indeed sometimes puts location in a custom tag or the description snippet.
    for tag in ("location", "{http://www.indeed.com/}location"):
        el = item.find(tag)
        if el is not None and el.text:
            return el.text.strip()
    # Try to find in description: "Location: Boston, MA"
    desc = _text(item, "description")
    m = re.search(r"location[:\s]+([A-Za-z ,]+(?:,\s*[A-Z]{2})?)", desc, re.I)
    if m:
        return m.group(1).strip()
    return ""


def _extract_id(url: str) -> str:
    # Indeed job URLs contain jk=<id>
    m = re.search(r"[?&]jk=([a-z0-9]+)", url, re.I)
    return m.group(1) if m else ""


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()
