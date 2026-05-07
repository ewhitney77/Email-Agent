"""Decide whether a job posting is a fit for the target roles.

Cheap pre-filter on title keywords, then optional Claude judgment for borderline
cases. Most postings get filtered without ever calling the model.
"""

import json
import re
from typing import List, Optional

import anthropic

from .models import JobPosting, MatchResult


# Stems we consider "PM-adjacent" for the cheap pre-filter.
_PM_STEMS = (
    "product manager",
    "product management",
    "product owner",
    "data product",
    "ai product",
    "ml product",
    "product lead",
    "head of product",
    "director of product",
    "vp product",
    "vp, product",
    "principal product",
    "group product",
    "lead product",
    "senior product",
)


def title_prefilter(title: str) -> bool:
    t = (title or "").lower()
    return any(stem in t for stem in _PM_STEMS)


def keyword_match(title: str, target_roles: List[str]) -> bool:
    t = (title or "").lower()
    return any(r.lower() in t for r in target_roles)


_SYSTEM = """You are screening job postings for a candidate looking for Product Manager roles, with a strong preference for Data PM and AI PM positions. The candidate is open to titles that don't say "Product Manager" verbatim if the work is fundamentally product management.

For each posting, decide whether it fits. Be permissive on related titles (Product Owner, Head of Product, Product Lead, etc.) and strict on unrelated ones (Engineering Manager, Project Manager, Marketing).

Return strict JSON only, no preamble:
{
  "fits": boolean,
  "confidence": number between 0 and 1,
  "role_category": "Data PM" | "AI PM" | "PM" | "Other",
  "reasoning": "one sentence"
}"""


def llm_judge(
    job: JobPosting,
    client: anthropic.Anthropic,
    model: str = "claude-opus-4-7",
) -> MatchResult:
    """Use Claude to judge fit for borderline titles. ~1 cheap call per posting."""
    user = (
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location or 'unspecified'}\n\n"
        f"Description (truncated):\n{(job.description or '')[:2500]}"
    )
    resp = client.messages.create(
        model=model,
        max_tokens=512,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return _parse_match(text)


def _parse_match(text: str) -> MatchResult:
    # Be lenient — strip code fences if present.
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(cleaned)
        return MatchResult(
            fits=bool(data.get("fits")),
            confidence=float(data.get("confidence", 0.0)),
            reasoning=str(data.get("reasoning", "")),
            role_category=str(data.get("role_category", "")),
        )
    except (ValueError, KeyError):
        return MatchResult(fits=False, confidence=0.0, reasoning=f"unparseable: {text[:120]}")


def match(
    job: JobPosting,
    target_roles: List[str],
    anthropic_client: Optional[anthropic.Anthropic] = None,
    model: str = "claude-opus-4-7",
) -> MatchResult:
    """Multi-tier match: keyword exact, then PM-stem, then optional LLM."""
    if keyword_match(job.title, target_roles):
        return MatchResult(fits=True, confidence=0.95, reasoning="exact title keyword match", role_category="PM")
    if not title_prefilter(job.title):
        return MatchResult(fits=False, confidence=0.0, reasoning="title not PM-adjacent")
    if anthropic_client is None:
        # No LLM available — accept PM-adjacent titles at lower confidence.
        return MatchResult(fits=True, confidence=0.7, reasoning="PM-adjacent title (no LLM check)", role_category="PM")
    return llm_judge(job, anthropic_client, model=model)
