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
import math
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from ..config import get_settings
from ..models.evidence import Evidence, Sentiment
from ..sources.base import describe_exception, sanitize_error
from .scoring import _jaccard, _tokens
from .symbol_match import SYMBOL_NAME_HINTS

logger = logging.getLogger(__name__)

JUDGED_SOURCE_TYPES = frozenset({"general_news", "social_media"})

# grade.py multiplies/compares these, so a judgment is only stored as a real one
# when all are present numbers. (direction and the confidences may legitimately be
# empty, e.g. for an off-topic item, and every reader tolerates that.)
REQUIRED_NUMERIC_FIELDS = ("relevant", "sensational", "usable_content", "materiality")

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
_STRING_FIELDS = frozenset({"direction", "content_type", "event_type"})
_META_FIELDS = ("model", "question_set_version", "request_id")

# Valid range of each numeric field; anything else (NaN, +-inf, out of range, a string,
# a bool) is treated as missing. materiality is a score over three levels, so 0..2.
FIELD_RANGES = {"materiality": (0.0, 2.0)}  # every other numeric field: 0..1

# details["jev"]["status"]: every record sent for judgment says what came back.
STATUS_OK = "ok"  # a validated judgment (engine "jev")
STATUS_UNAVAILABLE = "unavailable"  # the tool answered "unavailable" for this record
STATUS_MALFORMED = "malformed"  # a result came back but failed validation
STATUS_MISSING = "missing"  # sent, but no result came back for this record
STATUS_FAILED = "failed"  # the whole call raised

# Jev direction -> the tagging agent's vocabulary. "mixed" has no equivalent there.
_SENTIMENT_FROM_DIRECTION = {"positive": "Bullish", "negative": "Bearish", "neutral": "Neutral", "mixed": "Neutral"}
FILL_SENTIMENT_MIN_CONFIDENCE = 0.5

# Same-story candidates: enough word overlap to be worth asking, from different outlets.
SAME_STORY_CANDIDATE_JACCARD = 0.15
SAME_STORY_THRESHOLD = 0.5

_tool = None

# Per-request switch (the `judge` flag on /ingest/run), kept out of the ingest
# function signatures so this feature does not widen them.
_request_enabled: ContextVar[bool] = ContextVar("jev_request_enabled", default=True)


@contextmanager
def for_request(enabled: bool):
    """Turn the Jev step off (or leave it on) for the ingestion run inside this block."""
    token = _request_enabled.set(enabled)
    try:
        yield
    finally:
        _request_enabled.reset(token)


def request_enabled() -> bool:
    return _request_enabled.get()


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

    Every record sent gets a ``status``: ``ok`` (a validated judgment), or
    ``{"engine": "unavailable", "status": "unavailable" | "malformed" | "missing" |
    "failed", "error": ...}`` so the gap is visible downstream rather than looking like
    a judgment or like a record that was never sent. Results are matched to records by
    ``evidence_id`` and validated one by one; one bad result never stops the others, and
    nothing here raises into the ingest.
    """
    targets = [e for e in items if e.source_type in JUDGED_SOURCE_TYPES]
    if not targets or not request_enabled():
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
        judgments = list(tool.judge_evidence_items(payload, companies))
    except Exception as exc:
        # Sent but nothing came back: mark it, so "Jev failed" never looks like "never judged".
        # Never exc_info: the raw exception/traceback can carry the API key or a tokened URL.
        logger.warning("jev judgment failed for %d record(s): %s", len(targets), describe_exception(exc))
        for evidence in targets:
            evidence.details["jev"] = _unavailable(STATUS_FAILED, "jev call failed")
        return items

    for evidence, result in _match_results(targets, judgments):
        # Each record on its own: one bad result can never stop the others being attached.
        try:
            evidence.details["jev"] = _read_result(result)
        except Exception as exc:
            logger.warning("unreadable jev result for %s; marking it malformed: %s", evidence.id,
                           describe_exception(exc))
            evidence.details["jev"] = _unavailable(STATUS_MALFORMED, "unreadable judgment")
            continue
        if evidence.details["jev"]["engine"] == "jev":
            try:
                _fill_sentiment(evidence)
            except Exception as exc:
                logger.warning("jev sentiment fill failed for %s; skipping: %s", evidence.id, describe_exception(exc))
    for evidence in targets:
        if "jev" not in evidence.details:
            evidence.details["jev"] = _unavailable(STATUS_MISSING, "no judgment returned for this record")

    try:
        _mark_same_story([e for e in targets if e.details["jev"]["engine"] == "jev"], tool)
    except Exception as exc:
        # Optional and additive: whatever went wrong, the records still get stored.
        logger.warning("jev same-story marking failed; keeping records as they are: %s", describe_exception(exc))
    return items


def _unavailable(status: str, error: str | None) -> dict:
    return {"engine": "unavailable", "status": status, "error": error}


def _field(result, name):
    """Read one field from a result object (jev-tool's pydantic model) or a plain mapping."""
    if isinstance(result, Mapping):
        return result.get(name)
    return getattr(result, name, None)


def _is_result(result) -> bool:
    return isinstance(result, Mapping) or hasattr(result, "engine")


def _match_results(targets: list[Evidence], results: list) -> list[tuple[Evidence, object]]:
    """Pair each result with the record it is about, by ``evidence_id`` only.

    jev-tool always echoes the payload ``id`` back as ``evidence_id`` (and we always send
    one), so there is no positional fallback: a list that is short, reordered, or mixes
    identified and unidentified results would otherwise hand a judgment to the wrong
    record. A result with no id, an id that is not a non-empty string, an id we did not
    send, or a second result for an already-matched record is dropped (and counted);
    the record it might have belonged to is then marked ``missing``.
    """
    by_id = {e.id: e for e in targets}
    matched: dict[str, tuple[Evidence, object]] = {}
    dropped = 0
    for index, result in enumerate(results):
        try:
            key = _field(result, "evidence_id") if _is_result(result) else None
        except Exception as exc:
            logger.warning("could not read evidence_id from jev result %d: %s", index, describe_exception(exc))
            key = None
        if not isinstance(key, str) or key not in by_id:
            dropped += 1
            continue
        if key in matched:
            logger.warning("duplicate jev result for %s; keeping the first", key)
            dropped += 1
            continue
        matched[key] = (by_id[key], result)
    if dropped:
        logger.warning(
            "dropped %d jev result(s) without a usable evidence_id (none, invalid, not sent, or duplicate)", dropped
        )
    return list(matched.values())


def _read_result(result) -> dict:
    """Validate one result at the boundary and build what gets stored.

    jev-tool types every field ``float | None`` and nothing here trusts that further:
    the fields grading multiplies must be finite numbers in range or the judgment is
    stored as malformed; any other invalid value is stored as missing (None) and named
    in ``invalid_fields``. Never a NaN, an infinity or a string in a number's place.
    """
    if not _is_result(result):
        return _unavailable(STATUS_MALFORMED, f"not a judgment ({type(result).__name__})")
    engine = _field(result, "engine")
    if engine != "jev":
        if engine != "unavailable":
            return _unavailable(STATUS_MALFORMED, "judgment has no valid engine")
        error = _field(result, "error")
        return _unavailable(STATUS_UNAVAILABLE, sanitize_error(error) if error else None)
    bad = [name for name in REQUIRED_NUMERIC_FIELDS if _number(_field(result, name), name) is None]
    if bad:
        # Grading multiplies these, so a half-filled judgment must not be stored as a real one.
        return _unavailable(
            STATUS_MALFORMED, f"incomplete judgment (missing, non-numeric or out of range: {', '.join(bad)})"
        )
    stored = {"engine": "jev", "status": STATUS_OK}
    for name in _META_FIELDS:
        value = _field(result, name)
        stored[name] = value if value is None or isinstance(value, str) else str(value)
    invalid = []
    for name in _JUDGMENT_FIELDS:
        raw = _field(result, name)
        value = _string(raw) if name in _STRING_FIELDS else _number(raw, name)
        if value is None and raw is not None:
            invalid.append(name)
        stored[name] = value
    if invalid:
        stored["invalid_fields"] = invalid
    return stored


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value, name: str) -> float | None:
    """The value when it is a finite number inside the field's range, otherwise None."""
    if not _is_number(value):
        return None
    low, high = FIELD_RANGES.get(name, (0.0, 1.0))
    return value if low <= value <= high else None


def _string(value) -> str | None:
    return value if isinstance(value, str) else None


def valid_judgment(judgment) -> bool:
    """True for a stored judgment grading can use as one: engine "jev" and every
    number it multiplies or compares finite and in range. Re-checked at read time
    because records written by older code were never validated. ``same_story_as`` is
    not part of this check: a malformed link list is ignored (see same_story_ids), it
    never discards an otherwise valid judgment."""
    if not isinstance(judgment, Mapping) or judgment.get("engine") != "jev":
        return False
    if any(_number(judgment.get(name), name) is None for name in REQUIRED_NUMERIC_FIELDS):
        return False
    confidence = judgment.get("direction_confidence")
    if confidence is not None and _number(confidence, "direction_confidence") is None:
        return False
    return all(_string(judgment.get(name)) is not None or judgment.get(name) is None for name in _STRING_FIELDS)


def same_story_ids(judgment, self_id: str | None = None, known_ids=None) -> list[str]:
    """The usable ids in a judgment's ``same_story_as``: non-empty strings only, without
    the record itself, without duplicates, and (when ``known_ids`` is given) only ids in
    that set. Anything else -- not a list, None, numbers, nested lists, dicts -- is
    ignored, so a malformed stored link list can never raise in a reader."""
    if not isinstance(judgment, Mapping):
        return []
    raw = judgment.get("same_story_as")
    if not isinstance(raw, (list, tuple)):
        return []
    ids: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value or value == self_id or value in ids:
            continue
        if known_ids is not None and value not in known_ids:
            continue
        ids.append(value)
    return ids


def _fill_sentiment(evidence: Evidence) -> None:
    """Opt-in, and only when the tagging agent cannot run at all (Bedrock not configured):
    this step runs before tagging, so it must not write a value the tagger would replace.
    Never overwrites an existing value."""
    settings = get_settings()
    if not settings.jev_fill_sentiment or settings.bedrock_configured:
        return
    if evidence.sentiment.direction is not None:
        return
    judgment = evidence.details["jev"]  # already validated by _read_result
    confidence = judgment["direction_confidence"] or 0.0
    if confidence < FILL_SENTIMENT_MIN_CONFIDENCE:
        return
    mapped = _SENTIMENT_FROM_DIRECTION.get(judgment["direction"])
    if mapped is None:  # no direction (or one we don't know): leave sentiment empty rather than guess
        return
    evidence.sentiment = Sentiment(direction=mapped, score=round(confidence, 4))
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
    except Exception as exc:
        logger.warning("jev same-story check failed; skipping: %s", describe_exception(exc))
        return
    if _field(result, "engine") != "jev":
        return
    asked = set(pairs)
    for pair in _field(result, "pairs") or []:
        # Per pair, like the judgments: one bad pair must not drop the rest.
        try:
            a, b, same = _field(pair, "a"), _field(pair, "b"), _field(pair, "same")
            if (a, b) not in asked or not _is_number(same) or same < SAME_STORY_THRESHOLD:
                continue
            first, second = judged[a], judged[b]
            if first.id == second.id:
                continue
            _link(first, second.id)
            _link(second, first.id)
        except Exception as exc:
            logger.warning("skipping an unreadable same-story pair: %s", describe_exception(exc))



def _link(evidence: Evidence, other_id: str) -> None:
    """Add one same-story link, written already sanitised: a list of distinct string ids."""
    links = same_story_ids(evidence.details["jev"], self_id=evidence.id)
    if other_id not in links:
        links.append(other_id)
    evidence.details["jev"]["same_story_as"] = links
