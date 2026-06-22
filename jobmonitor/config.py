"""Configuration loading.

All tunable settings come from environment variables (optionally loaded from a
local .env file) with sensible defaults so the tool runs with zero config.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Project root = the directory that contains this package.
ROOT = Path(__file__).resolve().parent.parent

# Default file locations (overridable via env).
TARGETS_FILE = Path(os.getenv("TARGETS_FILE", ROOT / "targets.json"))
IDEAL_ROLES_DIR = Path(os.getenv("IDEAL_ROLES_DIR", ROOT / "ideal_roles"))
STATE_FILE = Path(os.getenv("STATE_FILE", ROOT / "state" / "seen.json"))
MATCHES_LOG = Path(os.getenv("MATCHES_LOG", ROOT / "matches.log"))
EMBED_CACHE_FILE = Path(os.getenv("EMBED_CACHE_FILE", ROOT / "state" / "embed_cache.json"))


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no external dependency)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Do not clobber values already present in the real environment.
        os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")


def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class SmtpConfig:
    enabled: bool = False
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    sender: str = ""
    recipient: str = ""
    use_tls: bool = True


@dataclass
class Config:
    # Matching
    threshold: float = 0.60
    embedding_backend: str = "sentence-transformers"  # or "openai"
    st_model: str = "all-MiniLM-L6-v2"
    openai_model: str = "text-embedding-3-small"  # ada-002 also supported
    openai_api_key: str = ""

    # Scraping
    request_timeout: int = 20
    max_listings_per_company: int = 60
    use_playwright: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 jobmonitor/0.1"
    )

    smtp: SmtpConfig = field(default_factory=SmtpConfig)

    @classmethod
    def from_env(cls) -> "Config":
        smtp = SmtpConfig(
            enabled=_get_bool("SMTP_ENABLED", False),
            host=os.getenv("SMTP_HOST", ""),
            port=int(os.getenv("SMTP_PORT", "587")),
            username=os.getenv("SMTP_USERNAME", ""),
            password=os.getenv("SMTP_PASSWORD", ""),
            sender=os.getenv("SMTP_SENDER", os.getenv("SMTP_USERNAME", "")),
            recipient=os.getenv("SMTP_RECIPIENT", ""),
            use_tls=_get_bool("SMTP_USE_TLS", True),
        )
        return cls(
            threshold=float(os.getenv("MATCH_THRESHOLD", "0.60")),
            embedding_backend=os.getenv("EMBEDDING_BACKEND", "sentence-transformers"),
            st_model=os.getenv("ST_MODEL", "all-MiniLM-L6-v2"),
            openai_model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "20")),
            max_listings_per_company=int(os.getenv("MAX_LISTINGS_PER_COMPANY", "60")),
            use_playwright=_get_bool("USE_PLAYWRIGHT", True),
            smtp=smtp,
        )


def load_targets() -> list[dict]:
    """Read the watch list from targets.json."""
    if not TARGETS_FILE.exists():
        raise FileNotFoundError(f"targets file not found: {TARGETS_FILE}")
    data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("targets.json must be a JSON array of objects")
    return data
