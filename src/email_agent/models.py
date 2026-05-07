"""Shared data shapes."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JobPosting:
    company: str
    title: str
    url: str
    location: Optional[str] = None
    description: str = ""
    source: str = ""  # "greenhouse" | "lever" | "ashby" | "workday" | "gmail"
    external_id: Optional[str] = None

    @property
    def key(self) -> str:
        # Stable dedup key. Prefer source + external_id; fall back to URL.
        if self.external_id:
            return f"{self.source}:{self.external_id}"
        return f"{self.source}:{self.url}"


@dataclass
class MatchResult:
    fits: bool
    confidence: float  # 0.0 - 1.0
    reasoning: str
    role_category: str = ""  # e.g. "Data PM", "AI PM", "PM"


@dataclass
class TailoredResume:
    job: JobPosting
    markdown: str
    cover_blurb: str = ""
