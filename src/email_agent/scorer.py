"""Detailed 1-10 fit scorer for job postings against Ethan's target profile.

Uses Claude with the exact scoring rubric from the spec:
  Title match           0-3
  AI/data platform      0-2
  GTM/sales context     0-2
  Location fit          0-1
  Company tier          0-2
  ─────────────────────────
  Max                    10

The system prompt is cached across all jobs in a single run.
"""

import json
import logging
import re
from typing import Optional

import anthropic

from .models import JobPosting, MatchResult, ScoreBreakdown, ScoredJob

log = logging.getLogger("email_agent.scorer")

# Companies in Ethan's target tier list (used for the +2 bonus).
TIER_1 = frozenset({
    "anthropic", "openai", "databricks", "snowflake", "datadog",
    "dynatrace", "palo alto networks", "crowdstrike", "zscaler",
})
TIER_2 = frozenset({
    "snyk", "cribl", "jellyfish", "maven agi", "monte carlo data",
    "monte carlo", "starburst", "sigma computing", "immuta", "hubspot",
    "wasabi tech", "wasabi",
})
TIER_3 = frozenset({
    "rapid7", "cyberark", "lightmatter", "vizit", "elastic", "sumo logic",
    "dbt labs", "fivetran", "airbyte", "atlan", "alation", "collibra",
    "securonix", "exabeam", "lacework", "orca security", "wiz",
})

ALL_TIERS = TIER_1 | TIER_2 | TIER_3

# Fast pre-filter: skip obviously non-PM titles before calling Claude.
_PM_STEMS = (
    "product manager", "product management", "product owner",
    "data product", "ai product", "ml product", "product lead",
    "head of product", "director of product", "vp product",
    "vp, product", "principal product", "group product",
    "lead product", "senior product", "sr. product", "sr product",
    "product director",
)

_SCORING_SYSTEM = """You are scoring job postings for Ethan Whitney, a Senior PM specializing in AI/data products for enterprise GTM.

CANDIDATE PROFILE
- Current: Sr. PM (Data Platform & AI) at Palo Alto Networks
- Prior: PM (Data Platform & Analytics) at CyberArk; Product Analyst at Rapid7
- Core skills: Snowflake Cortex, LLM workflows, GTM data products, sales analytics, post-acquisition integration
- Targeting: Applied AI PM, Data Platform PM, GTM PM, Senior PM AI/Data
- Location: Boston area or remote EST-compatible
- Target base: $180K–$220K+
- Industries: B2B SaaS, AI tooling, cybersecurity, data infrastructure
- NOT interested in: pure consumer, hands-on engineering management

SCORING RUBRIC (max 10 points)
1. title_match (0–3)
   3 = near-exact: Applied AI PM, Data Platform PM, GTM PM, Sr PM AI/Data
   2 = closely related: Head of Product AI, Principal PM Data, Sr PM Data, AI Product Lead
   1 = general PM with JD clearly pointing to AI/data work
   0 = unrelated

2. ai_data_focus (0–2)
   2 = core focus: LLMs, Snowflake, data platform, AI agents, ML workflows, AI copilots
   1 = AI/data mentioned but not the primary domain
   0 = no AI/data focus

3. gtm_context (0–2)
   2 = directly involves GTM, Sales, Revenue Ops, marketing data, pipeline analytics
   1 = mentions go-to-market or business stakeholders in context
   0 = no GTM context

4. location_fit (0–1)
   1 = Boston/MA office, OR explicitly remote/remote-first, OR EST-compatible remote
   0 = requires relocation outside Boston, or office-only non-Boston

5. company_tier (0–2)
   2 = Tier 1 (Anthropic, OpenAI, Databricks, Snowflake, Datadog, Dynatrace, Palo Alto, CrowdStrike, Zscaler)
   1 = Tier 2/3 (Snyk, Cribl, Jellyfish, Maven AGI, Monte Carlo, Starburst, Sigma, Immuta, Hubspot, Rapid7, CyberArk, etc.) or strong B2B SaaS/AI startup
   0 = unknown company or doesn't fit

AUTOMATIC DISQUALIFIERS (cap score at 2 regardless of rubric)
- Requires hands-on engineering people management as primary duty
- Pure B2C / consumer product (gaming, social, consumer app)
- Requires PhD or deep ML research background
- Completely outside tech industry

Return strict JSON only, no preamble, no explanation:
{
  "score": <int 1-10>,
  "title_match": <0-3>,
  "ai_data_focus": <0-2>,
  "gtm_context": <0-2>,
  "location_fit": <0-1>,
  "company_tier": <0-2>,
  "salary_mentioned": "<salary range string if explicitly mentioned, else null>",
  "match_summary": "<2-3 sentences on why this is a strong fit for Ethan's specific background>",
  "disqualifiers": "<any red flags e.g. requires eng management, or null>"
}"""


def _company_tier_bonus(company: str) -> int:
    name = company.lower()
    if name in TIER_1:
        return 2
    if name in TIER_2 or name in TIER_3:
        return 1
    return 0


def title_prefilter(title: str) -> bool:
    t = title.lower()
    return any(stem in t for stem in _PM_STEMS)


def score_job(
    job: JobPosting,
    client: anthropic.Anthropic,
    model: str = "claude-sonnet-4-6",
) -> Optional[ScoredJob]:
    """Score a single job posting. Returns None if Claude call fails."""
    user_content = (
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location or 'unspecified'}\n\n"
        f"Job description (truncated to 3000 chars):\n"
        f"{(job.description or '').strip()[:3000]}"
    )

    # Inject known company-tier bonus hint so Claude doesn't have to guess.
    tier_hint = _company_tier_bonus(job.company)
    if tier_hint:
        user_content += f"\n\n[System note: {job.company} is in Ethan's target company tier list. company_tier should be {tier_hint}.]"

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": _SCORING_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as e:
        log.warning("Scoring API call failed for %s — %s: %s", job.company, job.title, e)
        return None

    text = next((b.text for b in resp.content if b.type == "text"), "")
    return _parse_score(job, text)


def _parse_score(job: JobPosting, text: str) -> Optional[ScoredJob]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        d = json.loads(cleaned)
        bd = ScoreBreakdown(
            title_match=int(d.get("title_match", 0)),
            ai_data_focus=int(d.get("ai_data_focus", 0)),
            gtm_context=int(d.get("gtm_context", 0)),
            location_fit=int(d.get("location_fit", 0)),
            company_tier=int(d.get("company_tier", 0)),
        )
        return ScoredJob(
            job=job,
            score=int(d.get("score", 1)),
            breakdown=bd,
            salary_mentioned=d.get("salary_mentioned") or None,
            match_summary=str(d.get("match_summary", "")),
            disqualifiers=d.get("disqualifiers") or None,
        )
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        log.warning("Score parse failed for %s — %s: %s | raw: %s", job.company, job.title, e, text[:200])
        return None
