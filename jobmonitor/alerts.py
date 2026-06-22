"""Alert outputs: append to matches.log and optionally send an email via SMTP."""

from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from .config import Config
from .scraper import Posting


def log_match(log_path: Path, posting: Posting, score: float, best_role: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = (
        f"{ts}\t{posting.company}\t{posting.title}\t"
        f"score={score:.4f}\tmatched_role={best_role}\t{posting.url}\n"
    )
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def send_email(cfg: Config, postings: list[tuple[Posting, float, str]]) -> bool:
    """Send a single digest email for all matches found this run.

    Returns True on success, False if disabled or sending failed.
    """
    smtp = cfg.smtp
    if not smtp.enabled or not postings:
        return False
    if not (smtp.host and smtp.sender and smtp.recipient):
        print("[alerts] SMTP enabled but host/sender/recipient missing; skipping email.")
        return False

    lines = []
    for posting, score, role in postings:
        lines.append(
            f"- {posting.company}: {posting.title}\n"
            f"    similarity {score:.2f} (closest profile: {role})\n"
            f"    {posting.url}"
        )
    body = (
        f"{len(postings)} new job posting(s) matched your target profile:\n\n"
        + "\n\n".join(lines)
    )

    msg = EmailMessage()
    msg["Subject"] = f"[Job Monitor] {len(postings)} new match(es)"
    msg["From"] = smtp.sender
    msg["To"] = smtp.recipient
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp.host, smtp.port, timeout=30) as server:
            if smtp.use_tls:
                server.starttls()
            if smtp.username and smtp.password:
                server.login(smtp.username, smtp.password)
            server.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        print(f"[alerts] Failed to send email: {exc}")
        return False
