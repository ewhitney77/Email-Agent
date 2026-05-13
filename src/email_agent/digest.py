"""Build and send the daily job search digest email.

Generates a clean, scannable HTML email with:
  Part 1 — Top 10 Roles (scored job matches)
  Part 2 — Top 10 Outreach Targets (proactive company contacts)
"""

import base64
import logging
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from .gmail_client import GmailClient
from .models import OutreachTarget, ScoredJob

log = logging.getLogger("email_agent.digest")


# ── Colour palette ────────────────────────────────────────────────────────────
_BRAND = "#1a4a6b"     # dark teal — header / links
_ACCENT = "#2e86c1"    # mid blue — score badge high
_WARN = "#e67e22"      # orange — medium score
_MUTED = "#7f8c8d"     # grey — low score / meta text
_BG = "#f4f6f8"        # page background
_CARD = "#ffffff"      # card background
_BORDER = "#dde1e7"    # card border


def _score_colour(score: int) -> str:
    if score >= 8:
        return "#27ae60"   # green
    if score >= 6:
        return _ACCENT
    if score >= 4:
        return _WARN
    return _MUTED


def _score_badge(score: int) -> str:
    colour = _score_colour(score)
    return (
        f'<span style="display:inline-block;background:{colour};color:#fff;'
        f'font-weight:700;font-size:13px;padding:2px 8px;border-radius:12px;'
        f'min-width:28px;text-align:center;">{score}/10</span>'
    )


def _breakdown_bar(scored: ScoredJob) -> str:
    bd = scored.breakdown
    items = [
        ("Title", bd.title_match, 3),
        ("AI/Data", bd.ai_data_focus, 2),
        ("GTM", bd.gtm_context, 2),
        ("Location", bd.location_fit, 1),
        ("Company", bd.company_tier, 2),
    ]
    parts = []
    for label, val, max_val in items:
        pct = int((val / max_val) * 100) if max_val else 0
        colour = "#27ae60" if pct >= 67 else (_ACCENT if pct >= 33 else _MUTED)
        parts.append(
            f'<span style="margin-right:10px;font-size:11px;color:{_MUTED};">'
            f'{label}: <b style="color:{colour};">{val}/{max_val}</b></span>'
        )
    return "".join(parts)


def _job_card(idx: int, scored: ScoredJob) -> str:
    job = scored.job
    salary_line = ""
    if scored.salary_mentioned:
        salary_line = (
            f'<div style="font-size:12px;color:{_MUTED};margin-top:2px;">'
            f'💰 {scored.salary_mentioned}</div>'
        )
    location_line = f" &nbsp;·&nbsp; {job.location}" if job.location else ""
    disq_line = ""
    if scored.disqualifiers:
        disq_line = (
            f'<div style="font-size:11px;color:{_WARN};margin-top:4px;">'
            f'⚠ {scored.disqualifiers}</div>'
        )
    return f"""
<div style="background:{_CARD};border:1px solid {_BORDER};border-radius:8px;
            padding:16px 20px;margin-bottom:12px;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div style="flex:1;">
      <div style="font-size:15px;font-weight:700;color:{_BRAND};">
        {idx}. {job.title}
      </div>
      <div style="font-size:13px;color:#333;margin-top:2px;">
        <b>{job.company}</b><span style="color:{_MUTED};">{location_line}</span>
      </div>
      {salary_line}
    </div>
    <div style="margin-left:12px;flex-shrink:0;">
      {_score_badge(scored.score)}
    </div>
  </div>
  <div style="font-size:12px;color:{_MUTED};margin-top:6px;">
    {_breakdown_bar(scored)}
  </div>
  <div style="font-size:13px;color:#444;margin-top:8px;line-height:1.5;">
    {scored.match_summary}
  </div>
  {disq_line}
  <div style="margin-top:10px;">
    <a href="{job.url}"
       style="display:inline-block;background:{_BRAND};color:#fff;
              text-decoration:none;font-size:12px;font-weight:600;
              padding:5px 14px;border-radius:4px;">
      View Role →
    </a>
    &nbsp;
    <span style="font-size:11px;color:{_MUTED};">Source: {job.source}</span>
  </div>
</div>"""


def _outreach_card(idx: int, target: OutreachTarget) -> str:
    contact_line = ""
    linkedin_btn = ""
    if target.contact:
        contact_line = (
            f'<div style="font-size:13px;color:#333;margin-top:3px;">'
            f'<b>Contact:</b> {target.contact.name}'
            f'{" — " + target.contact.title if target.contact.title else ""}</div>'
        )
        if target.contact.linkedin_url:
            linkedin_btn = (
                f'<a href="{target.contact.linkedin_url}" '
                f'style="display:inline-block;background:#0077b5;color:#fff;'
                f'text-decoration:none;font-size:12px;font-weight:600;'
                f'padding:5px 14px;border-radius:4px;">LinkedIn →</a>&nbsp;'
            )

    # Escape the draft message for HTML (preserve line breaks).
    draft_html = (
        target.draft_message
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )

    return f"""
<div style="background:{_CARD};border:1px solid {_BORDER};border-radius:8px;
            padding:16px 20px;margin-bottom:12px;">
  <div style="font-size:15px;font-weight:700;color:{_BRAND};">
    {idx}. {target.company}
  </div>
  {contact_line}
  <div style="font-size:13px;color:#444;margin-top:6px;font-style:italic;">
    {target.outreach_hook}
  </div>
  <div style="font-size:12px;color:#555;margin-top:4px;line-height:1.4;">
    {target.relevance}
  </div>
  <div style="margin-top:12px;">
    {linkedin_btn}
  </div>
  <details style="margin-top:10px;">
    <summary style="font-size:12px;font-weight:600;color:{_BRAND};cursor:pointer;">
      📝 Draft Outreach Message
    </summary>
    <div style="margin-top:8px;background:#f8f9fa;border-left:3px solid {_ACCENT};
                padding:10px 14px;border-radius:0 4px 4px 0;
                font-size:13px;color:#333;line-height:1.6;font-family:sans-serif;">
      {draft_html}
    </div>
  </details>
</div>"""


def build_html(
    scored_jobs: List[ScoredJob],
    outreach_targets: List[OutreachTarget],
    run_date: Optional[str] = None,
) -> str:
    today = run_date or date.today().isoformat()

    job_cards = "".join(_job_card(i + 1, s) for i, s in enumerate(scored_jobs))
    outreach_cards = "".join(_outreach_card(i + 1, t) for i, t in enumerate(outreach_targets))

    no_roles_msg = (
        '<p style="color:#666;font-style:italic;">No new matching roles found today.</p>'
        if not scored_jobs else ""
    )
    no_outreach_msg = (
        '<p style="color:#666;font-style:italic;">No outreach targets generated today.</p>'
        if not outreach_targets else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Job Search Digest — {today}</title></head>
<body style="margin:0;padding:0;background:{_BG};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:680px;margin:0 auto;padding:24px 16px;">

  <!-- Header -->
  <div style="background:{_BRAND};border-radius:10px 10px 0 0;padding:20px 24px;margin-bottom:0;">
    <div style="color:#fff;font-size:20px;font-weight:700;">🔎 Job Search Digest</div>
    <div style="color:rgba(255,255,255,0.7);font-size:13px;margin-top:4px;">{today}</div>
  </div>

  <!-- Summary bar -->
  <div style="background:#e8f4fd;border:1px solid #bee3f8;border-top:none;
              padding:10px 24px;margin-bottom:24px;border-radius:0 0 8px 8px;">
    <span style="font-size:13px;color:{_BRAND};">
      <b>{len(scored_jobs)}</b> new matching roles &nbsp;·&nbsp;
      <b>{len(outreach_targets)}</b> outreach targets
    </span>
  </div>

  <!-- PART 1 -->
  <div style="font-size:18px;font-weight:700;color:{_BRAND};margin-bottom:4px;">
    Part 1 — Top {len(scored_jobs)} Matching Roles
  </div>
  <div style="font-size:12px;color:{_MUTED};margin-bottom:14px;">
    Scored against your profile: title match · AI/data focus · GTM context · location · company tier
  </div>
  {no_roles_msg}
  {job_cards}

  <!-- Divider -->
  <div style="border-top:2px solid {_BORDER};margin:28px 0;"></div>

  <!-- PART 2 -->
  <div style="font-size:18px;font-weight:700;color:{_BRAND};margin-bottom:4px;">
    Part 2 — Top {len(outreach_targets)} Outreach Targets
  </div>
  <div style="font-size:12px;color:{_MUTED};margin-bottom:14px;">
    Companies to proactively contact this week — expand each card to see a draft message.
  </div>
  {no_outreach_msg}
  {outreach_cards}

  <!-- Footer -->
  <div style="margin-top:32px;padding-top:16px;border-top:1px solid {_BORDER};
              font-size:11px;color:{_MUTED};text-align:center;">
    Generated by your Job Search Agent · ewhitney777@gmail.com
  </div>
</div>
</body></html>"""


def build_plain(
    scored_jobs: List[ScoredJob],
    outreach_targets: List[OutreachTarget],
    run_date: Optional[str] = None,
) -> str:
    today = run_date or date.today().isoformat()
    lines = [
        f"JOB SEARCH DIGEST — {today}",
        "=" * 50,
        "",
        f"PART 1 — TOP {len(scored_jobs)} MATCHING ROLES",
        "-" * 40,
    ]

    for i, s in enumerate(scored_jobs, 1):
        job = s.job
        lines += [
            f"{i}. [{s.score}/10] {job.title} — {job.company}",
            f"   Location: {job.location or 'unspecified'}",
        ]
        if s.salary_mentioned:
            lines.append(f"   Salary: {s.salary_mentioned}")
        lines += [
            f"   {s.match_summary}",
            f"   {job.url}",
            "",
        ]

    lines += [
        "",
        f"PART 2 — TOP {len(outreach_targets)} OUTREACH TARGETS",
        "-" * 40,
    ]

    for i, t in enumerate(outreach_targets, 1):
        lines.append(f"{i}. {t.company}")
        if t.contact:
            linkedin = f" | {t.contact.linkedin_url}" if t.contact.linkedin_url else ""
            lines.append(f"   Contact: {t.contact.name} — {t.contact.title}{linkedin}")
        lines += [
            f"   Why: {t.relevance}",
            f"   Hook: {t.outreach_hook}",
            "",
            "   DRAFT MESSAGE:",
            *[f"   {line}" for line in t.draft_message.splitlines()],
            "",
        ]

    return "\n".join(lines)


def send_digest(
    gmail: GmailClient,
    to: str,
    scored_jobs: List[ScoredJob],
    outreach_targets: List[OutreachTarget],
    run_date: Optional[str] = None,
) -> str:
    """Build and send the digest. Returns the Gmail message ID."""
    today = run_date or date.today().isoformat()
    subject = f"Job Search Digest — {today}"

    html_body = build_html(scored_jobs, outreach_targets, today)
    plain_body = build_plain(scored_jobs, outreach_targets, today)

    # Build a multipart/alternative email (plain + HTML).
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = to
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    result = (
        gmail.service()
        .users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute()
    )
    return result["id"]
