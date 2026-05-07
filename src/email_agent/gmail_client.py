"""Gmail client: OAuth, scrape job-related emails, and send notifications.

First run will pop a browser window asking you to grant Gmail access.
After that, the refresh token is cached in GOOGLE_TOKEN_PATH.
"""

import base64
import os
import re
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Read + send. We don't modify or delete.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


@dataclass
class EmailJobLead:
    message_id: str
    subject: str
    sender: str
    snippet: str
    body: str
    urls: List[str]


class GmailClient:
    def __init__(self, client_secrets_path: str, token_path: str):
        self.client_secrets_path = client_secrets_path
        self.token_path = token_path
        self._service = None

    def _creds(self) -> Credentials:
        creds: Optional[Credentials] = None
        if Path(self.token_path).exists():
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not Path(self.client_secrets_path).exists():
                    raise FileNotFoundError(
                        f"Google OAuth client secrets not found at {self.client_secrets_path}. "
                        "Download from Google Cloud Console (OAuth 2.0 Client ID, Desktop app)."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secrets_path, SCOPES
                )
                creds = flow.run_local_server(port=0)
            Path(self.token_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.token_path).write_text(creds.to_json())
        return creds

    def service(self):
        if self._service is None:
            self._service = build("gmail", "v1", credentials=self._creds(), cache_discovery=False)
        return self._service

    def search_job_emails(
        self, lookback_days: int, search_hints: List[str], max_results: int = 100
    ) -> List[EmailJobLead]:
        clauses = " OR ".join(f"({h})" for h in search_hints) if search_hints else ""
        query = f"newer_than:{lookback_days}d"
        if clauses:
            query = f"{query} ({clauses})"

        svc = self.service()
        resp = (
            svc.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        ids = [m["id"] for m in resp.get("messages", [])]

        leads: List[EmailJobLead] = []
        for mid in ids:
            msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
            leads.append(_parse_message(msg))
        return leads

    def send_email(self, to: str, subject: str, body_markdown: str, attachments: Optional[list] = None) -> str:
        """Send an email from the authenticated account. Returns the message ID."""
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body_markdown)

        for att in attachments or []:
            # att = (filename, bytes, mime_type)
            filename, data, mime = att
            maintype, _, subtype = mime.partition("/")
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        sent = (
            self.service()
            .users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        return sent["id"]


def _parse_message(msg: dict) -> EmailJobLead:
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    body = _extract_body(msg.get("payload", {}))
    urls = _extract_urls(body)
    return EmailJobLead(
        message_id=msg["id"],
        subject=headers.get("subject", ""),
        sender=headers.get("from", ""),
        snippet=msg.get("snippet", ""),
        body=body,
        urls=urls,
    )


def _extract_body(payload: dict) -> str:
    """Walk the MIME tree, prefer text/plain, fall back to text/html (stripped)."""
    parts = [payload]
    plain_chunks: List[str] = []
    html_chunks: List[str] = []
    while parts:
        part = parts.pop()
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data:
            decoded = base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
            if mime == "text/plain":
                plain_chunks.append(decoded)
            elif mime == "text/html":
                html_chunks.append(decoded)
        for sub in part.get("parts", []) or []:
            parts.append(sub)
    if plain_chunks:
        return "\n".join(plain_chunks)
    if html_chunks:
        text = re.sub(r"<[^>]+>", " ", "\n".join(html_chunks))
        return re.sub(r"\s+", " ", text).strip()
    return ""


URL_RE = re.compile(r"https?://[^\s>)\"']+", re.IGNORECASE)


def _extract_urls(text: str) -> List[str]:
    seen = set()
    out = []
    for m in URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,);")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
