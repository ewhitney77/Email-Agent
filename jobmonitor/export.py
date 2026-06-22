"""Produce data/results.json for the web dashboard.

Unlike ``jobmonitor.run`` (which alerts only on *new* postings), the export
scores **every** currently-open posting on each target page and ranks them by
similarity, so the dashboard always shows a full, fresh snapshot.

Run locally or from CI:
    python -m jobmonitor.export
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfgmod
from .config import Config
from .matcher import SemanticMatcher
from .scraper import fetch_description, scrape_target

OUTPUT_FILE = Path(cfgmod.ROOT / "data" / "results.json")


def build_snapshot(cfg: Config) -> dict:
    targets = cfgmod.load_targets()
    matcher = SemanticMatcher(cfg, cfgmod.IDEAL_ROLES_DIR)

    companies = []
    for target in targets:
        company = target.get("company", target.get("url", "?"))
        print(f"=== {company} ===")
        roles = []
        error = None
        try:
            postings = scrape_target(target, cfg)
        except Exception as exc:  # noqa: BLE001 - never let one site kill the run
            postings = []
            error = str(exc)
            print(f"  ! scrape failed: {exc}")

        for posting in postings:
            # ATS APIs already include the full description; only fetch when missing.
            if not posting.description:
                posting.description = fetch_description(
                    posting.url, cfg, target.get("render", "auto")
                )
            text = f"{posting.title}\n\n{posting.description}"
            result = matcher.score(text)
            roles.append(
                {
                    "title": posting.title,
                    "url": posting.url,
                    "score": round(result.score, 4),
                    "matched": result.score >= cfg.threshold,
                    "best_role": result.best_role,
                }
            )

        roles.sort(key=lambda r: r["score"], reverse=True)
        print(f"  {len(roles)} role(s); top score "
              f"{roles[0]['score'] if roles else 0:.3f}")

        companies.append(
            {
                "company": company,
                "url": target.get("url", ""),
                "error": error,
                "match_count": sum(1 for r in roles if r["matched"]),
                "top_score": roles[0]["score"] if roles else 0.0,
                "roles": roles,
            }
        )

    # Surface companies with the strongest opportunities first.
    companies.sort(key=lambda c: c["top_score"], reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "threshold": cfg.threshold,
        "embedding_backend": cfg.embedding_backend,
        "ideal_roles": matcher.role_names,
        "company_count": len(companies),
        "total_matches": sum(c["match_count"] for c in companies),
        "companies": companies,
    }


def main() -> int:
    cfg = Config.from_env()
    snapshot = build_snapshot(cfg)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"\nWrote {OUTPUT_FILE} "
          f"({snapshot['company_count']} companies, "
          f"{snapshot['total_matches']} matches).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
