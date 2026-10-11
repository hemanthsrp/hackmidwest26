"""The options math for assessments: a client for ``microservices/volatility-surface-builder``.

That service owns the calculation. This module asks it for one symbol's surface
over HTTP and hands the decision maker the statistics in the shape it reads
(``decision_maker.VolSurfaceSnapshot``). The surface is an options-risk
diagnostic: the decision maker uses it for uncertainty, never for direction.

A failure here is raised, so the assessment is still produced and says the math
failed for that request. Nothing is substituted.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

SURFACE_PATH = "/v0/volatility-surfaces"
# A live surface means fetching option chains and inverting each quote to an
# implied volatility, which takes a while.
TIMEOUT_SECONDS = 30.0


class VolSurfaceUnavailable(RuntimeError):
    """The volatility service did not return a surface."""


def _atm_by_expiry(surface: Mapping[str, Any], spot: float) -> list[dict[str, float]]:
    """At-the-money implied volatility per maturity, read off the service's
    interpolated grid at the strike nearest to spot."""
    strikes = surface.get("strike") or []
    maturities = surface.get("maturity_years") or []
    grid = surface.get("iv_decimal") or []
    if not strikes or not min(strikes) <= spot <= max(strikes):
        return []
    column = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    points = []
    for maturity, row in zip(maturities, grid):
        iv = row[column] if column < len(row) else None
        if maturity and maturity > 0 and iv and iv > 0:  # also drops NaN
            points.append({"T": maturity, "iv": iv})
    return points


def to_quant_input(snapshot: Mapping[str, Any]) -> Any:
    """Map a ``POST /v0/volatility-surfaces`` response onto the decision maker's input."""
    from decision_maker import QuantInput, VolSurfaceSnapshot

    statistics = snapshot["statistics"]
    return QuantInput(
        vol_surface=VolSurfaceSnapshot(
            spot=snapshot["spot"],
            # The service does not establish a quote time (market_observed_at is
            # null), so this is when the option chain was retrieved.
            as_of=snapshot.get("market_observed_at") or snapshot["retrieved_at"],
            source=snapshot["source"],
            data_mode=snapshot["data_mode"],
            n_points=statistics["n_points"],
            n_expiries=statistics["n_expiries"],
            atm_iv_mean=statistics.get("atm_iv_decimal"),
            skew_25d_proxy=statistics.get("skew_25d_proxy_decimal"),
            iv_range=statistics.get("iv_range_decimal"),
            T_range=statistics.get("maturity_range_years"),
            strike_range=statistics.get("strike_range"),
            atm_iv_by_expiry=_atm_by_expiry(snapshot.get("surface") or {}, snapshot["spot"]),
        )
    )


def vol_surface_provider(base_url: str, post: Callable[..., Any] | None = None) -> Callable[[str, str], Any]:
    """A quant provider backed by the volatility service at ``base_url``."""
    url = base_url.rstrip("/") + SURFACE_PATH

    def provider(symbol: str, horizon: str) -> Any:  # the surface does not depend on the horizon
        import httpx

        try:
            response = (post or httpx.post)(url, json={"symbol": symbol, "mode": "live"}, timeout=TIMEOUT_SECONDS)
        except httpx.HTTPError as error:
            raise VolSurfaceUnavailable(type(error).__name__) from None
        if response.status_code != 200:
            raise VolSurfaceUnavailable(f"HTTP {response.status_code}")
        return to_quant_input(response.json())

    return provider
