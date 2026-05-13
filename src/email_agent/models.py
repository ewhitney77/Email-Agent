"""Shared data shapes."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class JobPosting:
    company: str
    title: str
    url: str
    location: Optional[str] = None
    description: str = ""
    source: str = ""  # "greenhouse" | "lever" | "ashby" | "workday" | "gmail" | "indeed"
    external_id: Optional[str] = None

    @property
    def key(self) -> str:
        if self.external_id:
            return f"{self.source}:{self.external_id}"
        return f"{self.source}:{self.url}"


@dataclass
class MatchResult:
    fits: bool
    confidence: float  # 0.0 - 1.0
    reasoning: str
    role_category: str = ""


@dataclass
class ScoreBreakdown:
    title_match: int = 0    # 0-3
    ai_data_focus: int = 0  # 0-2
    gtm_context: int = 0    # 0-2
    location_fit: int = 0   # 0-1
    company_tier: int = 0   # 0-2


@dataclass
class ScoredJob:
    job: JobPosting
    score: int              # 1-10
    breakdown: ScoreBreakdown
    salary_mentioned: Optional[str]
    match_summary: str
    disqualifiers: Optional[str] = None


@dataclass
class OutreachContact:
    name: str
    title: str
    linkedin_url: Optional[str] = None


@dataclass
class OutreachTarget:
    company: str
    relevance: str          # why relevant to Ethan's background
    contact: Optional[OutreachContact]
    outreach_hook: str      # one-line hook
    draft_message: str      # full pre-written outreach message


@dataclass
class TailoredResume:
    job: JobPosting
    markdown: str
    cover_blurb: str = ""
