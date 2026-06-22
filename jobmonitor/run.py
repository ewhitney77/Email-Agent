"""Entry point: scrape targets, score new postings, alert on matches.

Usage:
    python -m jobmonitor.run                 # one full pass
    python -m jobmonitor.run --threshold 0.8
    python -m jobmonitor.run --company Cribl # restrict to one target
    python -m jobmonitor.run --dry-run       # don't write state or send email
"""

from __future__ import annotations

import argparse
import sys

from . import config as cfgmod
from .alerts import log_match, send_email
from .config import Config
from .matcher import SemanticMatcher
from .scraper import fetch_description, scrape_target
from .state import SeenStore


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Semantic job-posting monitor")
    p.add_argument("--threshold", type=float, help="Override similarity threshold (e.g. 0.75)")
    p.add_argument("--company", help="Only process the target with this company name")
    p.add_argument("--dry-run", action="store_true", help="Do not persist state or send email")
    p.add_argument("--reprocess", action="store_true", help="Ignore the seen-store and score everything")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = Config.from_env()
    if args.threshold is not None:
        cfg.threshold = args.threshold

    targets = cfgmod.load_targets()
    if args.company:
        targets = [t for t in targets if t.get("company", "").lower() == args.company.lower()]
        if not targets:
            print(f"No target named {args.company!r} in {cfgmod.TARGETS_FILE}")
            return 1

    print(f"Loading ideal-role profiles from {cfgmod.IDEAL_ROLES_DIR} ...")
    matcher = SemanticMatcher(cfg, cfgmod.IDEAL_ROLES_DIR)
    print(f"Loaded {len(matcher.role_names)} profile(s); threshold={cfg.threshold}")

    store = SeenStore(cfgmod.STATE_FILE)
    matches_for_email: list[tuple] = []
    new_count = 0

    for target in targets:
        company = target.get("company", target.get("url", "?"))
        print(f"\n=== {company} ===")
        try:
            postings = scrape_target(target, cfg)
        except Exception as exc:  # network/parse errors shouldn't kill the run
            print(f"  ! failed to scrape: {exc}")
            continue
        print(f"  found {len(postings)} candidate posting(s)")

        for posting in postings:
            if not args.reprocess and store.has(posting.url):
                continue
            new_count += 1
            posting.description = fetch_description(posting.url, cfg, target.get("render", "auto"))
            text = f"{posting.title}\n\n{posting.description}"
            matched, result = matcher.is_match(text)

            flag = "MATCH" if matched else "     "
            print(f"  [{flag}] {result.score:.3f}  {posting.title}")

            if matched:
                log_match(cfgmod.MATCHES_LOG, posting, result.score, result.best_role)
                matches_for_email.append((posting, result.score, result.best_role))

            if not args.dry_run:
                store.mark(
                    posting.url,
                    company=posting.company,
                    title=posting.title,
                    matched=matched,
                    score=result.score,
                )

    if not args.dry_run:
        store.save()

    print(f"\nProcessed {new_count} new posting(s); {len(matches_for_email)} match(es).")
    if matches_for_email:
        print(f"Matches written to {cfgmod.MATCHES_LOG}")
        if not args.dry_run and send_email(cfg, matches_for_email):
            print(f"Email sent to {cfg.smtp.recipient}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
