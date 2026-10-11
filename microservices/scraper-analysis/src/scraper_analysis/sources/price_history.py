"""Daily close history for charting.

Live Yahoo Finance data only. Unlike the signal adapters there is deliberately
no sample fallback: a chart of invented prices is worse than no chart, so a
provider failure surfaces as SourceUnavailableError."""

import math
from datetime import timezone

import yfinance as yf

from .base import SourceUnavailableError

SOURCE = "Yahoo Finance (yfinance)"
# Range label -> yfinance period. Daily bars throughout.
RANGES = {"1W": "7d", "1M": "1mo", "3M": "3mo", "1Y": "1y"}


def fetch_live(symbol: str, range_: str) -> list[dict]:
    period = RANGES.get(range_)
    if period is None:
        raise ValueError(f"range must be one of {', '.join(RANGES)}")
    try:
        history = yf.Ticker(symbol).history(period=period, interval="1d")
    except Exception as exc:  # yfinance raises assorted network/parse errors
        raise SourceUnavailableError(str(exc)) from exc

    if history.empty or "Close" not in history:
        raise SourceUnavailableError(f"no price history returned for {symbol}")

    points = [
        {
            "t": ts.to_pydatetime().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "close": round(float(close), 4),
        }
        for ts, close in history["Close"].dropna().items()
        if math.isfinite(float(close))
    ]
    if len(points) < 2:
        raise SourceUnavailableError(f"insufficient price history for {symbol}")
    return points
