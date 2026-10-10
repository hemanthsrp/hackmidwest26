import re

from ..models.evidence import Evidence


def _fingerprint(evidence: Evidence) -> str:
    if evidence.source_url:
        return evidence.source_url.strip().lower()
    normalized_title = re.sub(r"\s+", " ", evidence.title.strip().lower())
    return f"{evidence.symbol.upper()}::{evidence.source_name}::{normalized_title}"


def dedup_evidence(items: list[Evidence]) -> list[Evidence]:
    """v1 exact-match dedup on URL (or symbol+source+normalized title when no
    URL is available). A MinHash/cosine-similarity upgrade for near-duplicate
    articles across sources is a documented follow-up, not implemented here."""
    seen: set[str] = set()
    deduped: list[Evidence] = []
    for item in items:
        fp = _fingerprint(item)
        if fp in seen:
            continue
        seen.add(fp)
        deduped.append(item)
    return deduped
