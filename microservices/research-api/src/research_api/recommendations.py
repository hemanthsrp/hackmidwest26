"""Recommended stocks for an industry.

Takes the curated universe for the industry, scores each stock with the decision
maker (the same combiner and score as ``/v0/research-assessments``, without the
model-written explanation) and orders them best score first. Stocks the evidence
store cannot score are still listed, after the scored ones, in curated order and
marked by ``assessment_status``. Nothing is invented for them.

The options math is not applied here: it needs one live option-chain fetch per
stock. A stock's detail view can therefore differ slightly from its list score.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from . import assessment
from .universe import INDUSTRIES, STOCKS_PER_INDUSTRY, UNIVERSE_AS_OF

logger = logging.getLogger(__name__)

CACHE_SECONDS = 300
HORIZON = "30d"
RISK_PROFILE = "balanced"

_cache: dict[str, tuple[float, dict[str, Any]]] = {}

# (score, label, assessment_status) for one symbol
Scored = tuple[int | None, str | None, str]
Scorer = Callable[[str], Scored]

BASIS = (
    "Ordered by the heuristic 0-100 research score where the evidence store has enough data, "
    "then the remaining stocks in curated list order. The score is not a probability, forecast or "
    "validated predictor, and this is not investment advice."
)


def list_industries() -> list[dict[str, Any]]:
    return [{"slug": slug, "name": name, "stock_count": len(stocks)} for slug, (name, stocks) in INDUSTRIES.items()]


def make_scorer(maker: Any) -> Scorer:
    """Score one symbol with a decision maker. Never raises; failures become a status."""
    from decision_maker import DecisionError, DecisionRequest, Preferences

    def score(symbol: str) -> Scored:
        request = DecisionRequest(
            symbol=symbol, preferences=Preferences(horizon=HORIZON, risk_profile=RISK_PROFILE), mode="live"
        )
        try:
            result = maker.decide(request).assessment
        except DecisionError as error:
            status = {"stale_data": "stale", "provider_unavailable": "unavailable"}.get(error.code, "error")
            return None, None, status
        except Exception as error:  # one bad symbol must not take the industry down
            logger.warning("recommendation scoring failed for %s: %s", symbol, type(error).__name__)
            return None, None, "error"
        if result.score is None:
            return None, result.label, "insufficient_data"
        return result.score, result.label, "scored"

    return score


def rank_industry(slug: str, scorer: Scorer | None) -> dict[str, Any]:
    name, stocks = INDUSTRIES[slug]
    rows: list[dict[str, Any]] = []
    unavailable = scorer is None
    for order, (symbol, company) in enumerate(stocks):
        if unavailable:
            score, label, status = None, None, "not_assessed"
        else:
            score, label, status = scorer(symbol)
            if status == "unavailable":
                # The store itself is down: do not wait on it 23 more times.
                unavailable = True
        rows.append({"symbol": symbol, "name": company, "score": score, "label": label,
                     "assessment_status": status, "_order": order})
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["_order"]))
    for rank, row in enumerate(rows, start=1):
        row.pop("_order")
        row["rank"] = rank
    scored = sum(r["score"] is not None for r in rows)
    warnings = []
    if scorer is None or unavailable:
        warnings.append({
            "code": "scoring_unavailable",
            "message": "The evidence store is not available, so these stocks are listed in curated order without scores.",
            "retryable": True,
        })
    elif scored < len(rows):
        warnings.append({
            "code": "partially_scored",
            "message": f"{len(rows) - scored} of {len(rows)} stocks have no score yet; ingest their evidence to rank them.",
            "retryable": False,
        })
    return {
        "industry": {"slug": slug, "name": name},
        "universe_as_of": UNIVERSE_AS_OF,
        "stocks_per_industry": STOCKS_PER_INDUSTRY,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scoring": {"status": "unavailable" if unavailable and not scored else "available",
                    "scored": scored, "total": len(rows), "horizon": HORIZON, "risk_profile": RISK_PROFILE},
        "ranking_basis": BASIS,
        "stocks": rows,
        "warnings": warnings,
    }


def recommended_stocks(slug: str) -> dict[str, Any]:
    """Cached for a few minutes so a busy frontend does not re-read the store 24 times per view."""
    cached = _cache.get(slug)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    maker = assessment.get_scoring_maker()
    result = rank_industry(slug, make_scorer(maker) if maker is not None else None)
    if result["scoring"]["status"] == "available":  # do not pin an outage in the cache
        _cache[slug] = (time.monotonic(), result)
    return result


def reset() -> None:
    _cache.clear()
