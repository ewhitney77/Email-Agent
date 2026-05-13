"""Part 2: Company and contact discovery for proactive outreach.

Uses Claude with the built-in web_search tool to:
1. Find B2B SaaS companies that are likely hiring Applied AI / Data PMs
2. Identify the most likely person to contact at each company
3. Draft a personalised outreach message in Ethan's voice

The web_search tool (type: "web_search_20250305") is available on
claude-sonnet-4-6 and claude-opus-4-7 and doesn't require a separate
search API key.
"""

import json
import logging
import re
from typing import List, Optional

import anthropic

from .models import OutreachContact, OutreachTarget
from .state import State

log = logging.getLogger("email_agent.outreach")

# Hard-coded roster of companies to always evaluate (beyond what scraping finds).
# Drawn from Ethan's spec + logical adjacents.
CANDIDATE_COMPANIES = [
    # Tier 1 targets
    "Anthropic", "OpenAI", "Databricks", "Snowflake", "Datadog",
    "Dynatrace", "CrowdStrike", "Zscaler",
    # Tier 2 targets
    "Snyk", "Cribl", "Jellyfish", "Maven AGI", "Monte Carlo Data",
    "Starburst", "Sigma Computing", "Immuta", "HubSpot",
    # Tier 3 / Growth-stage Boston-area AI/data/security
    "Tenable", "LogicMonitor", "Rapid7", "Lacework", "Orca Security",
    "Wiz", "Cyera", "Normalyze", "Varonis", "Code42",
    "Atlan", "Alation", "Collibra", "dbt Labs", "Fivetran", "Airbyte",
    "Observe Inc", "Chronosphere", "Lightstep", "Honeycomb",
    "Securonix", "Exabeam", "Sumo Logic",
    "Elastic", "Couchbase", "SingleStore",
    "Census", "Hightouch", "Rudderstack",
    "Mixpanel", "Amplitude", "FullStory",
    "Salesloft", "Outreach", "Gong", "Clari", "People.ai",
    "Demandbase", "6sense", "Bombora", "TechTarget",
    "Vendr", "Zip", "Ironclad",
    "Cohere", "Mistral AI", "Writer", "Glean", "Moveworks",
    "Unstructured", "LlamaIndex", "LangChain",
]

_DISCOVERY_SYSTEM = """You are a job search research agent helping Ethan Whitney, a Senior PM specializing in AI and data products for GTM/enterprise use cases, identify companies to proactively reach out to.

Ethan's background:
- Sr. PM (Data Platform & AI) at Palo Alto Networks — owns roadmap for 105+ data/AI products across GTM, Finance, and Product
- Built Snowflake Cortex-based account intelligence system saving 1300+ hrs/yr
- Built conversational data access system lowering time-to-insight 75% for operational teams
- CyberArk: built data platform contributing to 51% increase in per-AE pipeline; LLM workflows for forecast accuracy; $100M+ incremental bookings impact
- Rapid7: channel performance and competitive intelligence products
- Target roles: Applied AI PM, Data Platform PM, GTM PM, Senior PM AI/Data
- Target: $180K–$220K base, Boston area or remote EST

Your strongest positioning angles for outreach:
1. Applied AI products on Snowflake Cortex for GTM use cases (real production deployments)
2. Post-acquisition data integration at scale ($6B pipeline identified, zero Day 1 loss)
3. Zero-to-one sales analytics ownership driving $100M+ bookings impact
4. AI automation replacing manual GTM workflows (1300+ hrs/yr saved)

You have access to web_search. Use it to research each company to:
- Confirm they're actively building AI/data products
- Find recent hiring signals (PM, AI PM, Data PM job postings)
- Identify the right person to contact (VP Product, Head of Product, Director of Product AI/Data, or Engineering hiring manager)
- Find their LinkedIn profile URL if possible

For each company, draft a warm, direct, peer-to-peer outreach message opening with:
"I wanted to reach out because I am doing a bit of research on [Company]."

The message should:
- Be 4-6 sentences total
- Reference something specific about what the company is building
- Connect to a specific, concrete achievement from Ethan's background
- End with a low-pressure ask (e.g., "Would love to connect and learn more about how you're thinking about [X]")
- Sound like a peer reaching out, not a job applicant begging

Do NOT mention job openings explicitly. This is a warm networking touch, not a job application.

Return a JSON array of OutreachTarget objects. Each object:
{
  "company": "<company name>",
  "relevance": "<1-2 sentences why this company is a strong fit for Ethan's background>",
  "contact_name": "<full name or null if not found>",
  "contact_title": "<title or null>",
  "contact_linkedin_url": "<linkedin.com/in/... or null>",
  "outreach_hook": "<one-line hook, 10-15 words>",
  "draft_message": "<full outreach message, 4-6 sentences>"
}"""

_DISCOVERY_USER_TEMPLATE = """Research these companies and identify the top {limit} that Ethan should reach out to this week. Skip any that have been contacted recently (listed below).

CANDIDATE COMPANIES TO EVALUATE:
{company_list}

RECENTLY SUGGESTED (skip these):
{skip_list}

For each company you include, search for:
1. Recent news or job postings signaling AI/data PM investment
2. The VP Product / Head of Product / Director Product AI or Data
3. Their LinkedIn URL if findable

Return exactly {limit} companies as a JSON array. Prioritize companies where you found strong hiring signals or recent AI product announcements."""


def discover_outreach_targets(
    client: anthropic.Anthropic,
    state: State,
    model: str = "claude-sonnet-4-6",
    limit: int = 10,
) -> List[OutreachTarget]:
    """Use Claude + web search to find companies and contacts for proactive outreach."""

    # Build skip list from state (companies suggested in last 21 days).
    recently_suggested = [
        c for c in CANDIDATE_COMPANIES
        if state.recently_suggested_outreach(c)
    ]
    available = [c for c in CANDIDATE_COMPANIES if c not in recently_suggested]

    if len(available) < limit:
        # Reset rotation: use everyone again.
        log.info("Outreach rotation complete; resetting skip list.")
        recently_suggested = []
        available = CANDIDATE_COMPANIES

    user_content = _DISCOVERY_USER_TEMPLATE.format(
        limit=limit,
        company_list="\n".join(f"- {c}" for c in available[:50]),
        skip_list="\n".join(f"- {c}" for c in recently_suggested) if recently_suggested else "(none)",
    )

    try:
        targets = _run_discovery(client, model, user_content, limit)
    except Exception as e:
        log.error("Outreach discovery failed: %s", e)
        return []

    # Persist to state so we don't re-suggest the same companies next run.
    for t in targets:
        name = t.contact.name if t.contact else ""
        title = t.contact.title if t.contact else ""
        state.record_outreach_suggestion(t.company, name, title)

    return targets


def _run_discovery(
    client: anthropic.Anthropic,
    model: str,
    user_content: str,
    limit: int,
) -> List[OutreachTarget]:
    """Call Claude with web_search tool use, looping until final answer."""
    messages = [{"role": "user", "content": user_content}]
    tools = [{"type": "web_search_20250305", "name": "web_search"}]

    max_rounds = 12  # web search can require multiple tool call rounds
    for _ in range(max_rounds):
        resp = client.messages.create(
            model=model,
            max_tokens=8000,
            system=_DISCOVERY_SYSTEM,
            tools=tools,
            messages=messages,
        )

        # Collect any text blocks produced in this turn.
        text_blocks = [b.text for b in resp.content if b.type == "text"]
        tool_uses = [b for b in resp.content if b.type == "tool_use"]

        if resp.stop_reason == "end_turn" or not tool_uses:
            # Final answer — parse the JSON from the text.
            full_text = "\n".join(text_blocks)
            return _parse_targets(full_text, limit)

        # Build tool results and continue the conversation.
        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for tu in tool_uses:
            # web_search tool results come back inside the tool_use block already
            # in claude's API; we just need to echo them as tool_result messages.
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": getattr(tu, "output", "") or "",
            })
        messages.append({"role": "user", "content": tool_results})

    log.warning("Outreach discovery hit max_rounds without final answer.")
    return []


def _parse_targets(text: str, limit: int) -> List[OutreachTarget]:
    """Extract JSON array from Claude's response and convert to OutreachTarget objects."""
    # Strip markdown code fences if present.
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()

    # Find the JSON array (may be embedded in surrounding prose).
    arr_match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not arr_match:
        log.warning("No JSON array found in outreach discovery response. Raw: %s", text[:400])
        return []

    try:
        data = json.loads(arr_match.group(0))
    except json.JSONDecodeError as e:
        log.warning("Outreach JSON parse failed: %s | raw: %s", e, text[:400])
        return []

    out: List[OutreachTarget] = []
    for item in data[:limit]:
        contact: Optional[OutreachContact] = None
        if item.get("contact_name"):
            contact = OutreachContact(
                name=item["contact_name"],
                title=item.get("contact_title") or "",
                linkedin_url=item.get("contact_linkedin_url") or None,
            )
        out.append(
            OutreachTarget(
                company=item.get("company", "Unknown"),
                relevance=item.get("relevance", ""),
                contact=contact,
                outreach_hook=item.get("outreach_hook", ""),
                draft_message=item.get("draft_message", ""),
            )
        )
    return out
