"""Orchestrator. Run with `python -m email_agent.main`."""

import logging
import os
import sys
from pathlib import Path
from typing import List

import anthropic
import yaml
from dotenv import load_dotenv

from . import notifier
from .ats import ashby, greenhouse, lever, workday
from .gmail_client import GmailClient
from .matcher import match
from .models import JobPosting, TailoredResume
from .state import State
from .tailor import tailor_resume


log = logging.getLogger("email_agent")


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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
        except Exception as e:  # noqa: BLE001 - external HTTP, log and continue
            log.warning("ATS fetch failed for %s: %s", name, e)
    return out


def collect_gmail_jobs(gmail: GmailClient, settings: dict, target_companies: set) -> List[JobPosting]:
    """Scrape Gmail and emit one JobPosting per email lead from a target company.

    The Gmail path catches roles that don't appear on a public ATS (recruiter
    outreach, internal referrals). We only emit one posting per email; the
    matcher and tailor handle judgment from there.
    """
    leads = gmail.search_job_emails(
        lookback_days=settings.get("gmail_lookback_days", 7),
        search_hints=settings.get("gmail_search_hints", []),
    )
    out: List[JobPosting] = []
    for lead in leads:
        company = _guess_company(lead.sender, lead.subject, lead.body, target_companies)
        if not company:
            continue
        title = _guess_title(lead.subject, lead.body)
        url = lead.urls[0] if lead.urls else ""
        out.append(
            JobPosting(
                company=company,
                title=title or "(unspecified — see email)",
                url=url,
                description=lead.body[:4000],
                source="gmail",
                external_id=lead.message_id,
            )
        )
    return out


def _guess_company(sender: str, subject: str, body: str, target_companies: set) -> str:
    haystack = f"{sender} {subject} {body[:500]}".lower()
    for name in target_companies:
        if name.lower() in haystack:
            return name
    return ""


def _guess_title(subject: str, body: str) -> str:
    # Cheap heuristic: the email subject usually contains the title.
    # Tailor will read the full body anyway.
    import re

    m = re.search(r"(?:opening|role|position|hiring|opportunity)[:\-\s]+([^|—\-\n]+)", subject, re.I)
    if m:
        return m.group(1).strip()
    return subject.strip()


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    root = Path(__file__).resolve().parents[2]
    settings = load_yaml(root / "config" / "settings.yaml")
    companies_cfg = load_yaml(root / "config" / "companies.yaml")
    companies = companies_cfg.get("companies", []) or []

    if not companies:
        log.error("No companies configured. Edit config/companies.yaml first.")
        return 2

    resume_path = root / "config" / "resume_master.md"
    master_resume = resume_path.read_text(encoding="utf-8")
    if "PASTE YOUR RESUME HERE" in master_resume:
        log.error("config/resume_master.md is still the placeholder. Replace it with your resume.")
        return 2

    state = State(os.environ.get("STATE_DB_PATH", root / "state.sqlite"))
    anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = settings.get("anthropic_model", "claude-opus-4-7")

    # 1. Pull from public ATS APIs.
    log.info("Polling %d companies via ATS APIs…", len(companies))
    ats_jobs = collect_ats_jobs(companies)
    log.info("Pulled %d total postings from ATS sources", len(ats_jobs))

    # 2. Pull from Gmail.
    gmail = GmailClient(
        client_secrets_path=os.environ.get("GOOGLE_CLIENT_SECRETS", "./secrets/client_secret.json"),
        token_path=os.environ.get("GOOGLE_TOKEN_PATH", "./secrets/token.json"),
    )
    target_company_names = {c["name"] for c in companies if c.get("name")}
    log.info("Scanning Gmail for job-related emails (lookback=%dd)…", settings.get("gmail_lookback_days", 7))
    gmail_jobs = collect_gmail_jobs(gmail, settings, target_company_names)
    log.info("Found %d Gmail leads from target companies", len(gmail_jobs))

    all_jobs = ats_jobs + gmail_jobs

    # 3. Dedup and match.
    new_matches: List[JobPosting] = []
    target_roles = settings.get("target_roles", [])
    for job in all_jobs:
        if state.has_job(job.key):
            continue
        result = match(job, target_roles, anthropic_client=anthropic_client, model=model)
        if result.fits and result.confidence >= 0.6:
            log.info("MATCH (%.2f, %s): %s — %s", result.confidence, result.role_category, job.company, job.title)
            new_matches.append(job)
        state.record_job(job.key, job.company, job.title, job.url, job.source)

    if not new_matches:
        log.info("No new matches this run.")
        return 0

    # 4. Tailor (cap per-run cost).
    cap = int(settings.get("max_tailored_per_run", 10))
    to_tailor = new_matches[:cap]
    if len(new_matches) > cap:
        log.warning("Capping tailored output at %d of %d matches (max_tailored_per_run).", cap, len(new_matches))

    tailored: List[TailoredResume] = []
    for job in to_tailor:
        log.info("Tailoring resume for %s — %s", job.company, job.title)
        try:
            tailored.append(tailor_resume(job, master_resume, anthropic_client, model=model))
        except Exception as e:  # noqa: BLE001 - LLM failures shouldn't kill the run
            log.exception("Failed to tailor resume for %s — %s: %s", job.company, job.title, e)

    # 5. Write to outbox + send digest.
    outbox = os.environ.get("OUTBOX_DIR", str(root / "outbox"))
    paths = notifier.write_to_outbox(outbox, tailored)
    log.info("Wrote %d tailored resumes to %s", len(paths), outbox)

    notify_to = os.environ.get("NOTIFY_EMAIL")
    if notify_to and tailored:
        msg_id = notifier.send_digest(gmail, notify_to, tailored)
        log.info("Sent digest email (id=%s) to %s", msg_id, notify_to)
        for t in tailored:
            state.mark_notified(t.job.key)

    return 0


if __name__ == "__main__":
    sys.exit(main())
