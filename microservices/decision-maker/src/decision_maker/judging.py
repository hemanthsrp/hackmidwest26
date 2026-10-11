"""Judge news the store holds without a Jev judgment.

``scraper-analysis`` judges news at ingestion only when Jev is enabled there,
and has no backfill, so rows stored earlier carry no judgment and could not
count toward the news leg. This asks the injected judge about the newest of
those, bounded, at decision time. Nothing is written back to the store; answers
are kept in memory so a repeat request does not send the same article again.

A record Jev does not answer for stays unjudged and is reported; it is never
given a stand-in judgment.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from .legs import NEWS_SOURCE_TYPES
from .models import EvidenceRecord, as_utc

logger = logging.getLogger(__name__)

MAX_FRESH_JUDGMENTS = 24
MAX_JUDGE_WORKERS = 8
MAX_CACHED_JUDGMENTS = 5000

_FIELDS = (
    "relevant",
    "direction",
    "direction_confidence",
    "content_type",
    "event_type",
    "upcoming_event",
    "sensational",
    "usable_content",
    "materiality",
    "materiality_confidence",
    "model",
    "request_id",
    "question_set_version",
)


class ArticleJudge(Protocol):
    """``research_api.decision.JevDecisionAdapter`` satisfies this."""

    def judge_evidence(self, evidence: Mapping[str, Any], *, company: str) -> Any: ...


def judge_missing(
    evidence: list[EvidenceRecord],
    judge: ArticleJudge,
    company: str,
    cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[EvidenceRecord], dict[str, Any]]:
    """Return the records with judgments attached, and what happened. ``cache``
    maps an evidence id to a judgment made earlier in this process."""
    cache = cache if cache is not None else {}
    unjudged = sorted(
        (e for e in evidence if e.source_type in NEWS_SOURCE_TYPES and e.data_mode != "sample" and not e.jev),
        key=lambda e: as_utc(e.published_at or e.retrieved_at),
        reverse=True,
    )
    known = [e for e in unjudged if e.id in cache]
    targets = [e for e in unjudged if e.id not in cache][:MAX_FRESH_JUDGMENTS]
    stats: dict[str, Any] = {
        "unjudged": len(unjudged),
        "from_cache": len(known),
        "asked": len(targets),
        "judged": 0,
        "unavailable": 0,
        "error": None,
    }

    def ask(record: EvidenceRecord) -> Any:
        payload = {"id": record.id, "symbol": record.symbol, "title": record.title, "summary": record.summary}
        try:
            return judge.judge_evidence(payload, company=company)
        except Exception as exc:
            logger.warning("fresh judgment failed for %s: %s", record.id, type(exc).__name__)
            return None

    results: list[Any] = []
    if targets:
        with ThreadPoolExecutor(max_workers=MAX_JUDGE_WORKERS) as pool:
            results = list(pool.map(ask, targets))

    if len(cache) + len(targets) > MAX_CACHED_JUDGMENTS:
        cache.clear()
    for record, result in zip(targets, results):
        if result is None or result.status != "available":
            stats["unavailable"] += 1
            stats["error"] = stats["error"] or getattr(result, "error", None) or "judge raised"
            continue
        cache[record.id] = {
            "engine": "jev",
            "judged_at": "decision",
            **{name: getattr(result, name, None) for name in _FIELDS},
        }
        stats["judged"] += 1

    def with_judgment(record: EvidenceRecord) -> EvidenceRecord:
        judgment = cache.get(record.id) if not record.jev else None
        if judgment is None:
            return record
        return record.model_copy(update={"details": {**record.details, "jev": judgment}})

    return [with_judgment(e) for e in evidence], stats
