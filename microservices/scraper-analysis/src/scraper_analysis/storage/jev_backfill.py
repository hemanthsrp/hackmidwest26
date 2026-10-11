"""Bounded Jev/grade write-back for already stored article evidence.

Run from scraper-analysis with JEV_ENABLED=true and TYPESAFE_API_KEY set:
  python -m scraper_analysis.storage.jev_backfill --limit 100          # dry run
  python -m scraper_analysis.storage.jev_backfill --limit 100 --apply  # persist
"""

from __future__ import annotations

import argparse
import json

from ..config import get_settings
from ..models.evidence import Evidence
from ..pipeline.grade import grade_evidence
from ..pipeline.jev_judge import judge_evidence
from .db import connect


def load_unjudged(limit: int) -> list[Evidence]:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    with connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, symbol, title, summary, source_name, source_type, source_url,
                      published_at, observed_at, retrieved_at, reporting_lag_days,
                      entities, sentiment, credibility, data_mode, details
               FROM evidence
               WHERE source_type IN ('general_news', 'social_media')
                 AND NOT (details ? 'jev')
               ORDER BY retrieved_at DESC LIMIT %s""",
            (limit,),
        )
        columns = ("id", "symbol", "title", "summary", "source_name", "source_type", "source_url",
                   "published_at", "observed_at", "retrieved_at", "reporting_lag_days", "entities",
                   "sentiment", "credibility", "data_mode", "details")
        return [Evidence(**{**dict(zip(columns, row)), "id": str(row[0])}) for row in cur.fetchall()]


def backfill(limit: int, apply: bool) -> tuple[int, int]:
    rows = load_unjudged(limit)
    judged = grade_evidence(judge_evidence(rows))
    changed = [row for row in judged if "jev" in row.details]
    if apply and changed:
        settings = get_settings()
        with connect(settings) as conn, conn.transaction(), conn.cursor() as cur:
            for row in changed:
                cur.execute("UPDATE evidence SET details = %s WHERE id = %s", (json.dumps(row.details), row.id))
    return len(rows), len(changed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 500:
        raise SystemExit("--limit must be 1..500")
    scanned, changed = backfill(args.limit, args.apply)
    print(f"jev backfill ({'applied' if args.apply else 'dry run'}): scanned {scanned}, judged {changed}")


if __name__ == "__main__":
    main()
