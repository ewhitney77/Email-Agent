"""Local JSON store of postings we have already processed.

Keyed by a stable hash of the posting URL so each posting is handled once.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def posting_id(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]


class SeenStore:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def has(self, url: str) -> bool:
        return posting_id(url) in self._data

    def mark(self, url: str, *, company: str, title: str, matched: bool, score: float) -> None:
        self._data[posting_id(url)] = {
            "url": url,
            "company": company,
            "title": title,
            "matched": matched,
            "score": round(score, 4),
            "seen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def __len__(self) -> int:
        return len(self._data)
