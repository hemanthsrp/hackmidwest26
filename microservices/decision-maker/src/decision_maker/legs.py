"""Direction legs: four independent readings of which way the evidence points.

  news      strength-weighted tone of on-topic, Jev-judged news and social items
  insider   discretionary Form 4 open-market flow (10b5-1 plan trades excluded)
  congress  Senate purchases against sales
  price     the realized 30-day price change

The news rule is a port of ``news_tone`` and the grade formula in
``scraper-analysis/pipeline/grade.py`` (this package reads that service's store
but does not import it). The insider, congress and price rules use the same
thresholds as ``scraper-analysis/pipeline/divergence.py``. Everything here is a
hand-set heuristic: a leg says what a kind of evidence reports, never that a
price will move.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Any

from .models import EvidenceRecord, Leg, SignalRecord, as_utc

NEWS_SOURCE_TYPES = frozenset({"general_news", "social_media"})

RECENCY_LOOKBACK_DAYS = 45
RECENCY_FORWARD_GRACE_DAYS = 3

RELEVANCE_GATE = 0.3
USABLE_CONTENT_GATE = 0.5
UPCOMING_EVENT_FLAG = 0.5
FRESHNESS_HALF_LIFE_HOURS = 72.0
TONE_THRESHOLD = 0.25
TONE_MIN_STORIES = 3
TONE_VALUE = {"positive": 1.0, "negative": -1.0, "neutral": 0.0, "mixed": 0.0}

# grade-v1 weights, as in scraper-analysis/pipeline/grade.py.
CONTENT_TYPE_WEIGHT = {
    "news_report": 1.0,
    "company_announcement": 0.8,
    "opinion_or_analysis": 0.6,
    "social_media_post": 0.4,
    "other": 0.3,
}
DEFAULT_CREDIBILITY = 0.5
HYPE_THRESHOLD = 0.8
HYPE_WEIGHT = 0.7
SAME_STORY_BONUS_PER_OUTLET = 0.1
SAME_STORY_BONUS_CAP = 3

# A news record Jev never judged can count only through a usable local NLP reading
# (nlp.py), at this fraction of the weight: the reader is less accurate than Jev and
# knows nothing of materiality or content type. Its strength is
# credibility x NLP_STORY_WEIGHT x reading confidence.
NLP_STORY_WEIGHT = 0.35
# Two NLP-only stories whose headlines share this much vocabulary are one story.
NLP_SAME_STORY_JACCARD = 0.5
# News confidence reaches full coverage at this many stories (multi-agent-investment uses 10).
FULL_COVERAGE_STORIES = 10

PRICE_SIGNAL = "30-day price change"
PRICE_MOVE_PCT = 5.0
INSIDER_NET_USD = 100_000.0

THRESHOLDS = {
    "recency_lookback_days": RECENCY_LOOKBACK_DAYS,
    "relevance_gate": RELEVANCE_GATE,
    "usable_content_gate": USABLE_CONTENT_GATE,
    "upcoming_event_flag": UPCOMING_EVENT_FLAG,
    "freshness_half_life_hours": FRESHNESS_HALF_LIFE_HOURS,
    "news_tone_threshold": TONE_THRESHOLD,
    "news_min_stories": TONE_MIN_STORIES,
    "nlp_story_weight": NLP_STORY_WEIGHT,
    "news_full_coverage_stories": FULL_COVERAGE_STORIES,
    "price_move_pct": PRICE_MOVE_PCT,
    "insider_net_usd": INSIDER_NET_USD,
}


def in_window(evidence: list[EvidenceRecord], as_of: datetime) -> tuple[list[EvidenceRecord], dict[str, int]]:
    """Records whose event falls inside the recency window around ``as_of``.
    An undated record cannot be placed in the window and is left out."""
    earliest = as_of - timedelta(days=RECENCY_LOOKBACK_DAYS)
    latest = as_of + timedelta(days=RECENCY_FORWARD_GRACE_DAYS)
    kept: list[EvidenceRecord] = []
    excluded = {"undated": 0, "outside_window": 0}
    for record in evidence:
        when = record.event_time
        if when is None:
            excluded["undated"] += 1
        elif earliest <= when <= latest:
            kept.append(record)
        else:
            excluded["outside_window"] += 1
    return kept, excluded


def current_grade(record: EvidenceRecord) -> dict | None:
    """The stored grade, only while it was built from the judgment the record holds now.

    A record moves unjudged -> judged, and the scraper grades it at one of those stages.
    A grade from an earlier stage is stale: a ``source_only`` grade (Jev was unavailable
    at ingest) once the record has been judged at decision time, or a Jev grade whose
    ``judged_by`` names a different judgment. Then None, and readers regrade from the
    judgment. Grades stored before ``judged_by`` existed are taken as matching."""
    grade = record.grade
    if not grade:
        return None
    judgment = record.jev
    if grade.get("basis") == "jev":
        if not judgment:
            return None
        if "judged_by" in grade and grade["judged_by"] != judgment.get("request_id"):
            return None
        return grade
    return None if judgment else grade


def is_gated(record: EvidenceRecord) -> bool:
    """Off-topic for the symbol, or not real content. Unjudged records are never gated."""
    grade = current_grade(record)
    if grade and "gated" in grade:
        return bool(grade["gated"])
    judgment = record.jev
    if not judgment:
        return False
    usable_content = judgment.get("usable_content")
    off_topic = (judgment.get("relevant") or 0.0) < RELEVANCE_GATE
    return off_topic or (usable_content is not None and usable_content < USABLE_CONTENT_GATE)


def nlp_reading(record: EvidenceRecord) -> dict | None:
    """The local NLP reading (nlp.py), only when it is usable and Jev has not judged
    the record: a Jev judgment always wins."""
    reading = record.details.get("nlp")
    if record.jev or not isinstance(reading, dict) or reading.get("engine") != "nlp" or not reading.get("usable"):
        return None
    return reading if reading.get("direction") in TONE_VALUE else None


def story_direction(record: EvidenceRecord) -> str | None:
    """The direction a story votes with: Jev's, else a usable NLP reading's."""
    if record.jev:
        return record.jev.get("direction")
    reading = nlp_reading(record)
    return reading["direction"] if reading else None


def strength(record: EvidenceRecord) -> float | None:
    """How much weight a judged record deserves, before freshness. The stored
    grade when the scraper computed one, otherwise the same formula applied to
    the judgment. A record Jev has not judged is weighed by its usable NLP
    reading, if any; otherwise None."""
    grade = current_grade(record)
    if grade and grade.get("basis") == "jev" and grade.get("strength") is not None:
        return float(grade["strength"])
    judgment = record.jev
    if not judgment:
        reading = nlp_reading(record)
        if reading is None:
            return None
        credibility = record.credibility_score
        credibility = DEFAULT_CREDIBILITY if credibility is None else credibility
        return min(1.0, credibility * NLP_STORY_WEIGHT * float(reading.get("confidence") or 0.0))
    credibility = record.credibility_score
    credibility = DEFAULT_CREDIBILITY if credibility is None else credibility
    value = (
        (judgment.get("relevant") or 0.0)
        * credibility
        * CONTENT_TYPE_WEIGHT.get(judgment.get("content_type"), CONTENT_TYPE_WEIGHT["other"])
        * (0.4 + 0.3 * (judgment.get("materiality") or 0.0))
        * (0.5 + 0.5 * (judgment.get("direction_confidence") or 0.0))
        * (HYPE_WEIGHT if (judgment.get("sensational") or 0.0) >= HYPE_THRESHOLD else 1.0)
        * (1.0 + SAME_STORY_BONUS_PER_OUTLET * min(len(judgment.get("same_story_as", [])), SAME_STORY_BONUS_CAP))
    )
    return min(1.0, value)


def freshness(record: EvidenceRecord, as_of: datetime) -> float:
    when = as_utc(record.published_at or record.observed_at or record.retrieved_at)
    age_hours = max(0.0, (as_of - when).total_seconds() / 3600)
    return 0.5 ** (age_hours / FRESHNESS_HALF_LIFE_HOURS)


def current_strength(record: EvidenceRecord, as_of: datetime) -> float:
    return (strength(record) or 0.0) * freshness(record, as_of)


def _headline_tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 2}


def _same_headline(a: set[str], b: set[str]) -> bool:
    return bool(a and b) and len(a & b) / len(a | b) >= NLP_SAME_STORY_JACCARD


def _cross_check(judged: list[EvidenceRecord]) -> dict[str, Any] | None:
    """How often a usable NLP reading agrees with Jev on the records both read.
    Reported only: it never changes a Jev-judged record's weight."""
    pairs = [
        (e, e.jev.get("direction"), e.details["nlp"]["direction"])
        for e in judged
        if isinstance(e.details.get("nlp"), dict) and e.details["nlp"].get("usable") and e.jev.get("direction")
    ]
    if not pairs:
        return None
    # The NLP reader has no "mixed" label; it reads a mixed story as neutral.
    disagree = [e.id for e, jev, nlp in pairs if ("neutral" if jev == "mixed" else jev) != nlp]
    return {"compared": len(pairs), "agreed": len(pairs) - len(disagree), "disagreed_ids": disagree}


def _confidence(stories: list[EvidenceRecord], tone: float, as_of: datetime) -> dict[str, float]:
    """How much to trust the tone, after the sentiment aggregator in
    flash131307/multi-agent-investment: |tone| x agreement x coverage, where agreement
    is 1 minus the strength-weighted spread of the stories' directions and coverage
    reaches 1 at FULL_COVERAGE_STORIES stories. A hand-set heuristic, not a probability."""
    weights = [current_strength(e, as_of) for e in stories]
    values = [TONE_VALUE.get(story_direction(e), 0.0) for e in stories]
    total = sum(weights)
    spread = math.sqrt(sum(w * (v - tone) ** 2 for w, v in zip(weights, values)) / total) if total > 0 else 0.0
    agreement = 1.0 - min(1.0, spread)
    coverage = min(1.0, len(stories) / FULL_COVERAGE_STORIES)
    return {
        "agreement": round(agreement, 4),
        "coverage": round(coverage, 4),
        "confidence": round(abs(tone) * agreement * coverage, 4),
    }


def news_leg(evidence: list[EvidenceRecord], as_of: datetime) -> Leg:
    news = [e for e in evidence if e.source_type in NEWS_SOURCE_TYPES]
    judged = [e for e in news if e.jev]
    usable = [e for e in judged if not is_gated(e)]
    nlp_only = [e for e in news if nlp_reading(e)]
    by_id = {e.id: e for e in usable}

    seen: set[str] = set()
    stories: list[EvidenceRecord] = []
    for record in sorted(usable, key=lambda e: current_strength(e, as_of), reverse=True):
        if record.id in seen:
            continue
        seen.add(record.id)
        seen.update(i for i in record.jev.get("same_story_as", []) if i in by_id)
        stories.append(record)
    # NLP-only stories after the Jev ones, skipping any headline that repeats one already used.
    used_headlines = [_headline_tokens(e.title) for e in stories]
    nlp_stories: list[EvidenceRecord] = []
    for record in sorted(nlp_only, key=lambda e: current_strength(e, as_of), reverse=True):
        tokens = _headline_tokens(record.title)
        if any(_same_headline(tokens, other) for other in used_headlines):
            continue
        used_headlines.append(tokens)
        nlp_stories.append(record)
    stories += nlp_stories

    by_direction: dict[str, int] = {}
    for record in stories:
        direction = story_direction(record) or "neutral"
        by_direction[direction] = by_direction.get(direction, 0) + 1
    upcoming = [e.id for e in usable if (e.jev.get("upcoming_event") or 0.0) >= UPCOMING_EVENT_FLAG]
    inputs = {
        "records": len(news),
        "records_judged": len(judged),
        "records_gated": len(judged) - len(usable),
        "records_unjudged": len(news) - len(judged),
        "stories_used": len(stories),
        "by_direction": by_direction,
        "upcoming_event_ids": upcoming,
        "tone": None,
    }
    if any(isinstance(e.details.get("nlp"), dict) for e in news):
        inputs["records_read_by_nlp_only"] = len(nlp_only)
        inputs["stories_by_reader"] = {"jev": len(stories) - len(nlp_stories), "nlp": len(nlp_stories)}
        inputs["nlp_story_ids"] = [e.id for e in nlp_stories]
        # The NLP reader may add to a news reading, never create one: without enough
        # Jev-judged stories of its own, the leg cannot back a label (combiner.py).
        inputs["backs_label"] = len(stories) - len(nlp_stories) >= TONE_MIN_STORIES
        cross_check = _cross_check(usable)
        if cross_check:
            inputs["nlp_cross_check"] = cross_check

    total = sum(current_strength(e, as_of) for e in stories)
    if len(stories) < TONE_MIN_STORIES or total <= 0:
        return Leg(
            name="news",
            summary=f"Only {len(stories)} on-topic judged news story(ies); need {TONE_MIN_STORIES}.",
            inputs=inputs,
        )
    tone = sum(TONE_VALUE.get(story_direction(e), 0.0) * current_strength(e, as_of) for e in stories) / total
    inputs["tone"] = round(tone, 4)
    inputs.update(_confidence(stories, tone, as_of))
    reading = "positive" if tone >= TONE_THRESHOLD else "negative" if tone <= -TONE_THRESHOLD else "mixed_or_neutral"
    counts = ", ".join(f"{n} {name}" for name, n in sorted(by_direction.items()))
    read_by = f"; {len(nlp_stories)} read only by the local NLP model" if nlp_stories else ""
    return Leg(
        name="news",
        direction=round(tone, 4),
        reading=reading,
        summary=f"Reported tone across {len(stories)} on-topic news story(ies) is {reading.replace('_', ' ')} "
        f"({counts}{read_by}).",
        record_ids=[e.id for e in stories],
        inputs=inputs,
    )


def insider_leg(evidence: list[EvidenceRecord]) -> Leg:
    form4 = [e for e in evidence if e.source_type == "sec_filing" and "sell_shares" in e.details]
    if not form4:
        return Leg(name="insider", summary="No parsed Form 4 filings in the window.")
    # A filing that is only tax withholding or an option exercise has no direction.
    active = [e for e in form4 if e.details.get("buy_shares") or e.details.get("sell_shares")]
    planned = [e for e in active if e.details.get("is_10b5_1")]
    discretionary = [e for e in active if not e.details.get("is_10b5_1")]
    inputs = {
        "filings": len(form4),
        "pre_scheduled_filings": len(planned),
        "pre_scheduled_sell_usd": round(sum(e.details.get("sell_value_usd") or 0.0 for e in planned), 2),
    }
    if not discretionary:
        return Leg(
            name="insider",
            summary="No discretionary open-market insider trades in the window "
            "(only pre-scheduled 10b5-1 trades, tax withholding, option exercises or grants).",
            inputs=inputs,
        )
    net = sum((e.details.get("buy_value_usd") or 0.0) - (e.details.get("sell_value_usd") or 0.0) for e in discretionary)
    inputs["discretionary_net_usd"] = round(net, 2)
    direction, reading = (1.0, "buying") if net >= INSIDER_NET_USD else (-1.0, "selling") if net <= -INSIDER_NET_USD else (0.0, "neutral")
    return Leg(
        name="insider",
        direction=direction,
        reading=reading,
        summary=f"Discretionary open-market insider trades net {'-' if net < 0 else '+'}${abs(net):,.0f} "
        f"across {len(discretionary)} filing(s).",
        record_ids=[e.id for e in discretionary],
        inputs=inputs,
    )


def congress_leg(evidence: list[EvidenceRecord]) -> Leg:
    trades = [e for e in evidence if e.source_type == "congressional_disclosure"]
    kinds = [(e, str(e.details.get("transaction_type", "")).lower()) for e in trades]
    buys = [e for e, kind in kinds if kind.startswith("purchase")]
    sells = [e for e, kind in kinds if kind.startswith("sale")]
    if not buys and not sells:
        return Leg(name="congress", summary="No congressional trades in this symbol in the window.")
    direction, reading = (1.0, "buying") if len(buys) > len(sells) else (-1.0, "selling") if len(sells) > len(buys) else (0.0, "mixed")
    return Leg(
        name="congress",
        direction=direction,
        reading=reading,
        summary=f"{len(buys)} congressional purchase(s) against {len(sells)} sale(s), disclosed with a lag.",
        record_ids=[e.id for e in buys + sells],
        inputs={"purchases": len(buys), "sales": len(sells)},
    )


def price_leg(signals: list[SignalRecord]) -> Leg:
    candidates = [s for s in signals if s.name == PRICE_SIGNAL]
    if not candidates:
        return Leg(name="price", summary="No price-change signal available.")
    signal = max(candidates, key=lambda s: as_utc(s.as_of))
    direction, reading = (1.0, "up") if signal.value >= PRICE_MOVE_PCT else (-1.0, "down") if signal.value <= -PRICE_MOVE_PCT else (0.0, "flat")
    return Leg(
        name="price",
        direction=direction,
        reading=reading,
        summary=f"Price changed {signal.value:+.1f}% over {signal.window} (as of {as_utc(signal.as_of).date()}).",
        record_ids=[signal.id],
        inputs={"change_pct": signal.value, "as_of": as_utc(signal.as_of).isoformat()},
    )


def build_legs(evidence: list[EvidenceRecord], signals: list[SignalRecord], as_of: datetime) -> dict[str, Leg]:
    """``evidence`` must already be limited to the recency window."""
    return {
        "news": news_leg(evidence, as_of),
        "insider": insider_leg(evidence),
        "price": price_leg(signals),
        "congress": congress_leg(evidence),
    }
