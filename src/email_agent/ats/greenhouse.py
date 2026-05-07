"""Greenhouse public jobs API.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{handle}/jobs?content=true
No auth required. Returns all open jobs for the board.
"""

from typing import List

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models import JobPosting

API = "https://boards-api.greenhouse.io/v1/boards/{handle}/jobs"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def fetch_jobs(handle: str, company_name: str | None = None) -> List[JobPosting]:
    url = API.format(handle=handle)
    r = httpx.get(url, params={"content": "true"}, timeout=30.0)
    r.raise_for_status()
    data = r.json()

    name = company_name or handle
    out: List[JobPosting] = []
    for j in data.get("jobs", []):
        out.append(
            JobPosting(
                company=name,
                title=j.get("title", ""),
                url=j.get("absolute_url", ""),
                location=(j.get("location") or {}).get("name"),
                description=_strip_html(j.get("content", "")),
                source="greenhouse",
                external_id=str(j.get("id")),
            )
        )
    return out


def _strip_html(html: str) -> str:
    # Greenhouse returns HTML-escaped HTML in `content`. Cheap-and-cheerful strip;
    # the matcher and tailor are tolerant of artifacts.
    import html as _html
    import re

    text = _html.unescape(html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
