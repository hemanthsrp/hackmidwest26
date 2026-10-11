"""The combiner: this is where the final label is decided.

A pure function of the legs and the quant reading, so the same inputs always
give the same label and the rule that produced it can be shown. The Strands
agent explains the result afterwards and has no way to change it.

The weights and thresholds are hand-set heuristics, not fitted or validated.
``net_direction`` (-1 to 1) is the internal quantity for this rule. ``score``
is its display form: a linear 0-100 rescale with 50 neutral. It is a position
on this heuristic's scale, not a probability or a forecast.
"""

from __future__ import annotations

from .models import Decision, Leg, QuantReading

COMBINER_VERSION = "combiner-v1"

WEIGHTS = {"news": 0.4, "insider": 0.3, "price": 0.2, "congress": 0.1}
BASE_THRESHOLD = 0.25
RAISED_THRESHOLD = 0.40
MIN_USABLE_LEGS = 2
# How far a leg must lean to count as pointing one way: for naming a conflict,
# and for an evidence leg to back a buy or sell.
MIN_LEG_DIRECTION = 0.25
EVIDENCE_LEGS = frozenset({"news", "insider", "congress"})
MAX_REASONS_PER_LEG = 5

THRESHOLDS = {
    "weights": WEIGHTS,
    "base_threshold": BASE_THRESHOLD,
    "raised_threshold": RAISED_THRESHOLD,
    "min_usable_legs": MIN_USABLE_LEGS,
    "min_leg_direction": MIN_LEG_DIRECTION,
    "evidence_legs": sorted(EVIDENCE_LEGS),
}


def score_from_net(net: float | None) -> int | None:
    """0-100 display score: 50 is neutral, 100 is every usable leg fully bullish."""
    if net is None:
        return None
    return round(max(0.0, min(100.0, 50.0 + 50.0 * net)))


def _raised_by(legs: dict[str, Leg], quant: QuantReading) -> list[str]:
    """Conditions under which more agreement is needed before leaving ``hold``."""
    reasons: list[str] = []
    if quant.status == "used":  # thin options data is reported but not acted on
        if quant.priced_volatility == "high":
            reasons.append("priced_volatility_high")
        if quant.skew == "steep":
            reasons.append("skew_steep")
        if quant.term_structure == "inverted":
            reasons.append("term_structure_inverted")
    news = legs.get("news")
    if news and news.inputs.get("upcoming_event_ids"):
        reasons.append("upcoming_event_in_news")
    return reasons


def _conflicts(usable: list[Leg]) -> list[str]:
    strong = [leg for leg in usable if abs(leg.direction) >= MIN_LEG_DIRECTION]
    return [
        f"{a.name} ({a.reading}) against {b.name} ({b.reading})"
        for i, a in enumerate(strong)
        for b in strong[i + 1 :]
        if a.direction * b.direction < 0
    ]


_QUANT_BUCKET = {
    "priced_volatility_high": "priced_volatility",
    "skew_steep": "skew",
    "term_structure_inverted": "term_structure",
}


def _reason_codes(label: str, usable: list[Leg], legs: dict[str, Leg], quant: QuantReading, raised_by: list[str]) -> list[str]:
    sign = {"buy": 1.0, "sell": -1.0}.get(label)
    # buy/sell: the legs pointing that way. hold: every usable leg, since the mix is the reason.
    behind = [leg for leg in usable if sign is None or leg.direction * sign > 0]
    codes: list[str] = []
    for leg in behind:
        codes += leg.record_ids[:MAX_REASONS_PER_LEG]
    for reason in raised_by:
        if reason in _QUANT_BUCKET:
            signal_id = quant.signal_ids.get(_QUANT_BUCKET[reason])
            if signal_id:
                codes.append(signal_id)
        elif reason == "upcoming_event_in_news":
            codes += legs["news"].inputs["upcoming_event_ids"][:MAX_REASONS_PER_LEG]
    return list(dict.fromkeys(codes))


def combine(legs: dict[str, Leg], quant: QuantReading, *, has_evidence: bool) -> Decision:
    raised_by = _raised_by(legs, quant)
    threshold = RAISED_THRESHOLD if raised_by else BASE_THRESHOLD
    usable = [leg for leg in legs.values() if leg.usable]
    names = [leg.name for leg in usable]

    if not has_evidence:
        return Decision(
            label="insufficient_data",
            reason_codes=["missing_attributable_evidence"],
            threshold=threshold,
            threshold_raised_by=raised_by,
            usable_legs=names,
        )
    if len(usable) < MIN_USABLE_LEGS:
        return Decision(
            label="insufficient_data",
            reason_codes=["insufficient_direction_signals"],
            threshold=threshold,
            threshold_raised_by=raised_by,
            usable_legs=names,
        )

    total = sum(WEIGHTS[leg.name] for leg in usable)
    net = sum(WEIGHTS[leg.name] * leg.direction for leg in usable) / total
    label = "buy" if net >= threshold else "sell" if net <= -threshold else "hold"

    held_because: list[str] = []
    if label != "hold":
        # A realized price move must not carry a label by itself: at least one kind
        # of attributable evidence has to point the same way.
        sign = 1.0 if label == "buy" else -1.0
        agrees = any(leg.name in EVIDENCE_LEGS and leg.direction * sign >= MIN_LEG_DIRECTION for leg in usable)
        if not agrees:
            label = "hold"
            held_because.append("no_evidence_leg_agrees")
    score = score_from_net(net)
    if label == "hold":
        # A hold must read as a hold: a net direction past the threshold that was held back
        # (or one that rounds onto the line) must not show a buy-looking number.
        score = min(max(score, score_from_net(-threshold) + 1), score_from_net(threshold) - 1)
    return Decision(
        label=label,
        reason_codes=_reason_codes(label, usable, legs, quant, raised_by),
        net_direction=round(net, 4),
        score=score,
        threshold=threshold,
        threshold_raised_by=raised_by,
        held_because=held_because,
        usable_legs=names,
        conflicts=_conflicts(usable),
    )
