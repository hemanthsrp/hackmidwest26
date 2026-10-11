"""One-off data migrations for the evidence table.

SEC filing re-key (stack review, PR #10 follow-up)
--------------------------------------------------
SEC filing IDs used to be uuid5(url::title::observed_date). Form 4
enrichment changes both the title (parsed owner/shares) and observed_at
(actual trade date), so the same filing could be stored twice: once as a
metadata-only row from before enrichment (or from a failed XML fetch) and
once enriched. IDs are now uuid5("sec_filing::" + url): one row per filing.

This migration groups existing sec_filing rows by filing URL, keeps one row
per filing -- the enriched one if any, otherwise the most recently
retrieved -- moves it to the new ID, and deletes the rest. It is a dry run
unless --apply is passed, and it never prints row contents.

    python -m scraper_analysis.storage.migrations           # dry run
    python -m scraper_analysis.storage.migrations --apply   # write

It is idempotent: a second run finds nothing to do.
"""

import argparse
from collections import defaultdict
from dataclasses import dataclass, field

from ..models.evidence import Evidence
from ..pipeline.dedup import stable_id
from .store import EvidenceStore, get_store


@dataclass
class RekeyPlan:
    renames: dict[str, str] = field(default_factory=dict)  # old id -> new id
    delete_ids: list[str] = field(default_factory=list)
    groups: int = 0

    @property
    def is_noop(self) -> bool:
        return not self.renames and not self.delete_ids


def _rank(e: Evidence) -> tuple:
    # Enriched beats metadata-only; then newest retrieval wins.
    return ("insider" in (e.details or {}), e.retrieved_at)


def plan_sec_filing_rekey(rows: list[Evidence]) -> RekeyPlan:
    plan = RekeyPlan()
    by_filing: dict[str, list[Evidence]] = defaultdict(list)
    for row in rows:
        if row.source_type == "sec_filing" and row.source_url:
            by_filing[stable_id(row)].append(row)
    for new_id, group in by_filing.items():
        plan.groups += 1
        keep = max(group, key=_rank)
        plan.delete_ids += [r.id for r in group if r is not keep]
        if keep.id != new_id:
            plan.renames[keep.id] = new_id
    return plan


def migrate_sec_filing_ids(store: EvidenceStore | None = None, apply: bool = False) -> RekeyPlan:
    store = store or get_store()
    plan = plan_sec_filing_rekey(store.query_evidence_by_source_type("sec_filing"))
    if apply and not plan.is_noop:
        store.rekey_evidence(plan.renames, plan.delete_ids)
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = parser.parse_args()
    plan = migrate_sec_filing_ids(apply=args.apply)
    mode = "applied" if args.apply else "dry run"
    print(
        f"sec_filing re-key ({mode}): {plan.groups} filing(s), "
        f"{len(plan.renames)} row(s) re-keyed, {len(plan.delete_ids)} duplicate row(s) deleted"
    )


if __name__ == "__main__":
    main()
