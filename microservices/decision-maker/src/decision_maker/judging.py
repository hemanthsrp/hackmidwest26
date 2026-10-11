"""Judge news the store holds without a Jev judgment.

``scraper-analysis`` judges news at ingestion only when Jev is enabled there,
and has no backfill, so rows stored earlier carry no judgment and could not
count toward the news leg. This asks the injected judge about the newest of
those, bounded, at decision time. Nothing is written back to the store.

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

MAX_FRESH_JUDGMENTS = 12
MAX_JUDGE_WORKERS = 8

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
    evidence: list[EvidenceRecord], judge: ArticleJudge, company: str
) -> tuple[list[EvidenceRecord], dict[str, Any]]:
    """Return the records with fresh judgments attached, and what happened."""
    targets = sorted(
        (e for e in evidence if e.source_type in NEWS_SOURCE_TYPES and e.data_mode != "sample" and not e.jev),
        key=lambda e: as_utc(e.published_at or e.retrieved_at),
        reverse=True,
    )
    stats: dict[str, Any] = {"unjudged": len(targets), "asked": 0, "judged": 0, "unavailable": 0, "error": None}
    targets = targets[:MAX_FRESH_JUDGMENTS]
    if not targets:
        return evidence, stats
    stats["asked"] = len(targets)

    def ask(record: EvidenceRecord) -> Any:
        payload = {"id": record.id, "symbol": record.symbol, "title": record.title, "summary": record.summary}
        try:
            return judge.judge_evidence(payload, company=company)
        except Exception as exc:
            logger.warning("fresh judgment failed for %s: %s", record.id, type(exc).__name__)
            return None

    with ThreadPoolExecutor(max_workers=MAX_JUDGE_WORKERS) as pool:
        results = list(pool.map(ask, targets))

    fresh: dict[str, EvidenceRecord] = {}
    for record, result in zip(targets, results):
        if result is None or result.status != "available":
            stats["unavailable"] += 1
            stats["error"] = stats["error"] or getattr(result, "error", None) or "judge raised"
            continue
        judgment = {"engine": "jev", "judged_at": "decision", **{name: getattr(result, name, None) for name in _FIELDS}}
        fresh[record.id] = record.model_copy(update={"details": {**record.details, "jev": judgment}})
        stats["judged"] += 1
    return [fresh.get(e.id, e) for e in evidence], stats
