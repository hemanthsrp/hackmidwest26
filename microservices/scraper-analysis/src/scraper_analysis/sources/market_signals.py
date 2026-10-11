"""Minimal quant/market signal adapter, closing the gap flagged against
Jet's docs/api-contract-v0.md (every example response includes a signal,
e.g. "30-day price change"; scraper-analysis had no signal producer yet).

Uses yfinance (free, no signup, already a dependency for the Phase-3
commodities adapter) for a single realized, historical measure -- not a
forward-looking claim, per docs/PROJECT_BRIEF.md."""

from datetime import datetime, timezone

import yfinance as yf

from ..models.signal import Signal
from .base import FetchResult, SourceUnavailableError, load_fixture, resolve

FIXTURE_FILE = "market_signal_sample.json"
WINDOW_DAYS = 30


def fetch_live(symbol: str) -> list[Signal]:
    try:
        history = yf.Ticker(symbol).history(period=f"{WINDOW_DAYS + 5}d")
    except Exception as exc:  # yfinance raises assorted network/parse errors
        raise SourceUnavailableError(str(exc)) from exc

    if history.empty or len(history) < 2:
        raise SourceUnavailableError(f"no price history returned for {symbol}")

    closes = history["Close"].dropna()
    start_price = float(closes.iloc[0])
    end_price = float(closes.iloc[-1])
    if start_price == 0:
        raise SourceUnavailableError("zero starting price, cannot compute percent change")

    pct_change = (end_price - start_price) / start_price * 100
    as_of = closes.index[-1].to_pydatetime().replace(tzinfo=timezone.utc)

    return [
        Signal(
            symbol=symbol.upper(),
            name="30-day price change",
            value=round(pct_change, 4),
            unit="percent",
            window="30d",
            as_of=as_of,
            source="Yahoo Finance (yfinance)",
            data_mode="live",
        )
    ]


def fetch_sample(symbol: str) -> list[Signal]:
    records = load_fixture(FIXTURE_FILE)
    return [
        Signal(
            symbol=symbol.upper(),
            name=r["name"],
            value=r["value"],
            unit=r["unit"],
            window=r["window"],
            as_of=datetime.fromisoformat(r["as_of"].replace("Z", "+00:00")),
            source=r["source"],
            data_mode="sample",
        )
        for r in records
        if r.get("symbol", symbol).upper() == symbol.upper()
    ]


def fetch_result(symbol: str, allow_live: bool = True, fallback: bool = True) -> FetchResult:
    return resolve(lambda: fetch_live(symbol), lambda: fetch_sample(symbol), allow_live, fallback)


def fetch(symbol: str, allow_live: bool = True) -> tuple[list[Signal], str]:
    result = fetch_result(symbol, allow_live)
    return result.items, result.data_mode
