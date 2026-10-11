"""Evidence grading: one stored, explainable strength per record, computed at
ingestion right after the optional Jev judgment (``pipeline/jev_judge.py``).

Why: a per-symbol news feed returns many items that only mention the company
or are not about it at all, and the tagging agent still gives those a
sentiment. Nothing is deleted or hidden here. Each graded record gains
``details["grade"]`` so every downstream reader -- the briefing agent, the
research API, a query on the store -- can see how much weight it deserves and
whether it is off-topic for the symbol.

    strength = relevance x credibility x content_type x materiality
               x direction_confidence x hype x same_story

Every factor and the weights behind it are stored next to the result. All
weights are hand-set heuristics, not fitted or validated; ``strength`` ranks
how much attention a record deserves. It is NOT a probability and says nothing
about where a price will go.

Records Jev did not judge (official filings, congressional disclosures, or
anything ingested while Jev was unavailable) are graded on source credibility
alone and marked ``basis: "source_only"``; they are never gated.

Freshness is deliberately not stored, because it changes by the hour:
``current_strength()`` applies it at read time. Grading only runs when Jev is
enabled, so with JEV_ENABLED unset records are unchanged.
"""

from datetime import UTC, datetime

from ..config import get_settings
from ..models.evidence import Evidence
from .jev_judge import request_enabled

GRADE_VERSION = "grade-v1"

CONTENT_TYPE_WEIGHT = {
    "news_report": 1.0,
    "company_announcement": 0.8,
    "opinion_or_analysis": 0.6,
    "social_media_post": 0.4,
    "other": 0.3,
}
DEFAULT_CREDIBILITY = 0.5
USABLE_CONTENT_GATE = 0.5
HYPE_THRESHOLD = 0.8  # the flag is too eager below this (see the live-run notes in INTEGRATION.md)
HYPE_WEIGHT = 0.7
SAME_STORY_BONUS_PER_OUTLET = 0.1
SAME_STORY_BONUS_CAP = 3
FRESHNESS_HALF_LIFE_HOURS = 72.0

TONE_VALUE = {"positive": 1.0, "negative": -1.0, "neutral": 0.0, "mixed": 0.0}
TONE_THRESHOLD = 0.25
TONE_MIN_STORIES = 3


def _jev(evidence: Evidence) -> dict | None:
    judgment = evidence.details.get("jev")
    return judgment if judgment and judgment.get("engine") == "jev" else None


def grade_record(evidence: Evidence, relevance_gate: float) -> dict:
    credibility = evidence.credibility.overall_score
    credibility = DEFAULT_CREDIBILITY if credibility is None else credibility
    judgment = _jev(evidence)
    if judgment is None:
        return {
            "version": GRADE_VERSION,
            "basis": "source_only",
            "strength": round(credibility, 4),
            "gated": False,
            "gate_reasons": [],
            "factors": {"credibility": credibility},
        }

    same_story = len(judgment.get("same_story_as", []))
    factors = {
        "relevance": judgment["relevant"],
        "credibility": credibility,
        "content_type": CONTENT_TYPE_WEIGHT.get(judgment["content_type"], CONTENT_TYPE_WEIGHT["other"]),
        "materiality": 0.4 + 0.3 * judgment["materiality"],  # 0 -> 0.4, 1 -> 0.7, 2 -> 1.0
        "direction_confidence": 0.5 + 0.5 * (judgment["direction_confidence"] or 0.0),
        "hype": HYPE_WEIGHT if judgment["sensational"] >= HYPE_THRESHOLD else 1.0,
        "same_story": 1.0 + SAME_STORY_BONUS_PER_OUTLET * min(same_story, SAME_STORY_BONUS_CAP),
    }
    strength = 1.0
    for value in factors.values():
        strength *= value
    reasons = []
    if judgment["relevant"] < relevance_gate:
        reasons.append("off_topic")
    if judgment["usable_content"] < USABLE_CONTENT_GATE:
        reasons.append("unusable_content")
    return {
        "version": GRADE_VERSION,
        "basis": "jev",
        "strength": round(min(1.0, strength), 4),
        "gated": bool(reasons),
        "gate_reasons": reasons,
        "relevance_gate": relevance_gate,
        "factors": {name: round(value, 4) for name, value in factors.items()},
    }


def grade_evidence(items: list[Evidence]) -> list[Evidence]:
    """Attach ``details["grade"]`` to every record. A no-op unless Jev is enabled."""
    settings = get_settings()
    if not request_enabled() or not settings.jev_configured:
        return items
    for evidence in items:
        evidence.details["grade"] = grade_record(evidence, settings.jev_relevance_gate)
    return items


def is_gated(evidence: Evidence) -> bool:
    """True when the record was graded as off-topic or unusable for its symbol.
    Ungraded records are never gated."""
    return bool(evidence.details.get("grade", {}).get("gated"))


def agent_view(evidence: Evidence) -> dict:
    """The few fields an LLM reader should see first, surfaced at the top level of a
    tool row. Empty for ungraded records, so rows are unchanged when Jev is off."""
    grade = evidence.details.get("grade")
    if not grade:
        return {}
    judgment = _jev(evidence)
    view = {"strength": grade["strength"], "off_topic_for_symbol": "off_topic" in grade["gate_reasons"]}
    if judgment:
        view["relevance_to_symbol"] = judgment["relevant"]
    return view


def _event_time(evidence: Evidence) -> datetime:
    when = evidence.published_at or evidence.observed_at or evidence.retrieved_at
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def freshness(evidence: Evidence, as_of: datetime | None = None) -> float:
    """1.0 for something published now, halving every FRESHNESS_HALF_LIFE_HOURS."""
    as_of = as_of or datetime.now(UTC)
    age_hours = max(0.0, (as_of - _event_time(evidence)).total_seconds() / 3600)
    return 0.5 ** (age_hours / FRESHNESS_HALF_LIFE_HOURS)


def current_strength(evidence: Evidence, as_of: datetime | None = None) -> float | None:
    """Stored strength with freshness applied. None for ungraded records."""
    grade = evidence.details.get("grade")
    if not grade:
        return None
    return round(grade["strength"] * freshness(evidence, as_of), 4)


def rank(items: list[Evidence], as_of: datetime | None = None) -> list[Evidence]:
    """Strongest first. Ungraded records keep their order after the graded ones."""
    return sorted(items, key=lambda e: current_strength(e, as_of) or -1.0, reverse=True)


def news_tone(items: list[Evidence], as_of: datetime | None = None) -> dict:
    """Strength-weighted direction of the on-topic, Jev-judged records.

    Gated (off-topic or unusable) records are excluded, and records Jev linked as
    the same story count once, at the strongest one's weight -- so one event
    repeated by several outlets, or a pile of unrelated feed items, cannot swing
    it. A heuristic summary of reported tone, never a forecast.
    """
    judged = [e for e in items if _jev(e) and "grade" in e.details]
    usable = [e for e in judged if not is_gated(e)]
    by_id = {e.id: e for e in usable}
    seen: set[str] = set()
    stories: list[Evidence] = []
    for evidence in sorted(usable, key=lambda e: current_strength(e, as_of) or 0.0, reverse=True):
        if evidence.id in seen:
            continue
        seen.add(evidence.id)
        seen.update(i for i in evidence.details["jev"].get("same_story_as", []) if i in by_id)
        stories.append(evidence)

    total = sum(current_strength(e, as_of) or 0.0 for e in stories)
    result = {
        "version": GRADE_VERSION,
        "records_judged": len(judged),
        "records_gated": len(judged) - len(usable),
        "stories_used": len(stories),
        "by_direction": {},
        "tone": None,
        "label": "insufficient_data",
        "thresholds": {"tone": TONE_THRESHOLD, "min_stories": TONE_MIN_STORIES},
        "evidence_ids": [e.id for e in stories],
    }
    for evidence in stories:
        direction = evidence.details["jev"]["direction"]
        result["by_direction"][direction] = result["by_direction"].get(direction, 0) + 1
    if len(stories) < TONE_MIN_STORIES or total <= 0:
        return result
    tone = sum(TONE_VALUE[e.details["jev"]["direction"]] * (current_strength(e, as_of) or 0.0) for e in stories) / total
    result["tone"] = round(tone, 4)
    result["label"] = "positive" if tone >= TONE_THRESHOLD else "negative" if tone <= -TONE_THRESHOLD else "mixed_or_neutral"
    return result
