"""Market-signal retrieval for the Yahoo Finance MCP tool.

The service defaults to deterministic sample output. Live retrieval is opt-in,
returns only a realized historical signal, and never substitutes sample data
when Yahoo Finance is unavailable.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import TypedDict

import yfinance as yf

_SYMBOL_PATTERN = re.compile(r"[A-Z]{1,5}")
_WINDOW_DAYS = 30
_SAMPLE_AS_OF = "2026-10-10T20:00:00Z"


class MarketSignal(TypedDict):
    symbol: str
    name: str
    value: float
    unit: str
    window: str
    as_of: str
    retrieved_at: str
    source_name: str
    data_mode: str


class ErrorEnvelope(TypedDict):
    code: str
    message: str
    retryable: bool


class ErrorResponse(TypedDict):
    error: ErrorEnvelope


def get_market_signal(
    symbol: str,
    mode: str = "sample",
    start_date: str | None = None,
    end_date: str | None = None,
) -> MarketSignal | ErrorResponse:
    """Return one labeled 30-day realized price-change signal.

    ``mode='live'`` calls yfinance; any upstream failure is returned as an
    explicit error rather than silently returning fixture content.
    """
    normalized_symbol = symbol.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(normalized_symbol):
        return _error("invalid_symbol", "symbol must contain 1 to 5 uppercase letters", False)
    if mode not in {"sample", "live"}:
        return _error("invalid_mode", "mode must be either sample or live", False)
    date_range_error = _validate_date_range(start_date, end_date)
    if date_range_error:
        return date_range_error
    if mode == "sample":
        if start_date or end_date:
            return _error(
                "unsupported_sample_time_range",
                "sample mode supports only the deterministic 30-day fixture",
                False,
            )
        return _signal(
            symbol=normalized_symbol,
            value=2.4,
            as_of=_SAMPLE_AS_OF,
            retrieved_at=_SAMPLE_AS_OF,
            data_mode="sample",
            window="30d",
        )

    try:
        start_price, end_price, as_of = _fetch_live_prices(normalized_symbol, start_date, end_date)
    except Exception:
        return _error(
            "provider_unavailable",
            "Yahoo Finance data is unavailable; no market signal was generated.",
            True,
        )
    if start_price == 0:
        return _error(
            "provider_unavailable",
            "Yahoo Finance data is unavailable; no market signal was generated.",
            True,
        )
    return _signal(
        symbol=normalized_symbol,
        value=round((end_price - start_price) / start_price * 100, 4),
        as_of=_to_utc_timestamp(as_of),
        retrieved_at=_now_timestamp(),
        data_mode="live",
        window=f"{start_date}..{end_date}" if start_date else "30d",
    )


def _fetch_live_prices(
    symbol: str, start_date: str | None, end_date: str | None
) -> tuple[float, float, datetime]:
    history = (
        yf.Ticker(symbol).history(start=start_date, end=end_date)
        if start_date
        else yf.Ticker(symbol).history(period=f"{_WINDOW_DAYS + 5}d")
    )
    closes = history["Close"].dropna()
    if len(closes) < 2:
        raise RuntimeError("no usable Yahoo Finance price history")
    as_of = closes.index[-1].to_pydatetime()
    return float(closes.iloc[0]), float(closes.iloc[-1]), as_of


def _signal(
    *, symbol: str, value: float, as_of: str, retrieved_at: str, data_mode: str, window: str
) -> MarketSignal:
    return {
        "symbol": symbol,
        "name": "30-day price change",
        "value": value,
        "unit": "percent",
        "window": window,
        "as_of": as_of,
        "retrieved_at": retrieved_at,
        "source_name": "Yahoo Finance via yfinance",
        "data_mode": data_mode,
    }


def _error(code: str, message: str, retryable: bool) -> ErrorResponse:
    return {"error": {"code": code, "message": message, "retryable": retryable}}


def _validate_date_range(start_date: str | None, end_date: str | None) -> ErrorResponse | None:
    if bool(start_date) != bool(end_date):
        return _error("invalid_date_range", "start_date and end_date must be provided together", False)
    if not start_date:
        return None
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        return _error("invalid_date_range", "dates must use ISO YYYY-MM-DD format", False)
    if start >= end:
        return _error("invalid_date_range", "start_date must be earlier than end_date", False)
    return None


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
