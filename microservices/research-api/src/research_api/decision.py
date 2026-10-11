"""Decision-adapter boundary for the research API.

The shared ``microservices/jev-tool`` package remains the owner of TypeSafe/Jev
transport and configuration. This module deliberately depends only on its public
``judge_article`` shape so API orchestration is testable without live credentials.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class JevArticleJudgment(Protocol):
    """Subset of the shared Jev result used by the API boundary."""

    engine: str
    error: str | None
    direction: str | None
    materiality: float | None


class JevArticleJudge(Protocol):
    """Public ``jev-tool`` capability consumed by this API."""

    def judge_article(
        self, symbol: str, company: str, title: str, summary: str
    ) -> JevArticleJudgment: ...


@dataclass(frozen=True)
class DecisionResult:
    """A safe, provider-agnostic decision-adapter result."""

    status: str
    engine: str
    direction: str | None
    materiality: float | None
    error: str | None
    # The rest of Jev's judgment, when the shared tool supplies it. All optional,
    # so callers written against the five fields above are unaffected.
    relevant: float | None = None
    direction_confidence: float | None = None
    content_type: str | None = None
    event_type: str | None = None
    upcoming_event: float | None = None
    sensational: float | None = None
    usable_content: float | None = None
    materiality_confidence: float | None = None
    model: str | None = None
    request_id: str | None = None
    question_set_version: str | None = None
    # "call" when Jev was asked now, "stored" when read from an evidence record.
    source: str = "call"


_EXTRA_FIELDS = (
    "relevant",
    "direction_confidence",
    "content_type",
    "event_type",
    "upcoming_event",
    "sensational",
    "usable_content",
    "materiality_confidence",
    "model",
    "request_id",
    "question_set_version",
)


class JevDecisionAdapter:
    """Adapt the existing shared Jev tool without duplicating its client logic."""

    def __init__(self, judge: JevArticleJudge) -> None:
        self._judge = judge

    def judge_article(
        self, *, symbol: str, company: str, title: str, summary: str
    ) -> DecisionResult:
        result = self._judge.judge_article(symbol, company, title, summary)
        if result.engine != "jev":
            return DecisionResult(
                status="unavailable",
                engine="unavailable",
                direction=None,
                materiality=None,
                error=result.error or "Jev did not return a judgment.",
            )
        return DecisionResult(
            status="available",
            engine="jev",
            direction=result.direction,
            materiality=result.materiality,
            error=None,
            **{name: getattr(result, name, None) for name in _EXTRA_FIELDS},
        )

    @staticmethod
    def from_stored(judgment: Mapping[str, Any] | None) -> DecisionResult:
        """Read a judgment that ``scraper-analysis`` stored on an evidence record
        (``details["jev"]``). No Jev call is made. A record that was never judged,
        or that Jev could not answer for, comes back as unavailable."""
        if not judgment or judgment.get("engine") != "jev":
            error = (judgment or {}).get("error") or "No stored Jev judgment for this record."
            return DecisionResult(
                status="unavailable",
                engine="unavailable",
                direction=None,
                materiality=None,
                error=error,
                source="stored",
            )
        return DecisionResult(
            status="available",
            engine="jev",
            direction=judgment.get("direction"),
            materiality=judgment.get("materiality"),
            error=None,
            source="stored",
            **{name: judgment.get(name) for name in _EXTRA_FIELDS},
        )

    def judge_evidence(self, evidence: Mapping[str, Any], *, company: str) -> DecisionResult:
        """Judge one evidence record. Uses the judgment stored on it when there is
        one, so an article judged at ingestion is not sent to Jev a second time."""
        stored = self.from_stored((evidence.get("details") or {}).get("jev"))
        if stored.status == "available":
            return stored
        return self.judge_article(
            symbol=evidence["symbol"],
            company=company,
            title=evidence["title"],
            summary=evidence.get("summary") or "",
        )


class JevExplanationChecker(Protocol):
    """Public ``jev-tool`` capability: ``JevTool.check_explanation``."""

    def check_explanation(self, explanation: str, evidence: Sequence[Mapping[str, Any]]) -> Any: ...


@dataclass(frozen=True)
class ExplanationReview:
    """Advisory review of generated explanation text. Probabilities are Jev's;
    the flags apply this module's thresholds. Nothing here edits the text."""

    status: str
    engine: str
    error: str | None
    unsupported_sentences: tuple[str, ...] = ()
    personal_advice: float | None = None
    promises_outcome: float | None = None
    reads_as_advice: bool = False
    promises_result: bool = False


SUPPORT_FLOOR = 0.5
FLAG_THRESHOLD = 0.5


class JevExplanationAdapter:
    """Check an explanation against the evidence it should rest on, before it is
    returned. Sentences that state no fact about the evidence (a label, a
    disclaimer) score as unsupported; pass only the factual part of the text."""

    def __init__(self, checker: JevExplanationChecker) -> None:
        self._checker = checker

    def review(self, *, explanation: str, evidence: Sequence[Mapping[str, Any]]) -> ExplanationReview:
        result = self._checker.check_explanation(explanation, evidence)
        if result.engine != "jev":
            return ExplanationReview(
                status="unavailable",
                engine="unavailable",
                error=result.error or "Jev did not review the explanation.",
            )
        return ExplanationReview(
            status="available",
            engine="jev",
            error=None,
            unsupported_sentences=tuple(c.text for c in result.claims if c.supported < SUPPORT_FLOOR),
            personal_advice=result.personal_advice,
            promises_outcome=result.promises_outcome,
            reads_as_advice=result.personal_advice >= FLAG_THRESHOLD,
            promises_result=result.promises_outcome >= FLAG_THRESHOLD,
        )
