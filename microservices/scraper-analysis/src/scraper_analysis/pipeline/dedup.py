import re
from uuid import NAMESPACE_URL, uuid5

from ..models.evidence import Evidence


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def _fingerprint(evidence: Evidence) -> str:
    if evidence.source_type == "sec_filing" and evidence.source_url:
        # One SEC filing == one evidence row. The filing URL embeds the
        # accession number, which is unique and never changes; title and
        # date do (Form 4 enrichment rewrites the title and moves
        # observed_at to the trade date), and must not mint a new ID. See
        # storage/migrations.py for re-keying rows stored under the old scheme.
        return f"sec_filing::{evidence.source_url.strip().lower()}"
    title = _normalize_title(evidence.title)
    day = evidence.observed_at.date().isoformat() if evidence.observed_at else ""
    if evidence.source_url:
        # URL alone is not enough: one Senate PTR page holds several
        # distinct transactions, so title (type/ticker/amount) and the
        # transaction date are part of the identity too.
        return f"{evidence.source_url.strip().lower()}::{title}::{day}"
    return f"{evidence.symbol.upper()}::{evidence.source_name}::{title}::{day}"


def stable_id(evidence: Evidence) -> str:
    """Deterministic ID from the fingerprint, so re-ingesting the same item
    on a later run yields the same ID and the store's ON CONFLICT (id)
    actually dedupes across runs (random uuid4 IDs never could)."""
    return str(uuid5(NAMESPACE_URL, _fingerprint(evidence)))


def dedup_evidence(items: list[Evidence]) -> list[Evidence]:
    """Exact-match dedup within one batch. A MinHash/cosine-similarity
    upgrade for near-duplicate articles across sources is a documented
    follow-up, not implemented here."""
    seen: set[str] = set()
    deduped: list[Evidence] = []
    for item in items:
        fp = _fingerprint(item)
        if fp in seen:
            continue
        seen.add(fp)
        deduped.append(item)
    return deduped


def record_rank(data_mode: str | None, details: dict | None) -> tuple[bool, bool]:
    """How good a stored copy of one record is, compared lexicographically:
    live beats sample (a fixture must never block, or later overwrite, real
    data), then parsed details beat metadata-only (a Form 4 whose XML fetch
    failed)."""
    return (data_mode != "sample", "insider" in (details or {}))


def is_upgrade(existing: Evidence, new: Evidence) -> bool:
    """True when `new` is a strictly better copy of the SAME record (same
    stable ID) than the stored `existing` one, so the stored row is replaced
    rather than kept. Never true for a downgrade: a later sample cannot
    replace live data, and a later metadata-only copy cannot replace parsed
    details."""
    return record_rank(new.data_mode, new.details) > record_rank(existing.data_mode, existing.details)


def assign_stable_ids(items: list[Evidence]) -> None:
    for item in items:
        item.id = stable_id(item)
