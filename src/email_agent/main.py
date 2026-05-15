"""Job Search Agent — daily digest orchestrator.

Run with:
  python -m email_agent.main

Flow:
  1. Pull open jobs from ATS APIs (Greenhouse, Lever, Ashby, Workday)
  2. Pull jobs from Indeed RSS (multiple keyword queries)
  3. Pre-filter to PM-adjacent titles; deduplicate against seen DB
  4. Score each new job 1-10 against Ethan's profile (Claude)
  5. Take the top 10 by score
  6. Run Part 2: discover 10 companies + contacts for proactive outreach (Claude + web search)
  7. Send a single HTML digest email to NOTIFY_EMAIL
"""

import logging
import os
import sys
from pathlib import Path
from typing import List

import anthropic
import yaml
from dotenv import load_dotenv

from . import digest as digest_module
from .ats import ashby, greenhouse, lever, workday
from .gmail_client import GmailClient
from .job_boards import indeed as indeed_module
from .models import JobPosting, ScoredJob
from .outreach import discover_outreach_targets
from .scorer import score_job, title_prefilter
from .state import State

log = logging.getLogger("email_agent")


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── ATS collection ────────────────────────────────────────────────────────────

def collect_ats_jobs(companies: List[dict]) -> List[JobPosting]:
    """Poll every configured ATS for every company. Errors per-company are non-fatal."""
    out: List[JobPosting] = []
    for c in companies:
        name = c.get("name") or "Unknown"
        try:
            if c.get("greenhouse"):
                out.extend(greenhouse.fetch_jobs(c["greenhouse"], company_name=name))
            if c.get("lever"):
                out.extend(lever.fetch_jobs(c["lever"], company_name=name))
            if c.get("ashby"):
                out.extend(ashby.fetch_jobs(c["ashby"], company_name=name))
            if c.get("workday"):
                w = c["workday"]
                out.extend(
                    workday.fetch_jobs(
                        tenant=w["tenant"],
                        site=w["site"],
                        host=w.get("host", "wd1"),
                        company_name=name,
                    )
                )
        except Exception as e:  # noqa: BLE001
            log.warning("ATS fetch failed for %s: %s", name, e)
    return out


# ── Indeed collection ─────────────────────────────────────────────────────────

def collect_indeed_jobs() -> List[JobPosting]:
    try:
        return indeed_module.fetch_all()
    except Exception as e:
        log.warning("Indeed fetch failed entirely: %s", e)
        return []


# ── Scoring pipeline ──────────────────────────────────────────────────────────

def score_new_jobs(
    all_jobs: List[JobPosting],
    state: State,
    client: anthropic.Anthropic,
    model: str,
    max_score_per_run: int = 80,
) -> List[ScoredJob]:
    """
    For each job not already in the DB:
      1. Record it (so future runs skip it)
      2. Pre-filter title
      3. Score with Claude
    Returns all scored jobs (not yet top-N filtered).
    """
    to_score: List[JobPosting] = []
    for job in all_jobs:
        if state.has_job(job.key):
            continue
        state.record_job(job.key, job.company, job.title, job.url, job.source)
        if title_prefilter(job.title):
            to_score.append(job)
        else:
            log.debug("Pre-filter skip: %s — %s", job.company, job.title)

    log.info(
        "%d total jobs pulled; %d new and PM-adjacent (title pre-filter passed)",
        len(all_jobs),
        len(to_score),
    )

    if len(to_score) > max_score_per_run:
        log.warning(
            "Capping scoring at %d of %d eligible jobs (max_score_per_run).",
            max_score_per_run,
            len(to_score),
        )
        to_score = to_score[:max_score_per_run]

    scored: List[ScoredJob] = []
    for job in to_score:
        result = score_job(job, client, model=model)
        if result is not None:
            scored.append(result)
            log.info(
                "Scored %d/10 — %s: %s (%s)",
                result.score,
                job.company,
                job.title,
                job.location or "?",
            )

    return scored


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    # Explicitly resolve the repo root so load_dotenv works on Windows
    # regardless of which directory the user runs the command from.
    root = Path(__file__).resolve().parents[2]
    load_dotenv(dotenv_path=root / ".env")
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_yaml(root / "config" / "settings.yaml")
    companies_cfg = load_yaml(root / "config" / "companies.yaml")
    companies = companies_cfg.get("companies", []) or []

    if not companies:
        log.error("No companies configured. Edit config/companies.yaml.")
        return 2

    state = State(os.environ.get("STATE_DB_PATH", str(root / "state.sqlite")))
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    scoring_model = settings.get("scoring_model", "claude-sonnet-4-6")
    outreach_model = settings.get("outreach_model", "claude-sonnet-4-6")
    top_n = int(settings.get("top_roles_per_digest", 10))
    top_outreach = int(settings.get("top_outreach_per_digest", 10))
    max_score = int(settings.get("max_score_per_run", 80))
    min_score = int(settings.get("min_score_threshold", 4))

    # 1. Collect from ATS APIs.
    log.info("Polling %d companies via ATS APIs…", len(companies))
    ats_jobs = collect_ats_jobs(companies)
    log.info("ATS: %d postings pulled", len(ats_jobs))

    # 2. Collect from Indeed RSS.
    log.info("Fetching Indeed RSS…")
    indeed_jobs = collect_indeed_jobs()
    log.info("Indeed: %d postings pulled", len(indeed_jobs))

    all_jobs = ats_jobs + indeed_jobs

    # 3. Score new PM-adjacent jobs.
    scored = score_new_jobs(all_jobs, state, client, scoring_model, max_score_per_run=max_score)

    # Filter out anything below min_score threshold and jobs with disqualifiers.
    qualified = [s for s in scored if s.score >= min_score and not _hard_disqualified(s)]
    log.info("%d jobs scored; %d meet minimum threshold (%d)", len(scored), len(qualified), min_score)

    # Sort by score descending, take top N.
    top_jobs = sorted(qualified, key=lambda s: s.score, reverse=True)[:top_n]

    # 4. Discover outreach targets (Part 2).
    log.info("Discovering outreach targets via Claude web search…")
    outreach_targets = discover_outreach_targets(
        client=client,
        state=state,
        model=outreach_model,
        limit=top_outreach,
    )
    log.info("Found %d outreach targets", len(outreach_targets))

    # 5. Send digest.
    notify_to = os.environ.get("NOTIFY_EMAIL")
    if not notify_to:
        log.warning("NOTIFY_EMAIL not set — printing digest to stdout instead.")
        print(digest_module.build_plain(top_jobs, outreach_targets))
        return 0

    if not top_jobs and not outreach_targets:
        log.info("Nothing new to report. Skipping email.")
        return 0

    gmail = GmailClient(
        client_secrets_path=os.environ.get("GOOGLE_CLIENT_SECRETS", "./secrets/client_secret.json"),
        token_path=os.environ.get("GOOGLE_TOKEN_PATH", "./secrets/token.json"),
    )

    msg_id = digest_module.send_digest(gmail, notify_to, top_jobs, outreach_targets)
    log.info("Digest sent (id=%s) to %s — %d roles, %d outreach targets", msg_id, notify_to, len(top_jobs), len(outreach_targets))

    # Mark notified in state.
    for s in top_jobs:
        state.mark_notified(s.job.key)

    return 0


def _hard_disqualified(scored: ScoredJob) -> bool:
    """True if the job has a disqualifier string that looks like a hard no."""
    if not scored.disqualifiers:
        return False
    d = scored.disqualifiers.lower()
    hard_phrases = (
        "engineering manager", "engineering management",
        "hands-on management", "people management required",
        "pure consumer", "phd required",
    )
    return any(p in d for p in hard_phrases)


if __name__ == "__main__":
    sys.exit(main())
