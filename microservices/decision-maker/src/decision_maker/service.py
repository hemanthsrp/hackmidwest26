"""The decision maker: evidence, a user question and the math in; one assessment out.

    validate -> retrieve -> legs -> quant -> combine -> explain -> review -> respond

The label comes from every in-window record for the symbol. The user's question
only steers which records the explanation looks at and what it answers, so
rephrasing a question cannot change the label.

Failures are explicit. A live request is never answered from fixtures, a
missing input is reported as missing, and ``insufficient_data`` is a truthful
result rather than an error.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from . import combiner, legs as legs_module, quant as quant_module
from .explain import AgentFactory, ExplainContext, Explanation, explain, lead_sentence, template_explanation
from .judging import ArticleJudge, judge_missing
from .models import (
    HORIZON_DAYS,
    MAX_QUERY_CHARS,
    SYSTEM_REASON_CODES,
    Assessment,
    Decision,
    DecisionRequest,
    DecisionResponse,
    EngineStatus,
    EvidenceRecord,
    Freshness,
    Leg,
    ProviderUnavailableError,
    QuantInput,
    QuantReading,
    ResponseWarning,
    SignalRecord,
    StaleDataError,
    as_utc,
    normalize_symbol,
)
from .retrieval import EvidenceSource, FixtureEvidenceSource
from .review import ExplanationChecker, review_explanation

logger = logging.getLogger(__name__)

STALE_AFTER_SECONDS = 86400
FOCUS_LIMIT = 8
MAX_RETURNED_EVIDENCE = 25

TRACE_NOTE = (
    "Internal trace of a hand-set heuristic rule. net_direction and the 0-100 score derived from it are "
    "not a probability or a forecast."
)


def _clean_query(query: str | None, warnings: list[ResponseWarning]) -> str | None:
    if not query:
        return None
    cleaned = " ".join("".join(ch if ch.isprintable() else " " for ch in query).split())
    if len(cleaned) > MAX_QUERY_CHARS:
        cleaned = cleaned[:MAX_QUERY_CHARS]
        warnings.append(ResponseWarning(code="query_truncated", message=f"The question was cut to {MAX_QUERY_CHARS} characters."))
    return cleaned or None


def _latest_per_series(signals: list[SignalRecord]) -> list[SignalRecord]:
    """One row per signal series, the newest. The store keeps a row per day."""
    latest: dict[tuple[str, str, str], SignalRecord] = {}
    for signal in signals:
        key = (signal.name, signal.window, signal.source)
        if key not in latest or as_utc(signal.as_of) > as_utc(latest[key].as_of):
            latest[key] = signal
    return list(latest.values())


def _uncertainty(
    horizon: str,
    data_mode: str,
    decision: Decision,
    legs: dict[str, Leg],
    reading: QuantReading,
) -> str:
    parts = [
        f"This is a rule-based research heuristic for a {horizon} horizon, not investment advice, "
        "a probability or a validated prediction."
    ]
    if data_mode == "sample":
        parts.append("It rests on sample fixture data, not live market data.")
    if reading.implied_move_pct is not None:
        text = (
            f"Options are pricing a move of roughly {reading.implied_move_pct:.1f}% either way over that horizon "
            "(one standard deviation), which describes the size of the expected movement and not its direction."
        )
        if reading.status == "thin":
            text += " The options data is thin, so that figure is rough."
        parts.append(text)
    else:
        parts.append("No usable options-based math was supplied, so how much movement the market is pricing is unknown.")
    if decision.conflicts:
        parts.append("Kinds of evidence disagree: " + "; ".join(decision.conflicts) + ".")
    missing = [leg.name for leg in legs.values() if not leg.usable]
    if missing:
        parts.append("No usable reading from: " + ", ".join(missing) + ".")
    unjudged = legs["news"].inputs.get("records_unjudged", 0)
    if unjudged:
        parts.append(f"{unjudged} news item(s) had no relevance and direction judgment and were left out of the news reading.")
    return " ".join(parts)


class DecisionMaker:
    def __init__(
        self,
        *,
        evidence_source: EvidenceSource | None = None,
        agent_factory: AgentFactory | None = None,
        agent_model: str | None = None,
        use_agent_tools: bool = False,
        article_judge: ArticleJudge | None = None,
        explanation_checker: ExplanationChecker | None = None,
        companies: Mapping[str, str] | None = None,
        stale_after_seconds: int = STALE_AFTER_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._evidence_source = evidence_source
        self._agent_factory = agent_factory
        self._agent_model = agent_model
        self._use_agent_tools = use_agent_tools
        self._article_judge = article_judge
        self._explanation_checker = explanation_checker
        self._companies = companies or {}
        self._stale_after_seconds = stale_after_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # Judgments made at decision time, by evidence id, for the life of this process.
        self._judgment_cache: dict[str, dict[str, Any]] = {}

    def decide(self, request: DecisionRequest, quant: QuantInput | None = None) -> DecisionResponse:
        """Raises ``InvalidSymbolError``, ``ProviderUnavailableError`` or ``StaleDataError``;
        every other outcome, including ``insufficient_data``, is a response."""
        now = self._clock()
        symbol = normalize_symbol(request.symbol)
        horizon = request.preferences.horizon
        warnings: list[ResponseWarning] = []
        query = _clean_query(request.query, warnings)
        sample = request.mode == "sample"

        if sample:
            source: EvidenceSource = FixtureEvidenceSource(clock=self._clock)
            quant = quant or source.quant(symbol)
            warnings.append(ResponseWarning(code="sample_data", message="Sample fixture data; not live market data."))
        elif self._evidence_source is None:
            raise ProviderUnavailableError(
                "The evidence store is not configured; no assessment was generated.", {"provider": "evidence_store"}
            )
        else:
            source = self._evidence_source

        evidence, signals = source.load(symbol)
        vol_surface = quant.vol_surface if quant else None
        signals = [*signals, *(quant.signals if quant else [])]
        if not sample:
            # A live answer never rests on fixtures, even when nothing live exists.
            ignored = sum(e.data_mode == "sample" for e in evidence) + sum(s.data_mode == "sample" for s in signals)
            evidence = [e for e in evidence if e.data_mode != "sample"]
            signals = [s for s in signals if s.data_mode != "sample"]
            if ignored:
                warnings.append(
                    ResponseWarning(code="sample_records_ignored", message=f"Ignored {ignored} stored fixture record(s).")
                )
            if vol_surface and vol_surface.data_mode == "sample":
                vol_surface = None
                warnings.append(
                    ResponseWarning(code="quant_sample_ignored", message="The supplied options math is sample data and was not used.")
                )

        freshness = self._freshness(evidence, signals, now, enforce=not sample)
        window, excluded = legs_module.in_window(evidence, now)
        if excluded["undated"] or excluded["outside_window"]:
            warnings.append(
                ResponseWarning(
                    code="evidence_outside_window",
                    message=f"{excluded['outside_window']} record(s) older than {legs_module.RECENCY_LOOKBACK_DAYS} days "
                    f"and {excluded['undated']} undated record(s) were not used.",
                )
            )

        judgments = None
        if self._article_judge is not None and not sample:
            window, judgments = judge_missing(
                window, self._article_judge, self._companies.get(symbol, symbol), self._judgment_cache
            )
            if judgments["unavailable"]:
                warnings.append(
                    ResponseWarning(
                        code="news_judgment_unavailable",
                        message=f"Jev did not judge {judgments['unavailable']} news item(s); they were left out of the news reading.",
                        retryable=True,
                    )
                )

        signals = _latest_per_series(signals)
        legs = legs_module.build_legs(window, signals, now)
        reading, quant_rows = quant_module.read_vol_surface(symbol, vol_surface, horizon)
        signals = [*signals, *quant_rows]
        if reading.status == "unavailable":
            warnings.append(
                ResponseWarning(
                    code="quant_unavailable",
                    message="No options-based math was supplied; the assessment uses evidence and the price signal only.",
                )
            )
        elif reading.status == "thin":
            warnings.append(ResponseWarning(code="quant_thin", message=" ".join(reading.notes)))

        decision = combiner.combine(legs, reading, has_evidence=bool(window))
        if decision.label == "insufficient_data":
            warnings.append(
                ResponseWarning(
                    code="insufficient_evidence",
                    message="There is not enough attributable evidence in the recency window to support an assessment.",
                )
            )

        focus_ids, retrieval = self._focus(source, symbol, query, window, warnings)
        ctx = ExplainContext(
            symbol=symbol,
            query=query,
            horizon=horizon,
            risk_profile=request.preferences.risk_profile,
            decision=decision,
            legs=legs,
            quant=reading,
            evidence=window,
            signals=signals,
            as_of=now,
            focus_ids=focus_ids,
            search=lambda text, limit: source.search(symbol, text, limit),
        )
        explanation = explain(ctx, self._agent_factory, use_tools=self._use_agent_tools, model=self._agent_model)
        outcome = review_explanation(explanation, {e.id: e for e in window}, self._explanation_checker)
        explanation = outcome.explanation
        if outcome.replace_with_template:
            replaced = template_explanation(ctx)
            replaced.engine.error = "The model-written explanation did not pass review."
            replaced.warnings = explanation.warnings
            explanation = replaced
        warnings += explanation.warnings
        if query and not explanation.answer:
            warnings.append(
                ResponseWarning(code="question_not_answered", message="No model-written answer to the question is available.")
            )

        data_mode = "sample" if sample else "cached" if any(r.data_mode == "cached" for r in [*window, *signals]) else "live"
        return DecisionResponse(
            request_id=f"dm-{uuid.uuid4().hex}",
            symbol=symbol,
            query=query,
            data_mode=data_mode,
            freshness=freshness,
            evidence=self._returned_evidence(window, decision, explanation, focus_ids, now),
            signals=signals,
            assessment=Assessment(
                label=decision.label,
                score=decision.score,
                score_sell_at_or_below=combiner.score_from_net(-decision.threshold) if decision.score is not None else None,
                score_buy_at_or_above=combiner.score_from_net(decision.threshold) if decision.score is not None else None,
                horizon=horizon,
                reason_codes=decision.reason_codes,
                explanation=" ".join([lead_sentence(decision), *(p.text for p in explanation.points)]),
                explanation_points=explanation.points,
                answer=explanation.answer,
                uncertainty=_uncertainty(horizon, data_mode, decision, legs, reading),
                generated_at=now,
                data_mode=data_mode,
                decision_engine=EngineStatus(name=combiner.COMBINER_VERSION, status="used" if window else "not_run"),
            ),
            warnings=warnings,
            meta={
                "decision_trace": {
                    "combiner_version": combiner.COMBINER_VERSION,
                    "note": TRACE_NOTE,
                    "net_direction": decision.net_direction,
                    "threshold": decision.threshold,
                    "threshold_raised_by": decision.threshold_raised_by,
                    "held_because": decision.held_because,
                    "usable_legs": decision.usable_legs,
                    "conflicts": decision.conflicts,
                    "legs": [leg.model_dump() for leg in legs.values()],
                    "quant": reading.model_dump(),
                    "thresholds": {
                        "combiner": combiner.THRESHOLDS,
                        "legs": legs_module.THRESHOLDS,
                        "quant": quant_module.THRESHOLDS,
                    },
                    "horizon_days": HORIZON_DAYS[horizon],
                    "evidence_considered": len(window),
                    "evidence_excluded": excluded,
                    "system_reason_codes": sorted(SYSTEM_REASON_CODES),
                },
                "explanation_engine": explanation.engine.model_dump(),
                "answer_evidence_ids": explanation.answer_evidence_ids,
                "jev_review": outcome.meta,
                "judgments_at_decision": judgments,
                "retrieval": retrieval,
                "quant_citations": quant.quant_citations if quant else [],
            },
        )

    def _freshness(self, evidence: list[EvidenceRecord], signals: list[SignalRecord], now: datetime, *, enforce: bool) -> Freshness:
        retrieved = max((as_utc(e.retrieved_at) for e in evidence), default=None)
        dated = [e.event_time for e in evidence if e.event_time] + [as_utc(s.as_of) for s in signals]
        freshness = Freshness(
            as_of=max(dated, default=None), retrieved_at=retrieved, stale_after_seconds=self._stale_after_seconds
        )
        if retrieved is None:
            return freshness
        age = (now - retrieved).total_seconds()
        freshness.status = "stale" if age > self._stale_after_seconds else "fresh"
        if enforce and freshness.status == "stale":
            raise StaleDataError(
                "Available evidence is older than the allowed freshness window; no current assessment was generated.",
                {"newest_retrieved_at": retrieved.isoformat(), "stale_after_seconds": self._stale_after_seconds},
            )
        return freshness

    def _focus(
        self,
        source: EvidenceSource,
        symbol: str,
        query: str | None,
        window: list[EvidenceRecord],
        warnings: list[ResponseWarning],
    ) -> tuple[list[str], dict[str, Any]]:
        """Records closest to the user's question, for the explanation to look at first."""
        if not query or not window:
            return [], {"semantic_search": "not_requested", "focus_ids": []}
        ids = source.search(symbol, query, FOCUS_LIMIT * 2)
        if ids is None:
            warnings.append(
                ResponseWarning(
                    code="semantic_search_unavailable",
                    message="Semantic search over the evidence was unavailable; the question did not narrow the evidence.",
                    retryable=True,
                )
            )
            return [], {"semantic_search": "unavailable", "focus_ids": []}
        in_window = {e.id for e in window}
        focus = [i for i in ids if i in in_window][:FOCUS_LIMIT]
        return focus, {"semantic_search": "used", "focus_ids": focus}

    @staticmethod
    def _returned_evidence(
        window: list[EvidenceRecord],
        decision: Decision,
        explanation: Explanation,
        focus_ids: list[str],
        now: datetime,
    ) -> list[EvidenceRecord]:
        """Every cited record, then the question's matches, then the strongest of the rest."""
        by_id = {e.id: e for e in window}
        cited = [i for p in explanation.points for i in p.evidence_ids]
        first = [i for i in dict.fromkeys([*decision.reason_codes, *cited, *explanation.answer_evidence_ids, *focus_ids]) if i in by_id]
        rest = sorted(
            (e for e in window if e.id not in first),
            key=lambda e: (legs_module.current_strength(e, now), as_utc(e.published_at or e.retrieved_at)),
            reverse=True,
        )
        room = max(0, MAX_RETURNED_EVIDENCE - len(first))
        return [by_id[i] for i in first] + rest[:room]
