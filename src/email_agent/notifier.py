"""Notifier: send a digest email with tailored resumes attached."""

from pathlib import Path
from typing import List

from .gmail_client import GmailClient
from .models import TailoredResume


def write_to_outbox(outbox_dir: str, tailored: List[TailoredResume]) -> List[Path]:
    """Write each tailored resume to disk for review. Returns the paths written."""
    out_dir = Path(outbox_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    for t in tailored:
        slug = _slug(f"{t.job.company}_{t.job.title}")
        p = out_dir / f"{slug}.md"
        body = (
            f"# Tailored resume — {t.job.title} at {t.job.company}\n"
            f"\n<!-- {t.job.url} -->\n\n"
            f"{t.markdown}\n\n"
            f"---\n\n"
            f"## Cover blurb\n\n{t.cover_blurb}\n"
        )
        p.write_text(body, encoding="utf-8")
        paths.append(p)
    return paths


def send_digest(
    gmail: GmailClient,
    to: str,
    tailored: List[TailoredResume],
) -> str:
    if not tailored:
        return ""

    lines = [
        f"Found {len(tailored)} new role(s) at your target companies. Tailored resumes attached.",
        "",
    ]
    for t in tailored:
        lines.append(f"- {t.job.company} — {t.job.title}")
        if t.job.location:
            lines.append(f"    {t.job.location}")
        lines.append(f"    {t.job.url}")
        if t.cover_blurb:
            lines.append(f"    \"{t.cover_blurb}\"")
        lines.append("")

    body = "\n".join(lines)
    attachments = []
    for t in tailored:
        slug = _slug(f"{t.job.company}_{t.job.title}")
        content = (
            f"# {t.job.title} — {t.job.company}\n\n"
            f"{t.markdown}\n\n---\n\n## Cover blurb\n\n{t.cover_blurb}\n"
        )
        attachments.append((f"{slug}.md", content.encode("utf-8"), "text/markdown"))

    subject = f"[Job Agent] {len(tailored)} new role(s) at target companies"
    return gmail.send_email(to=to, subject=subject, body_markdown=body, attachments=attachments)


def _slug(s: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:80]
