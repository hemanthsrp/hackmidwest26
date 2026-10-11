"""Safe, source-labeled Yahoo Finance retrieval for the project MCP server."""

from __future__ import annotations

import math
import os
import re
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf

_SYMBOL_PATTERN = re.compile(r"[A-Z]{1,5}")
_DEFAULT_WINDOW_DAYS = 30
_MAX_RANGE_DAYS = 3650
_SAMPLE_AS_OF = "2026-10-10T20:00:00Z"
_INTERVALS = {"daily": "1d", "weekly": "1wk", "monthly": "1mo", "1d": "1d", "1wk": "1wk", "1mo": "1mo"}
_PRICE_COLUMNS = {"close": "Close", "adjusted_close": "Adj Close"}


def get_market_signal(
    symbol: str,
    mode: str = "sample",
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str = "daily",
    price_field: str = "close",
    include_volume: bool = False,
    include_realized_volatility: bool = False,
    include_corporate_actions: bool = False,
) -> dict[str, Any]:
    """Return labeled realized market metrics; live mode never falls back to samples."""
    normalized_symbol = symbol.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(normalized_symbol):
        return _error("invalid_symbol", "symbol must contain 1 to 5 uppercase letters", False)
    if mode not in {"sample", "live"}:
        return _error("invalid_mode", "mode must be either sample or live", False)
    normalized_interval = _INTERVALS.get(interval)
    if not normalized_interval:
        return _error("invalid_interval", "interval must be daily, weekly, or monthly", False)
    price_column = _PRICE_COLUMNS.get(price_field)
    if not price_column:
        return _error("invalid_price_field", "price_field must be close or adjusted_close", False)
    range_result = _validate_date_range(start_date, end_date)
    if isinstance(range_result, dict):
        return range_result
    start, end = range_result
    if start and (end - start).days > _MAX_RANGE_DAYS:
        return _error("range_too_large", "requested date range exceeds the 3650-day limit", False)
    if mode == "sample":
        if start_date or end_date:
            return _error(
                "unsupported_sample_time_range",
                "sample mode supports only the deterministic 30-day fixture",
                False,
            )
        if interval != "daily" or price_field != "close" or any(
            [include_volume, include_realized_volatility, include_corporate_actions]
        ):
            return _error(
                "unsupported_sample_filter",
                "sample mode supports only the deterministic daily 30-day close fixture",
                False,
            )
        return _sample_signal(normalized_symbol)

    try:
        history = _fetch_live_history(normalized_symbol, start_date, end_date, normalized_interval)
        return _live_signal(
            normalized_symbol,
            history,
            price_column,
            price_field,
            normalized_interval,
            start_date,
            end_date,
            include_volume,
            include_realized_volatility,
            include_corporate_actions,
        )
    except Exception:
        return _error(
            "provider_unavailable",
            "Yahoo Finance data is unavailable; no market signal was generated.",
            True,
        )


def get_company_fundamentals(symbol: str, mode: str = "live") -> dict[str, Any]:
    """Return a narrow live fundamentals record only after source-policy approval."""
    normalized_symbol = symbol.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(normalized_symbol):
        return _error("invalid_symbol", "symbol must contain 1 to 5 uppercase letters", False)
    if mode != "live":
        return _error("invalid_mode", "company fundamentals are available only in live mode", False)
    if os.getenv("YAHOO_FINANCE_FUNDAMENTALS_ENABLED", "false").lower() != "true":
        return _error(
            "source_policy_not_approved",
            "company fundamentals are disabled pending source-policy approval",
            False,
        )
    try:
        info = yf.Ticker(normalized_symbol).info
        return {
            "symbol": normalized_symbol,
            "data_mode": "live",
            "source_name": "Yahoo Finance via yfinance",
            "retrieved_at": _now_timestamp(),
            "fundamentals": {
                key: info.get(key)
                for key in ("marketCap", "trailingPE", "forwardPE", "dividendYield", "sector", "industry")
                if info.get(key) is not None
            },
        }
    except Exception:
        return _error("provider_unavailable", "Yahoo Finance fundamentals are unavailable.", True)


def _fetch_live_history(symbol: str, start_date: str | None, end_date: str | None, interval: str) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    if start_date:
        return ticker.history(start=start_date, end=end_date, interval=interval, auto_adjust=False, actions=True)
    return ticker.history(period=f"{_DEFAULT_WINDOW_DAYS + 5}d", interval=interval, auto_adjust=False, actions=True)


def _live_signal(
    symbol: str,
    history: pd.DataFrame,
    price_column: str,
    price_field: str,
    interval: str,
    start_date: str | None,
    end_date: str | None,
    include_volume: bool,
    include_realized_volatility: bool,
    include_corporate_actions: bool,
) -> dict[str, Any]:
    if history.empty or price_column not in history:
        raise RuntimeError("no usable Yahoo Finance price history")
    prices = history[price_column].dropna()
    if len(prices) < 2 or float(prices.iloc[0]) == 0:
        raise RuntimeError("insufficient price history")
    as_of = _to_utc_timestamp(prices.index[-1].to_pydatetime())
    result: dict[str, Any] = {
        "symbol": symbol,
        "name": "realized price change",
        "value": round((float(prices.iloc[-1]) - float(prices.iloc[0])) / float(prices.iloc[0]) * 100, 4),
        "unit": "percent",
        "window": f"{start_date}..{end_date}" if start_date else "30d",
        "as_of": as_of,
        "retrieved_at": _now_timestamp(),
        "source_name": "Yahoo Finance via yfinance",
        "data_mode": "live",
        "interval": interval,
        "price_field": price_field,
    }
    if include_volume:
        result["average_volume"] = int(history["Volume"].dropna().mean()) if "Volume" in history else None
    if include_realized_volatility:
        returns = prices.pct_change().dropna()
        annualization = {"1d": 252, "1wk": 52, "1mo": 12}[interval]
        result["realized_volatility_annualized"] = (
            round(float(returns.std(ddof=1)) * math.sqrt(annualization) * 100, 4) if len(returns) > 1 else None
        )
    if include_corporate_actions:
        dividends = history["Dividends"].fillna(0) if "Dividends" in history else pd.Series(dtype=float)
        splits = history["Stock Splits"].fillna(0) if "Stock Splits" in history else pd.Series(dtype=float)
        result["dividends_total"] = round(float(dividends.sum()), 4)
        result["stock_split_events"] = int((splits != 0).sum())
    return result


def _sample_signal(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "name": "30-day price change",
        "value": 2.4,
        "unit": "percent",
        "window": "30d",
        "as_of": _SAMPLE_AS_OF,
        "retrieved_at": _SAMPLE_AS_OF,
        "source_name": "Yahoo Finance via yfinance",
        "data_mode": "sample",
        "interval": "1d",
        "price_field": "close",
    }


def _validate_date_range(start_date: str | None, end_date: str | None) -> tuple[date | None, date | None] | dict[str, Any]:
    if bool(start_date) != bool(end_date):
        return _error("invalid_date_range", "start_date and end_date must be provided together", False)
    if not start_date:
        return None, None
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        return _error("invalid_date_range", "dates must use ISO YYYY-MM-DD format", False)
    if start >= end:
        return _error("invalid_date_range", "start_date must be earlier than end_date", False)
    return start, end


def _error(code: str, message: str, retryable: bool) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "retryable": retryable}}


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
