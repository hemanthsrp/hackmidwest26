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
  congress   congressional (Senate/House) periodic-transaction purchases vs sales
  news       credibility-weighted tone of Bedrock-tagged news items

and flag the pairs that disagree. Every threshold is a named constant and is
returned in the response.

Input hygiene, applied inside analyze() so no caller can bypass it:

  * live only -- only records with data_mode "live" are compared. "sample"
    (fixtures) and "cached" records are dropped before any leg is computed
    and counted in excluded.sample / excluded.cached, so neither can
    contribute to a flag, even when nothing live exists (status is then
    insufficient_data). Callers should pass the raw stored records so these
    counts are complete;
  * request time -- `as_of` (default: now) is the moment the analysis is
    for. It may never be in the future: an as_of more than
    CLOCK_SKEW_TOLERANCE_HOURS after the actual current time raises
    FutureAsOfError (the endpoint answers 400). A past as_of is allowed for
    reproducible/back-dated analysis but is always labelled
    window.historical = true with a warning, so historical flags are never
    presented as current;
  * nothing from the future -- one ceiling, min(request time, actual clock)
    + CLOCK_SKEW_TOLERANCE_HOURS (the tolerance applies once, never stacked
    on an as_of that was itself accepted inside it). Any record (price
    signal or evidence) whose event date OR published_at is after it is
    unusable: counted in excluded.future_dated, warned about, never compared;
  * fresh price -- the price leg is the latest live, not-future price
    signal, usable only if its as_of is at most MAX_PRICE_SIGNAL_AGE_DAYS
    before the request time. A stale price leaves the leg unusable, is
    counted in excluded.stale_price and warned about, and never anchors the
    window -- old data is never presented as a current flag;
  * recency -- every evidence record must fall inside the comparison window.
    With a fresh price it is the price signal's own change window
    (`window`, e.g. "30d"; RECENCY_LOOKBACK_DAYS if unparseable) ending at
    its as_of, so every flag pairs the price move with evidence from the
    period that move covers; otherwise it is RECENCY_LOOKBACK_DAYS before
    the request time. RECENCY_FORWARD_GRACE_DAYS after the end absorbs the
    close being stamped at midnight of the session date, but the window
    never extends past that same ceiling. The event date is
    observed_at (Form 4 / congressional trade date) falling back to
    published_at for other sources (news). Congressional records use the
    trade date only -- never the filing date -- and any record whose parser
    set details.date_issue (e.g. a House trade dated after its filing) is
    excluded as invalid_date. Congressional disclosures are filed up to 45
    days after the trade; we still window on the trade date, because that is
    when the member acted, and accept that the congress leg will often be
    empty (a false negative is preferred to pairing a months-old trade with
    today's price move). Undated evidence cannot be placed in the window and
    is dropped;
  * insider -- only discretionary open-market P/S counts. A filing that is
    a 10b5-1 plan trade, tax withholding (F), an option exercise (M), a
    grant, etc. leaves the insider leg unusable (direction None). One Form 4
    can cover trades on several days, so only the trades dated inside the
    window are valued: with the per-transaction breakdown
    (details.transactions) out-of-window trades are dropped (counted in
    excluded.out_of_window_transactions); a legacy record without the
    breakdown is valued at its totals only if every details.transaction_date
    is inside the window, otherwise it is excluded from the insider leg
    (excluded.partially_out_of_window) -- out-of-window trades are never
    valued.

Every exclusion is counted in `excluded` and explained in `warnings`. This is a research aid: a flag says "these sources
point different ways", never that a price will move, and it is not a score.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..models.evidence import Evidence
from ..models.signal import Signal

PRICE_MOVE_PCT = 5.0
INSIDER_NET_USD = 100_000.0
MIN_TAGGED_NEWS = 3
NEWS_TONE_THRESHOLD = 0.25
DEFAULT_CREDIBILITY = 0.5
# Lookback when the price signal's window cannot be used (no fresh price, or
# an unparseable `window`): matches the 30-day price change signal, so the
# evidence never covers a longer period than the price move it is paired with.
RECENCY_LOOKBACK_DAYS = 30
# Daily closes are stamped at midnight of the session date, so evidence from
# that same day is up to one day "after" as_of; nothing later counts.
RECENCY_FORWARD_GRACE_DAYS = 1
# A price signal older than this (relative to the request time) is stale:
# a weekly ingest plus weekends/holidays fits; a 2010 close never does.
MAX_PRICE_SIGNAL_AGE_DAYS = 7
# Tolerated clock difference between our clock and a source's timestamps.
# Anything dated later than this after the request time (or a request time
# this far after the actual clock) is future-dated and never used.
CLOCK_SKEW_TOLERANCE_HOURS = 1

THRESHOLDS = {
    "price_move_pct": PRICE_MOVE_PCT,
    "insider_net_usd": INSIDER_NET_USD,
    "min_tagged_news": MIN_TAGGED_NEWS,
    "news_tone_threshold": NEWS_TONE_THRESHOLD,
    "recency_lookback_days": RECENCY_LOOKBACK_DAYS,
    "recency_forward_grace_days": RECENCY_FORWARD_GRACE_DAYS,
    "max_price_signal_age_days": MAX_PRICE_SIGNAL_AGE_DAYS,
    "clock_skew_tolerance_hours": CLOCK_SKEW_TOLERANCE_HOURS,
}

PRICE_SIGNAL = "30-day price change"
_SKEW = timedelta(hours=CLOCK_SKEW_TOLERANCE_HOURS)


class FutureAsOfError(ValueError):
    """The requested as_of is after the actual current time."""


def _clock() -> datetime:
    return datetime.now(timezone.utc)


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


def _utc(t: datetime) -> datetime:
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


def _window_days(window: str) -> int:
    """'30d' -> 30; anything else falls back to RECENCY_LOOKBACK_DAYS."""
    w = (window or "").strip().lower()
    if w.endswith("d") and w[:-1].isdigit() and int(w[:-1]) > 0:
        return int(w[:-1])
    return RECENCY_LOOKBACK_DAYS


def _price_leg(signals: list[Signal], now: datetime, ceiling: datetime | None = None) -> tuple[Leg, Signal | None, int, int]:
    """Latest live price signal, if fresh relative to the request time `now`.
    Returns the leg, the chosen signal (the latest not-future one, also when
    stale, so its age can be reported), and the numbers of live price
    signals rejected as stale and as future-dated (after `ceiling`, which
    defaults to now + skew; analyze() passes min(now, real clock) + skew so
    the tolerance never stacks on a caller-supplied as_of)."""
    live = [s for s in signals if s.name == PRICE_SIGNAL and s.data_mode == "live"]
    if not live:
        return Leg("price", None, "No live price signal available."), None, 0, 0
    latest_ok = ceiling if ceiling is not None else now + _SKEW
    oldest_ok = now - timedelta(days=MAX_PRICE_SIGNAL_AGE_DAYS)
    past = [s for s in live if _utc(s.as_of) <= latest_ok]
    future = len(live) - len(past)
    fresh = [s for s in past if oldest_ok <= _utc(s.as_of)]
    stale = len(past) - len(fresh)
    if not fresh:
        if not past:
            return Leg("price", None, "Every live price signal is dated after the request time (future-dated); "
                       "not compared."), None, stale, future
        s = max(past, key=lambda x: _utc(x.as_of))
        return Leg("price", None, f"Latest live price signal is stale (as of {_utc(s.as_of).date()}, more than "
                   f"{MAX_PRICE_SIGNAL_AGE_DAYS} days before the request); not compared.",
                   [], {"as_of": _utc(s.as_of).isoformat()}), s, stale, future
    s = max(fresh, key=lambda x: _utc(x.as_of))
    if s.value >= PRICE_MOVE_PCT:
        direction = "up"
    elif s.value <= -PRICE_MOVE_PCT:
        direction = "down"
    else:
        direction = "flat"
    return Leg(
        "price", direction, f"{s.value:+.1f}% over {s.window} (as of {_utc(s.as_of).date()}).",
        [s.id], {"change_pct": s.value, "as_of": _utc(s.as_of).isoformat(), "window": s.window},
    ), s, stale, future


@dataclass
class _Form4Row:
    """A Form 4 filing as valued inside the window."""
    evidence: Evidence
    buy_usd: float
    sell_usd: float

    @property
    def active(self) -> bool:
        return bool(self.buy_usd or self.sell_usd)


def _is_form4(e: Evidence) -> bool:
    return e.source_type == "sec_filing" and "sell_shares" in e.details


def _tx_time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _in(t: datetime | None, start: datetime, end: datetime) -> bool:
    return t is not None and start <= t <= end


def _insider_leg(rows: list) -> tuple[Leg, list[str]]:
    """`rows` are windowed _Form4Row values; bare Evidence is accepted and
    valued at its totals (the caller has already windowed it)."""
    notes: list[str] = []
    form4 = [r if isinstance(r, _Form4Row) else
             _Form4Row(r, float(r.details.get("buy_value_usd") or 0.0), float(r.details.get("sell_value_usd") or 0.0))
             for r in rows if isinstance(r, _Form4Row) or _is_form4(r)]
    if not form4:
        return Leg("insider", None, "No parsed Form 4 filings available."), notes

    # Only filings with real open-market buying/selling (inside the window)
    # count: a filing that is purely tax withholding or an option exercise
    # has no direction.
    active = [r for r in form4 if r.active]
    discretionary = [r for r in active if not r.evidence.details.get("is_10b5_1")]
    planned = [r for r in active if r.evidence.details.get("is_10b5_1")]
    planned_sell = sum(r.sell_usd for r in planned)
    if planned:
        notes.append(
            f"{len(planned)} pre-scheduled 10b5-1 insider filing(s) (~${planned_sell:,.0f} sold) are excluded "
            "from insider direction: they were decided in advance and carry little current-conviction signal."
        )
    if not discretionary:
        # Excluded activity must not make the leg usable: no direction at all.
        return Leg("insider", None, "No discretionary open-market insider activity in the window (only pre-scheduled "
                   "10b5-1 trades, tax withholding, option exercises or grants).",
                   [], {"discretionary_net_usd": 0.0, "planned_sell_usd": planned_sell}), notes

    net = sum(r.buy_usd - r.sell_usd for r in discretionary)
    if net >= INSIDER_NET_USD:
        direction = "buying"
    elif net <= -INSIDER_NET_USD:
        direction = "selling"
    else:
        direction = "neutral"
    ids = [r.evidence.id for r in discretionary]
    return Leg(
        "insider", direction,
        f"Discretionary open-market net ${net:+,.0f} across {len(discretionary)} filing(s) "
        "(trades inside the window only).",
        ids, {"discretionary_net_usd": net, "planned_sell_usd": planned_sell},
    ), notes


def _congress_leg(evidence: list[Evidence]) -> Leg:
    trades = [e for e in evidence if e.source_type == "congressional_disclosure"]
    buys = [e for e in trades if str(e.details.get("transaction_type", "")).lower().startswith("purchase")]
    sells = [e for e in trades if str(e.details.get("transaction_type", "")).lower().startswith("sale")]
    if not buys and not sells:
        return Leg("congress", None, "No dated congressional (Senate or House) trades in this symbol in the window.")
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
        add("congress_buying_insiders_selling", "Members of Congress buying while insiders sell",
            f"{congress.summary} vs {insider.summary}", congress, insider)
    if congress.direction == "selling" and insider.direction == "buying":
        add("congress_selling_insiders_buying", "Members of Congress selling while insiders buy",
            f"{congress.summary} vs {insider.summary}", congress, insider)
    return flags


def _event_time(e: Evidence) -> datetime | None:
    # Congressional rows: the trade date only. The filing date (published_at)
    # can be up to 45 days later and must never stand in for an invalid or
    # missing trade date.
    if e.source_type == "congressional_disclosure":
        t = e.observed_at
    else:
        t = e.observed_at or e.published_at
    return _utc(t) if t is not None else None


def _value_form4(e: Evidence, start: datetime, end: datetime) -> tuple[_Form4Row | None, str]:
    """Value a Form 4 by its in-window trades only. Returns (row, outcome);
    outcome is "ok", "out_of_window" (nothing in the window) or
    "partially_out_of_window" (legacy record that cannot be split)."""
    txs = e.details.get("transactions")
    if isinstance(txs, list):
        inside = [x for x in txs if isinstance(x, dict) and _in(_tx_time(x.get("date")), start, end)]
        if txs and not inside:
            return None, "out_of_window"
        if not txs and not _in(_event_time(e), start, end):
            return None, "out_of_window"
        buy = sum(float(x.get("value_usd") or 0.0) for x in inside if x.get("code") == "P")
        sell = sum(float(x.get("value_usd") or 0.0) for x in inside if x.get("code") == "S")
        return _Form4Row(e, buy, sell), "ok"
    # Legacy record: totals only, placed by observed_at (earliest trade date).
    if not _in(_event_time(e), start, end):
        return None, "out_of_window"
    dates = e.details.get("transaction_dates") or []
    if any(not _in(_tx_time(dt), start, end) for dt in dates):
        return None, "partially_out_of_window"
    return _Form4Row(e, float(e.details.get("buy_value_usd") or 0.0),
                     float(e.details.get("sell_value_usd") or 0.0)), "ok"


def analyze(symbol: str, evidence: list[Evidence], signals: list[Signal], as_of: datetime | None = None) -> dict:
    """Deterministic for fixed inputs when `as_of` (the request time) is
    passed; defaults to now. `as_of` must not be in the future (raises
    FutureAsOfError); a past `as_of` is labelled window.historical. Non-live,
    future-dated, stale and out-of-window records are dropped here, whatever
    the caller passes in -- pass the raw stored records so the `excluded`
    counts are complete."""
    warnings: list[str] = []
    clock = _clock()
    now = _utc(as_of) if as_of is not None else clock
    if now > clock + _SKEW:
        raise FutureAsOfError(f"as_of {now.isoformat()} is in the future (current time {clock.isoformat()}); "
                              "divergence can only be computed for the present or the past.")
    historical = now < clock - _SKEW
    # One ceiling for everything: nothing dated (or published) after the
    # request time OR the actual clock, plus a single skew allowance. Using
    # now + skew alone let an as_of accepted inside the tolerance add a second
    # hour on top of the real clock.
    ceiling = min(now, clock) + _SKEW
    if historical:
        warnings.append(f"Historical analysis as of {now.isoformat()}: the requested as_of is in the past, so these "
                        "legs and flags describe that date, not the present.")
    records = [*evidence, *signals]
    sample_count = sum(1 for i in records if i.data_mode == "sample")
    cached_count = sum(1 for i in records if i.data_mode == "cached")
    live_evidence = [e for e in evidence if e.data_mode == "live"]
    live_signals = [s for s in signals if s.data_mode == "live"]
    if sample_count:
        if not live_evidence and not live_signals:
            warnings.append(f"Only sample (fixture) data is stored ({sample_count} record(s)); fixtures never "
                            "contribute to divergence flags.")
        else:
            warnings.append(f"{sample_count} sample (fixture) record(s) ignored; only live data is compared.")
    if cached_count:
        warnings.append(f"{cached_count} cached record(s) ignored; only live data is compared.")

    price, price_signal, stale_price, future_price = _price_leg(live_signals, now, ceiling)
    price_age_days = None
    if price_signal is not None:
        price_age_days = round((now - _utc(price_signal.as_of)).total_seconds() / 86400, 2)
    if future_price:
        warnings.append(f"{future_price} live price signal(s) are dated after the request time (future-dated, "
                        f"beyond the {CLOCK_SKEW_TOLERANCE_HOURS}h clock-skew tolerance) and were not used.")
    if price.direction is not None:
        end_anchor = _utc(price_signal.as_of)
        lookback = _window_days(price_signal.window)
    else:
        end_anchor = now
        lookback = RECENCY_LOOKBACK_DAYS
        if price_signal is not None:
            warnings.append(f"Price signal is stale (as of {_utc(price_signal.as_of).date()}, "
                            f"{price_age_days:g} day(s) before the request; limit {MAX_PRICE_SIGNAL_AGE_DAYS}); "
                            "the price leg is not compared and the window is anchored on the request time.")
    start = end_anchor - timedelta(days=lookback)
    # Never past the request time (+ skew): nothing from its future counts.
    end = min(end_anchor + timedelta(days=RECENCY_FORWARD_GRACE_DAYS), ceiling)

    in_window: list[Evidence] = []
    form4_rows: list[_Form4Row] = []
    out_of_window = undated = invalid_date = future_dated = partial = trimmed_tx = 0
    for e in live_evidence:
        if e.details.get("date_issue"):
            invalid_date += 1
            continue
        t = _event_time(e)
        published = _utc(e.published_at) if e.published_at else None
        if t is None:
            undated += 1
        elif t > ceiling or (published is not None and published > ceiling):
            # Event dated in the future, or not even published yet: never compared.
            future_dated += 1
        elif _is_form4(e):
            row, outcome = _value_form4(e, start, end)
            if outcome == "out_of_window":
                out_of_window += 1
            elif outcome == "partially_out_of_window":
                partial += 1
            else:
                form4_rows.append(row)
                txs = e.details.get("transactions")
                if isinstance(txs, list):
                    trimmed_tx += sum(1 for x in txs if not (isinstance(x, dict)
                                                             and _in(_tx_time(x.get("date")), start, end)))
        elif start <= t <= end:
            in_window.append(e)
        else:
            out_of_window += 1
    if future_dated:
        warnings.append(f"{future_dated} live record(s) are dated after the request time (future-dated, beyond the "
                        f"{CLOCK_SKEW_TOLERANCE_HOURS}h clock-skew tolerance) and were not counted.")
    if out_of_window:
        warnings.append(f"{out_of_window} live record(s) fall outside the comparison window "
                        f"({start.date()} to {end.date()}) and were not counted.")
    if partial:
        warnings.append(f"{partial} Form 4 filing(s) without a per-transaction breakdown have trades partially "
                        "outside the comparison window; they were excluded from the insider leg rather than valued "
                        "in full.")
    if trimmed_tx:
        warnings.append(f"{trimmed_tx} Form 4 transaction(s) dated outside the comparison window were not valued "
                        "(only the in-window trades of multi-day filings count).")
    if undated:
        warnings.append(f"{undated} live record(s) have no usable event date (trade date for congressional "
                        "records, else observed/published date) and were not counted.")
    if invalid_date:
        warnings.append(f"{invalid_date} live record(s) have an invalid date (details.date_issue) and were not "
                        "counted.")

    insider, notes = _insider_leg(form4_rows)
    legs = {
        "price": price,
        "insider": insider,
        "congress": _congress_leg(in_window),
        "news": _news_leg(in_window),
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
        "warnings": warnings,
        "excluded": {"sample": sample_count, "cached": cached_count, "stale_price": stale_price,
                     "future_dated": future_price + future_dated, "out_of_window": out_of_window,
                     "partially_out_of_window": partial, "out_of_window_transactions": trimmed_tx,
                     "undated": undated, "invalid_date": invalid_date},
        "window": {
            "request_time": now.isoformat(),
            "historical": historical,
            "anchor": end_anchor.isoformat(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "lookback_days": lookback,
            "forward_grace_days": RECENCY_FORWARD_GRACE_DAYS,
            "clock_skew_tolerance_hours": CLOCK_SKEW_TOLERANCE_HOURS,
            "price_as_of": _utc(price_signal.as_of).isoformat() if price_signal is not None else None,
            "price_age_days": price_age_days,
            "max_price_age_days": MAX_PRICE_SIGNAL_AGE_DAYS,
        },
        "data_modes": ["live"] if live_evidence or live_signals else [],
        "thresholds": THRESHOLDS,
        "disclaimer": "Heuristic comparison of source directions. Not a prediction, score, or recommendation.",
    }
