"""Workday — best-effort.

Workday has no stable public API. Most tenants expose an internal CXS endpoint
at: https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
that accepts POST with a JSON body. Schemas drift; handle gracefully.
"""

from typing import List

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models import JobPosting


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
def fetch_jobs(
    tenant: str,
    site: str,
    host: str = "wd1",
    company_name: str | None = None,
    keyword: str = "",
) -> List[JobPosting]:
    base = f"https://{tenant}.{host}.myworkdayjobs.com"
    url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    body = {
        "appliedFacets": {},
        "limit": 50,
        "offset": 0,
        "searchText": keyword,
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=30.0)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return []

    name = company_name or tenant
    out: List[JobPosting] = []
    for j in data.get("jobPostings", []):
        external_path = j.get("externalPath", "")
        full_url = f"{base}/{site}{external_path}" if external_path else ""
        out.append(
            JobPosting(
                company=name,
                title=j.get("title", ""),
                url=full_url,
                location=j.get("locationsText"),
                description="",  # Workday list endpoint omits descriptions; would need a second fetch per job.
                source="workday",
                external_id=external_path or j.get("bulletFields", [None])[0],
            )
        )
    return out
