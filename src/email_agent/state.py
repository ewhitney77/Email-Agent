"""SQLite store for jobs we've already seen, so we don't re-alert."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_jobs (
    job_key      TEXT PRIMARY KEY,
    company      TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    source       TEXT NOT NULL,
    first_seen   TEXT NOT NULL DEFAULT (datetime('now')),
    notified_at  TEXT
);

CREATE TABLE IF NOT EXISTS seen_emails (
    message_id   TEXT PRIMARY KEY,
    seen_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class State:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def has_job(self, key: str) -> bool:
        with self._conn() as c:
            cur = c.execute("SELECT 1 FROM seen_jobs WHERE job_key = ?", (key,))
            return cur.fetchone() is not None

    def record_job(self, key: str, company: str, title: str, url: str, source: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO seen_jobs (job_key, company, title, url, source) VALUES (?, ?, ?, ?, ?)",
                (key, company, title, url, source),
            )

    def mark_notified(self, key: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE seen_jobs SET notified_at = datetime('now') WHERE job_key = ?",
                (key,),
            )

    def has_email(self, message_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("SELECT 1 FROM seen_emails WHERE message_id = ?", (message_id,))
            return cur.fetchone() is not None

    def record_email(self, message_id: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO seen_emails (message_id) VALUES (?)",
                (message_id,),
            )
