"""Ashby public job-board API.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{handle}?includeCompensation=true
No auth required.
"""

from typing import List

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models import JobPosting

API = "https://api.ashbyhq.com/posting-api/job-board/{handle}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def fetch_jobs(handle: str, company_name: str | None = None) -> List[JobPosting]:
    url = API.format(handle=handle)
    r = httpx.get(url, params={"includeCompensation": "true"}, timeout=30.0)
    r.raise_for_status()
    data = r.json()

    name = company_name or handle
    out: List[JobPosting] = []
    for j in data.get("jobs", []):
        out.append(
            JobPosting(
                company=name,
                title=j.get("title", ""),
                url=j.get("jobUrl") or j.get("applyUrl", ""),
                location=j.get("locationName"),
                description=j.get("descriptionPlain", "") or _strip_html(j.get("descriptionHtml", "")),
                source="ashby",
                external_id=j.get("id"),
            )
        )
    return out


def _strip_html(html: str) -> str:
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
