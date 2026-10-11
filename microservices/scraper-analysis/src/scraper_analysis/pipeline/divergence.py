"""Cross-source divergence: where independent kinds of evidence disagree.

This is the honest, tractable version of the README's 3.4 "cross-source
anomaly / squeeze engine". The README's version needs a social-volume
z-score over a rolling window. We cannot compute that truthfully: Reddit is
blocked (403), X/Twitter was dropped, and without a scheduler the store has
no history to form a baseline, so a z-score would be invented precision.

What we can do deterministically is compare the *direction* of four
independent legs, each backed by cited records:

  price      30-day price change signal
  insider    discretionary Form 4 open-market flow (10b5-1 plan trades are
             excluded -- they were scheduled months ago and say little about
             current conviction; they are reported in notes instead)
  congress   Senate periodic-transaction purchases vs sales
  news       credibility-weighted tone of Bedrock-tagged news items

and flag the pairs that disagree. Every threshold is a named constant and is
returned in the response. This is a research aid: a flag says "these sources
point different ways", never that a price will move, and it is not a score.
"""

from dataclasses import dataclass, field

from ..models.evidence import Evidence
from ..models.signal import Signal

PRICE_MOVE_PCT = 5.0
INSIDER_NET_USD = 100_000.0
MIN_TAGGED_NEWS = 3
NEWS_TONE_THRESHOLD = 0.25
DEFAULT_CREDIBILITY = 0.5

THRESHOLDS = {
    "price_move_pct": PRICE_MOVE_PCT,
    "insider_net_usd": INSIDER_NET_USD,
    "min_tagged_news": MIN_TAGGED_NEWS,
    "news_tone_threshold": NEWS_TONE_THRESHOLD,
}

@dataclass
class Leg:
    name: str
    direction: str | None  # None = no usable data for this leg
    summary: str
    evidence_ids: list[str] = field(default_factory=list)
    inputs: dict = field(default_factory=dict)


@dataclass
class Flag:
    id: str
    title: str
    description: str
    legs: list[str]
    evidence_ids: list[str]


def _price_leg(signals: list[Signal]) -> Leg:
    candidates = [s for s in signals if s.name == "30-day price change" and s.data_mode != "sample"] or [
        s for s in signals if s.name == "30-day price change"
    ]
    if not candidates:
        return Leg("price", None, "No price signal available.")
    s = max(candidates, key=lambda x: x.as_of)
    if s.value >= PRICE_MOVE_PCT:
        direction = "up"
    elif s.value <= -PRICE_MOVE_PCT:
        direction = "down"
    else:
        direction = "flat"
    return Leg(
        "price", direction, f"{s.value:+.1f}% over {s.window} (as of {s.as_of.date()}).",
        [s.id], {"change_pct": s.value, "as_of": s.as_of.isoformat()},
    )


def _insider_leg(evidence: list[Evidence]) -> tuple[Leg, list[str]]:
    notes: list[str] = []
    form4 = [e for e in evidence if e.source_type == "sec_filing" and "sell_shares" in e.details]
    if not form4:
        return Leg("insider", None, "No parsed Form 4 filings available."), notes

    # Only filings with real open-market buying/selling count: a filing that
    # is purely tax withholding or an option exercise has no direction.
    active = [e for e in form4 if e.details.get("buy_shares") or e.details.get("sell_shares")]
    discretionary = [e for e in active if not e.details.get("is_10b5_1")]
    planned = [e for e in active if e.details.get("is_10b5_1")]
    planned_sell = sum(e.details.get("sell_value_usd", 0.0) for e in planned)
    if planned:
        notes.append(
            f"{len(planned)} pre-scheduled 10b5-1 insider filing(s) (~${planned_sell:,.0f} sold) are excluded "
            "from insider direction: they were decided in advance and carry little current-conviction signal."
        )
    if not discretionary:
        return Leg("insider", "neutral", "No discretionary open-market insider activity (only pre-scheduled 10b5-1 trades, tax withholding or option exercises).",
                   [], {"discretionary_net_usd": 0.0, "planned_sell_usd": planned_sell}), notes

    net = sum(e.details.get("buy_value_usd", 0.0) - e.details.get("sell_value_usd", 0.0) for e in discretionary)
    if net >= INSIDER_NET_USD:
        direction = "buying"
    elif net <= -INSIDER_NET_USD:
        direction = "selling"
    else:
        direction = "neutral"
    ids = [e.id for e in discretionary]
    return Leg(
        "insider", direction,
        f"Discretionary open-market net ${net:+,.0f} across {len(discretionary)} filing(s).",
        ids, {"discretionary_net_usd": net, "planned_sell_usd": planned_sell},
    ), notes


def _congress_leg(evidence: list[Evidence]) -> Leg:
    trades = [e for e in evidence if e.source_type == "congressional_disclosure"]
    buys = [e for e in trades if str(e.details.get("transaction_type", "")).lower().startswith("purchase")]
    sells = [e for e in trades if str(e.details.get("transaction_type", "")).lower().startswith("sale")]
    if not buys and not sells:
        return Leg("congress", None, "No Senate trades in this symbol.")
    if len(buys) > len(sells):
        direction = "buying"
    elif len(sells) > len(buys):
        direction = "selling"
    else:
        direction = "mixed"
    return Leg(
        "congress", direction, f"{len(buys)} purchase(s) vs {len(sells)} sale(s) disclosed (reported with a lag).",
        [e.id for e in buys + sells], {"purchases": len(buys), "sales": len(sells)},
    )


def _news_leg(evidence: list[Evidence]) -> Leg:
    news = [e for e in evidence if e.source_type == "general_news" and e.sentiment.direction and e.sentiment.score is not None]
    if len(news) < MIN_TAGGED_NEWS:
        return Leg("news", None, f"Only {len(news)} sentiment-tagged news item(s); need {MIN_TAGGED_NEWS}.")
    sign = {"Bullish": 1.0, "Bearish": -1.0}
    weighted = total = 0.0
    for e in news:
        w = e.credibility.overall_score if e.credibility.overall_score is not None else DEFAULT_CREDIBILITY
        weighted += sign.get(e.sentiment.direction, 0.0) * e.sentiment.score * w
        total += w
    tone = weighted / total if total else 0.0
    direction = "bullish" if tone >= NEWS_TONE_THRESHOLD else "bearish" if tone <= -NEWS_TONE_THRESHOLD else "neutral"
    return Leg("news", direction, f"Credibility-weighted tone {tone:+.2f} across {len(news)} tagged items.",
               [e.id for e in news], {"tone": round(tone, 3), "items": len(news)})


def _flags(legs: dict[str, Leg]) -> list[Flag]:
    price, insider, congress, news = (legs[k] for k in ("price", "insider", "congress", "news"))
    flags: list[Flag] = []

    def add(fid, title, desc, *involved):
        ids = []
        for leg in involved:
            ids += [i for i in leg.evidence_ids if i not in ids]
        flags.append(Flag(fid, title, desc, [leg.name for leg in involved], ids))

    if price.direction == "up" and insider.direction == "selling":
        add("insiders_selling_into_rally", "Insiders selling into a rally",
            f"Price {price.summary} but discretionary insiders are net sellers: {insider.summary}", price, insider)
    if price.direction == "down" and insider.direction == "buying":
        add("insiders_buying_into_weakness", "Insiders buying into weakness",
            f"Price {price.summary} while discretionary insiders are net buyers: {insider.summary}", price, insider)
    if news.direction == "bullish" and price.direction == "down":
        add("bullish_news_falling_price", "Bullish news, falling price",
            f"News tone is bullish ({news.summary}) but price {price.summary}", news, price)
    if news.direction == "bearish" and price.direction == "up":
        add("bearish_news_rising_price", "Bearish news, rising price",
            f"News tone is bearish ({news.summary}) but price {price.summary}", news, price)
    if congress.direction == "buying" and insider.direction == "selling":
        add("congress_buying_insiders_selling", "Senate buying while insiders sell",
            f"{congress.summary} vs {insider.summary}", congress, insider)
    if congress.direction == "selling" and insider.direction == "buying":
        add("congress_selling_insiders_buying", "Senate selling while insiders buy",
            f"{congress.summary} vs {insider.summary}", congress, insider)
    return flags


def analyze(symbol: str, evidence: list[Evidence], signals: list[Signal]) -> dict:
    """Pure function: same inputs, same output. Callers decide which records
    (live vs sample) to pass in."""
    insider, notes = _insider_leg(evidence)
    legs = {
        "price": _price_leg(signals),
        "insider": insider,
        "congress": _congress_leg(evidence),
        "news": _news_leg(evidence),
    }
    usable = [leg.name for leg in legs.values() if leg.direction is not None]
    unavailable = [f"{leg.name}: {leg.summary}" for leg in legs.values() if leg.direction is None]
    status = "ok" if len(usable) >= 2 else "insufficient_data"
    flags = _flags(legs) if status == "ok" else []
    if status == "ok" and not flags:
        notes.append("No divergence among the available legs: they do not point in opposing directions.")
    return {
        "symbol": symbol,
        "status": status,
        "legs": {name: leg.__dict__ for name, leg in legs.items()},
        "flags": [f.__dict__ for f in flags],
        "notes": notes + [f"Unavailable -- {u}" for u in unavailable],
        "thresholds": THRESHOLDS,
        "disclaimer": "Heuristic comparison of source directions. Not a prediction, score, or recommendation.",
    }
