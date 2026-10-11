"""Check model-written explanation text with Jev before it is returned.

The agent's prompt forbids advice and invented facts and its citations are
verified by id. This is a second, independent check of the *text*: is each
point backed by what its cited news says, and does the wording read as personal
advice or a promised outcome.

This is the last stop before the text reaches a user, so a hit is acted on: an
unsupported point is removed, and advice or promise language makes the caller
fall back to the templated explanation. When Jev is unavailable the text passes
through unreviewed and the response says so.

Scope follows ``scraper-analysis/agents/jev_guard.py``: only text citing news or
social records is compared, against those records' title and summary. Points
resting on filings, disclosures or signals are not checked, because their facts
are in structured details and numbers that this comparison cannot see. These
are heuristic model judgments, not verification.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from .explain import AGENT_ENGINE, Explanation
from .legs import NEWS_SOURCE_TYPES
from .models import EvidenceRecord, ResponseWarning

logger = logging.getLogger(__name__)

MAX_REVIEW_WORKERS = 4


class ExplanationChecker(Protocol):
    """``research_api.decision.JevExplanationAdapter`` satisfies this."""

    def review(self, *, explanation: str, evidence: Sequence[Mapping[str, Any]]) -> Any: ...


@dataclass
class ReviewOutcome:
    explanation: Explanation
    # None when no review was attempted (no checker, or code-written text).
    meta: dict[str, Any] | None = None
    replace_with_template: bool = False


def _cited_news(ids: list[str], by_id: dict[str, EvidenceRecord]) -> list[dict[str, Any]]:
    return [
        {"id": by_id[i].id, "title": by_id[i].title, "summary": by_id[i].summary}
        for i in ids
        if i in by_id and by_id[i].source_type in NEWS_SOURCE_TYPES
    ]


def review_explanation(
    explanation: Explanation,
    evidence_by_id: dict[str, EvidenceRecord],
    checker: ExplanationChecker | None,
) -> ReviewOutcome:
    # The template is assembled by code from structured data; there is no model text to check.
    if checker is None or explanation.engine.name != AGENT_ENGINE:
        return ReviewOutcome(explanation)

    texts = [p.text for p in explanation.points]
    cited = [_cited_news(p.evidence_ids, evidence_by_id) for p in explanation.points]
    if explanation.answer:
        texts.append(explanation.answer)
        cited.append(_cited_news(explanation.answer_evidence_ids, evidence_by_id))
    # One call per text that cites news, plus one over the whole wording for advice and promises.
    jobs = [(text, items) for text, items in zip(texts, cited) if items] + [(" ".join(texts), [])]

    try:
        with ThreadPoolExecutor(max_workers=MAX_REVIEW_WORKERS) as pool:
            results = list(pool.map(lambda job: checker.review(explanation=job[0], evidence=job[1]), jobs))
    except Exception as exc:
        logger.warning("explanation review failed: %s", type(exc).__name__)
        return _unavailable(explanation, type(exc).__name__)
    failed = next((r for r in results if r.status != "available"), None)
    if failed is not None:
        return _unavailable(explanation, failed.error)

    framing = results[-1]
    support = iter(results[:-1])
    warnings = list(explanation.warnings)
    points_meta: list[dict[str, Any]] = []
    kept = []
    for index, (point, items) in enumerate(zip(explanation.points, cited)):
        if not items:
            points_meta.append({"index": index, "status": "not_checked", "reason": "cites no news or social records"})
            kept.append(point)
            continue
        unsupported = next(support).unsupported_sentences
        points_meta.append(
            {"index": index, "status": "checked", "unsupported_sentences": len(unsupported), "evidence_checked": len(items)}
        )
        if unsupported:
            warnings.append(
                ResponseWarning(
                    code="unsupported_point_removed",
                    message=f"Removed an explanation point its cited evidence may not support: {unsupported[0][:80]!r}",
                )
            )
        else:
            kept.append(point)

    answer, answer_ids, answer_meta = explanation.answer, explanation.answer_evidence_ids, None
    if explanation.answer:
        if cited[-1]:
            unsupported = next(support).unsupported_sentences
            answer_meta = {"status": "checked", "unsupported_sentences": len(unsupported), "evidence_checked": len(cited[-1])}
            if unsupported:
                answer, answer_ids = None, []
                warnings.append(
                    ResponseWarning(
                        code="unsupported_answer_removed",
                        message="Removed the answer to the question: its cited evidence may not support it.",
                    )
                )
        else:
            answer_meta = {"status": "not_checked", "reason": "cites no news or social records"}

    flagged = bool(framing.reads_as_advice or framing.promises_result)
    if flagged:
        what = "personal investment advice" if framing.reads_as_advice else "a future outcome presented as certain"
        warnings.append(
            ResponseWarning(
                code="explanation_replaced",
                message=f"The model's wording read as {what}; a templated explanation is shown instead.",
            )
        )
    elif not kept:
        warnings.append(
            ResponseWarning(
                code="explanation_replaced",
                message="No model-written point passed review; a templated explanation is shown instead.",
            )
        )

    reviewed = explanation.model_copy(
        update={"points": kept, "answer": answer, "answer_evidence_ids": answer_ids, "warnings": warnings}
    )
    meta = {
        "engine": "jev",
        "points": points_meta,
        "answer": answer_meta,
        "personal_advice": framing.personal_advice,
        "promises_outcome": framing.promises_outcome,
    }
    return ReviewOutcome(reviewed, meta, replace_with_template=flagged or not kept)


def _unavailable(explanation: Explanation, error: str | None) -> ReviewOutcome:
    warnings = [
        *explanation.warnings,
        ResponseWarning(
            code="explanation_review_unavailable",
            message="Jev could not review the explanation text; it is shown unreviewed.",
            retryable=True,
        ),
    ]
    return ReviewOutcome(
        explanation.model_copy(update={"warnings": warnings}),
        {"engine": "unavailable", "error": error},
    )
