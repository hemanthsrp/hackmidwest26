"""Decision-adapter boundary for the research API.

The shared ``microservices/jev-tool`` package remains the owner of TypeSafe/Jev
transport and configuration. This module deliberately depends only on its public
``judge_article`` shape so API orchestration is testable without live credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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
        )
