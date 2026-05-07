"""Lever public postings API.

Endpoint: https://api.lever.co/v0/postings/{handle}?mode=json
No auth required.
"""

from typing import List

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models import JobPosting

API = "https://api.lever.co/v0/postings/{handle}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def fetch_jobs(handle: str, company_name: str | None = None) -> List[JobPosting]:
    url = API.format(handle=handle)
    r = httpx.get(url, params={"mode": "json"}, timeout=30.0)
    r.raise_for_status()
    data = r.json()

    name = company_name or handle
    out: List[JobPosting] = []
    for j in data:
        location = (j.get("categories") or {}).get("location")
        # `descriptionPlain` is plain text; fall back to `description` (HTML).
        desc = j.get("descriptionPlain") or _strip_html(j.get("description", ""))
        out.append(
            JobPosting(
                company=name,
                title=j.get("text", ""),
                url=j.get("hostedUrl") or j.get("applyUrl", ""),
                location=location,
                description=desc,
                source="lever",
                external_id=j.get("id"),
            )
        )
    return out


def _strip_html(html: str) -> str:
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
