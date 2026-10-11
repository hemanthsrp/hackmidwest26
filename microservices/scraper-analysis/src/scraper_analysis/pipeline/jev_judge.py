"""Optional Jev judgment of news and social evidence, via the shared
``microservices/jev-tool`` package (see its AGENT_GUIDE.md).

Purely additive: when enabled, each judged record gains ``details["jev"]``
(relevance to the symbol, direction, content type, event type, upcoming
event, sensational style, usable content, materiality) and, where another new
record from a different outlet reports the same event, ``same_story_as``.
Nothing else on the record is changed -- ``sentiment`` and ``credibility`` stay
exactly as the tagging agent and scoring left them -- and nothing is filtered
out. (One opt-in exception: JEV_FILL_SENTIMENT fills ``sentiment`` only where
tagging left it empty, and marks that it did.) With JEV_ENABLED unset this is a no-op, the same
graceful degradation as tagging when Bedrock is not configured.

Official filings and congressional disclosures are skipped on purpose: they
are structured, number-heavy records that are parsed deterministically
upstream, and Jev is documented as unreliable with numbers and dates.

These are heuristic model judgments, not validated measures. In particular
none of the values is a probability that a price will move.
"""

import logging

from ..config import get_settings
from ..models.evidence import Evidence, Sentiment
from ..sources.base import sanitize_error
from .scoring import _jaccard, _tokens
from .symbol_match import SYMBOL_NAME_HINTS

logger = logging.getLogger(__name__)

JUDGED_SOURCE_TYPES = frozenset({"general_news", "social_media"})

_JUDGMENT_FIELDS = (
    "relevant",
    "direction",
    "direction_confidence",
    "content_type",
    "content_type_confidence",
    "event_type",
    "event_type_confidence",
    "upcoming_event",
    "sensational",
    "usable_content",
    "materiality",
    "materiality_confidence",
)

# Jev direction -> the tagging agent's vocabulary. "mixed" has no equivalent there.
_SENTIMENT_FROM_DIRECTION = {"positive": "Bullish", "negative": "Bearish", "neutral": "Neutral", "mixed": "Neutral"}
FILL_SENTIMENT_MIN_CONFIDENCE = 0.5

# Same-story candidates: enough word overlap to be worth asking, from different outlets.
SAME_STORY_CANDIDATE_JACCARD = 0.15
SAME_STORY_THRESHOLD = 0.5

_tool = None


def _get_tool():
    """Built lazily so the service imports and runs without jev-tool installed."""
    global _tool
    if _tool is None:
        from jev_tool import JevTool

        settings = get_settings()
        _tool = JevTool(enabled=True, api_key=settings.typesafe_api_key, model=settings.jev_model)
    return _tool


def company_name(symbol: str) -> str:
    """Jev's questions name the company; fall back to the ticker when we have no hint."""
    return SYMBOL_NAME_HINTS.get(symbol.upper(), symbol)


def judge_evidence(items: list[Evidence], tool=None) -> list[Evidence]:
    """Attach ``details["jev"]`` to news/social items. Returns the same list.

    A record Jev could not answer for gets ``{"engine": "unavailable", "error": ...}``
    so the gap is visible downstream rather than looking like a judgment.
    """
    targets = [e for e in items if e.source_type in JUDGED_SOURCE_TYPES]
    if not targets:
        return items
    if tool is None:
        if not get_settings().jev_configured:
            logger.info("jev not enabled; skipping judgment for %d record(s)", len(targets))
            return items
        try:
            tool = _get_tool()
        except ImportError:
            logger.warning("JEV_ENABLED is set but jev-tool is not installed; skipping judgment")
            return items

    payload = [{"id": e.id, "symbol": e.symbol, "title": e.title, "summary": e.summary} for e in targets]
    companies = {e.symbol: company_name(e.symbol) for e in targets}
    try:
        judgments = tool.judge_evidence_items(payload, companies)
    except Exception:
        logger.warning("jev judgment failed; leaving %d record(s) unjudged", len(targets), exc_info=True)
        return items

    for evidence, judgment in zip(targets, judgments):
        if judgment.engine != "jev":
            evidence.details["jev"] = {
                "engine": "unavailable",
                "error": sanitize_error(judgment.error) if judgment.error else None,
            }
            continue
        evidence.details["jev"] = {
            "engine": "jev",
            "model": judgment.model,
            "question_set_version": judgment.question_set_version,
            "request_id": judgment.request_id,
            **{name: getattr(judgment, name) for name in _JUDGMENT_FIELDS},
        }
        _fill_sentiment(evidence, judgment)
    _mark_same_story([e for e in targets if e.details.get("jev", {}).get("engine") == "jev"], tool)
    return items


def _fill_sentiment(evidence: Evidence, judgment) -> None:
    """Opt-in: only where tagging left sentiment empty, and never over an existing value."""
    if not get_settings().jev_fill_sentiment or evidence.sentiment.direction is not None:
        return
    confidence = judgment.direction_confidence or 0.0
    if confidence < FILL_SENTIMENT_MIN_CONFIDENCE:
        return
    evidence.sentiment = Sentiment(
        direction=_SENTIMENT_FROM_DIRECTION[judgment.direction], score=round(confidence, 4)
    )
    evidence.details["jev"]["filled_sentiment"] = True


def _mark_same_story(judged: list[Evidence], tool) -> None:
    """Record which other new records (different outlet) report the same event.
    Marks only; deduplication and corroboration scoring are left as they are."""
    tokens = [_tokens(f"{e.title} {e.summary or ''}") for e in judged]
    pairs = [
        (i, j)
        for i in range(len(judged))
        for j in range(i + 1, len(judged))
        if judged[i].source_name != judged[j].source_name
        and _jaccard(tokens[i], tokens[j]) >= SAME_STORY_CANDIDATE_JACCARD
    ]
    if not pairs:
        return
    try:
        result = tool.same_story([{"title": e.title, "summary": e.summary} for e in judged], pairs)
    except Exception:
        logger.warning("jev same-story check failed; skipping", exc_info=True)
        return
    if result.engine != "jev":
        return
    for pair in result.pairs:
        if pair.same >= SAME_STORY_THRESHOLD:
            a, b = judged[pair.a], judged[pair.b]
            a.details["jev"].setdefault("same_story_as", []).append(b.id)
            b.details["jev"].setdefault("same_story_as", []).append(a.id)
