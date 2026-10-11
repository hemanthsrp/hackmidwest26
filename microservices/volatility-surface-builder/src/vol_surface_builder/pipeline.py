"""Transport-independent option volatility diagnostics.

Synthetic SPY output is a reproducible visualization fixture. Live output uses
option quotes when explicitly selected and never falls back to synthetic data.
Neither path produces a stock-price forecast or buy/hold/sell label.
"""

from datetime import datetime, timezone
import math

from . import config
from .data_feed import get_option_data
from .surface_builder import build_surface, compute_surface_statistics


class UnsupportedSampleSymbol(ValueError):
    """The synthetic model is calibrated only for SPY-like illustration."""


def _finite_or_none(value: object) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def build_snapshot(
    symbol: str,
    mode: str = "sample",
    spot: float = 602.0,
    grid_strikes: int = 24,
    grid_maturities: int = 16,
) -> dict:
    symbol = symbol.strip().upper()
    if mode not in {"sample", "live"}:
        raise ValueError("mode must be sample or live")
    if mode == "sample" and symbol != "SPY":
        raise UnsupportedSampleSymbol("Synthetic sample data is calibrated for SPY only.")
    if not math.isfinite(spot) or spot <= 0:
        raise ValueError("spot must be a positive finite number")

    try:
        frame, actual_spot = get_option_data(
            source="synthetic" if mode == "sample" else "live",
            ticker=symbol,
            spot=spot,
        )
    except Exception as exc:
        if mode == "live":
            raise RuntimeError("Live option provider unavailable") from exc
        raise
    statistics = compute_surface_statistics(frame, actual_spot)
    strikes, maturities, _, _, iv_grid = build_surface(
        frame, n_k=grid_strikes, n_t=grid_maturities
    )
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "symbol": symbol,
        "data_mode": mode,
        "source": "synthetic SPY illustration" if mode == "sample" else "Yahoo Finance option chain",
        "retrieved_at": retrieved_at,
        "market_observed_at": None,
        "spot": float(actual_spot),
        "pricing_assumptions": {
            "risk_free_rate_decimal": config.RISK_FREE_RATE,
            "dividend_yield_decimal": config.DIVIDEND_YIELD,
        },
        "statistics": {
            "n_points": int(statistics["n_points"]),
            "n_expiries": int(statistics["n_expiries"]),
            "strike_range": [float(v) for v in statistics["strike_range"]],
            "maturity_range_years": [float(v) for v in statistics["T_range"]],
            "iv_range_decimal": [float(v) for v in statistics["iv_range"]],
            "atm_iv_decimal": _finite_or_none(statistics["atm_iv_mean"]),
            "skew_25d_proxy_decimal": _finite_or_none(statistics["skew_25d_proxy"]),
        },
        "surface": {
            "strike": strikes.tolist(),
            "maturity_years": maturities.tolist(),
            "iv_decimal": iv_grid.tolist(),
        },
        "interpretation": "Option-implied volatility diagnostic; not a stock-price forecast or investment assessment.",
    }
