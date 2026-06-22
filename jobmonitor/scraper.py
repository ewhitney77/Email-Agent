"""Career-page scraper.

Strategy for each page:
  1. Try a plain HTTP fetch (requests) + BeautifulSoup parsing.
  2. If that fails or returns suspiciously little content (a sign the page is
     rendered client-side with JavaScript), fall back to Playwright.

Posting links are extracted with a generic heuristic that looks for anchors
pointing at job-detail URLs. Because every career site is laid out differently,
each target in targets.json may supply an optional CSS ``link_selector`` to
override the heuristic.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import Config

# href fragments that strongly suggest a link points to an individual posting.
JOB_URL_HINTS = re.compile(
    r"(/jobs?/|/job/|/careers?/|/positions?/|/opening|/vacanc|/gh_jid|"
    r"greenhouse\.io|lever\.co|myworkdayjobs|ashbyhq|smartrecruiters|"
    r"/apply|jobid=|/p/|/role/)",
    re.IGNORECASE,
)

# Link text that is almost never an actual job title -> skip.
SKIP_TEXT = re.compile(
    r"^(apply|learn more|view all|see all|all jobs|search|home|back|next|"
    r"previous|read more|benefits|culture|life at|about|contact|login|"
    r"sign in|privacy|cookie|terms)$",
    re.IGNORECASE,
)


@dataclass
class Posting:
    company: str
    title: str
    url: str
    description: str = ""


def _looks_thin(html: str) -> bool:
    """Heuristic: pages that need JS often ship almost no body text."""
    if not html:
        return True
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return len(text) < 500


def fetch_static(url: str, cfg: Config) -> str | None:
    try:
        resp = requests.get(
            url,
            timeout=cfg.request_timeout,
            headers={"User-Agent": cfg.user_agent, "Accept-Language": "en-US,en;q=0.9"},
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException:
        return None


def fetch_rendered(url: str, cfg: Config) -> str | None:
    """Render a page with Playwright (Chromium). Returns None if unavailable."""
    if not cfg.use_playwright:
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=cfg.user_agent)
            page.goto(url, timeout=cfg.request_timeout * 1000, wait_until="networkidle")
            html = page.content()
            browser.close()
            return html
    except Exception:
        return None


def get_html(url: str, cfg: Config, render: str = "auto") -> str | None:
    """Fetch HTML honoring the target's render preference.

    render: "static" -> requests only; "js" -> Playwright only;
            "auto" -> requests first, Playwright if the result looks thin.
    """
    if render == "js":
        return fetch_rendered(url, cfg)
    if render == "static":
        return fetch_static(url, cfg)
    # auto
    html = fetch_static(url, cfg)
    if html is None or _looks_thin(html):
        rendered = fetch_rendered(url, cfg)
        if rendered is not None:
            return rendered
    return html


def extract_postings(html: str, base_url: str, target: dict, cfg: Config) -> list[Posting]:
    """Parse a listing page into individual postings (title + absolute URL)."""
    soup = BeautifulSoup(html, "html.parser")
    company = target.get("company", urlparse(base_url).netloc)
    selector = target.get("link_selector")

    anchors = soup.select(selector) if selector else soup.find_all("a", href=True)

    seen_urls: set[str] = set()
    postings: list[Posting] = []
    for a in anchors:
        href = a.get("href")
        if not href:
            continue
        abs_url = urljoin(base_url, href.split("#")[0])
        if abs_url in seen_urls or abs_url.rstrip("/") == base_url.rstrip("/"):
            continue
        title = " ".join(a.get_text(" ", strip=True).split())

        # Without an explicit selector, keep only links that look like postings.
        if not selector and not JOB_URL_HINTS.search(abs_url):
            continue
        if not title or len(title) < 3 or SKIP_TEXT.match(title):
            continue
        if abs_url.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue

        seen_urls.add(abs_url)
        postings.append(Posting(company=company, title=title, url=abs_url))
        if len(postings) >= cfg.max_listings_per_company:
            break
    return postings


def fetch_description(url: str, cfg: Config, render: str = "auto") -> str:
    """Follow a posting link and return its visible text."""
    html = get_html(url, cfg, render=render)
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "svg"]):
        tag.decompose()
    # Prefer a main/article region when present, else fall back to body.
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text("\n", strip=True)
    # Collapse runs of blank lines.
    return re.sub(r"\n{3,}", "\n\n", text)


def _html_to_text(raw_html: str) -> str:
    """Strip tags from an HTML fragment and normalize whitespace."""
    soup = BeautifulSoup(raw_html or "", "html.parser")
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))


# --------------------------------------------------------------------------- #
# ATS APIs -- structured, reliable, and selector-free. Preferred when a target
# declares an "ats" block in targets.json.
# --------------------------------------------------------------------------- #
def fetch_greenhouse(token: str, company: str, cfg: Config) -> list[Posting]:
    """Greenhouse Job Board API. One call returns every job *with* full content.

    https://developers.greenhouse.io/job-board.html
    """
    api = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    try:
        resp = requests.get(api, timeout=cfg.request_timeout, headers={"User-Agent": cfg.user_agent})
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []
    postings: list[Posting] = []
    for job in data.get("jobs", [])[: cfg.max_listings_per_company]:
        content = html_lib.unescape(job.get("content", "") or "")
        postings.append(
            Posting(
                company=company,
                title=(job.get("title") or "").strip(),
                url=job.get("absolute_url", ""),
                description=_html_to_text(content),
            )
        )
    return postings


def fetch_smartrecruiters(company_id: str, company: str, cfg: Config) -> list[Posting]:
    """SmartRecruiters public Posting API (list + per-posting detail for text).

    https://dev.smartrecruiters.com/customer-api/posting-api/
    """
    base = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
    try:
        resp = requests.get(
            base,
            params={"limit": min(cfg.max_listings_per_company, 100)},
            timeout=cfg.request_timeout,
            headers={"User-Agent": cfg.user_agent},
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    postings: list[Posting] = []
    for item in data.get("content", [])[: cfg.max_listings_per_company]:
        pid = item.get("id")
        title = (item.get("name") or "").strip()
        apply_url = f"https://careers.smartrecruiters.com/{company_id}/{pid}"
        description = ""
        try:
            detail = requests.get(
                f"{base}/{pid}", timeout=cfg.request_timeout, headers={"User-Agent": cfg.user_agent}
            )
            if detail.ok:
                sections = (detail.json().get("jobAd") or {}).get("sections") or {}
                parts = []
                for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
                    text = (sections.get(key) or {}).get("text") or ""
                    if text:
                        parts.append(_html_to_text(html_lib.unescape(text)))
                description = "\n\n".join(parts)
        except (requests.RequestException, ValueError):
            pass
        postings.append(Posting(company=company, title=title, url=apply_url, description=description))
    return postings


def _fetch_via_ats(target: dict, cfg: Config) -> list[Posting] | None:
    """Dispatch to an ATS API if the target declares one; else None."""
    ats = target.get("ats") or {}
    atype = (ats.get("type") or "").lower()
    company = target.get("company", "")
    if atype == "greenhouse" and ats.get("token"):
        return fetch_greenhouse(ats["token"], company, cfg)
    if atype == "smartrecruiters" and ats.get("company"):
        return fetch_smartrecruiters(ats["company"], company, cfg)
    return None


def scrape_target(target: dict, cfg: Config) -> list[Posting]:
    """Return postings for one target.

    Prefers the target's ATS API (postings come back with descriptions already
    populated). Falls back to generic HTML scraping otherwise.
    """
    # Prefer the ATS API; if it's declared but returns nothing (e.g. the board's
    # JSON API is disabled or the id is wrong), fall through to HTML scraping.
    ats_postings = _fetch_via_ats(target, cfg)
    if ats_postings:
        return ats_postings

    render = target.get("render", "auto")
    html = get_html(target["url"], cfg, render=render)
    if not html:
        return []
    return extract_postings(html, target["url"], target, cfg)
