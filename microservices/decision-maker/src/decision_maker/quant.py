"""Read the vol-surface math into named buckets.

The surface statistics say how much movement and downside protection the
options market is pricing. They do not say which way the stock will go
(vol-surface-builder's own ``docs/methodology.md`` section 7), so nothing here
feeds direction: the combiner only uses these buckets to decide how much
agreement it needs before leaving ``hold``, and to word the uncertainty.

Every threshold is a hand-set constant, not fitted or validated, and is echoed
in the response. The volatility bands are absolute levels, not a comparison
with the symbol's own history, which this service does not keep.
"""

from __future__ import annotations

import math
import uuid

from .models import HORIZON_DAYS, QuantReading, SignalRecord, VolSurfaceSnapshot, as_utc

VOL_LOW_BELOW = 0.20
VOL_HIGH_FROM = 0.40
SKEW_STEEP_RATIO = 0.30
TERM_INVERTED_RATIO = 1.10
TERM_FLAT_RATIO = 0.95
TERM_MIN_SHORT_T = 7 / 365
TERM_MIN_SPREAD = 2.0  # the long expiry must be at least this many times the short one
MIN_POINTS = 30
MIN_EXPIRIES = 3
MIN_SVI_CONVERGED_SHARE = 0.5

THRESHOLDS = {
    "vol_low_below": VOL_LOW_BELOW,
    "vol_high_from": VOL_HIGH_FROM,
    "skew_steep_ratio": SKEW_STEEP_RATIO,
    "term_inverted_ratio": TERM_INVERTED_RATIO,
    "term_flat_ratio": TERM_FLAT_RATIO,
    "min_points": MIN_POINTS,
    "min_expiries": MIN_EXPIRIES,
    "min_svi_converged_share": MIN_SVI_CONVERGED_SHARE,
}

ATM_IV = "ATM implied volatility"
SKEW = "25-delta skew proxy"
IMPLIED_MOVE = "Implied one-standard-deviation move"
TERM_RATIO = "Short-to-long ATM implied volatility ratio"
SURFACE_POINTS = "Option quotes in surface"

DERIVED_SOURCE = "decision-maker (from ATM implied volatility)"
_NAMESPACE = uuid.UUID("6f2b6d1e-3c0a-5f43-9d0e-8a7c1b2d4e5f")


def _signal(symbol: str, name: str, value: float, unit: str, window: str, snap: VolSurfaceSnapshot, source: str) -> SignalRecord:
    # Same natural key the signals table uses, so the id is stable across requests.
    as_of = as_utc(snap.as_of)
    key = f"{symbol}|{name}|{window}|{as_of.isoformat()}|{source}"
    return SignalRecord(
        id=str(uuid.uuid5(_NAMESPACE, key)),
        symbol=symbol,
        name=name,
        value=round(value, 4),
        unit=unit,
        window=window,
        as_of=as_of,
        source=source,
        data_mode=snap.data_mode,
    )


def _term_ratio(snap: VolSurfaceSnapshot) -> float | None:
    usable = sorted((e for e in snap.atm_iv_by_expiry if e.T >= TERM_MIN_SHORT_T), key=lambda e: e.T)
    if len(usable) < 2 or usable[-1].T < TERM_MIN_SPREAD * usable[0].T:
        return None
    return usable[0].iv / usable[-1].iv


def _thin_reasons(snap: VolSurfaceSnapshot) -> list[str]:
    reasons = []
    if snap.atm_iv_mean is None:
        reasons.append("no near-the-money quotes, so ATM implied volatility is missing")
    if snap.n_points < MIN_POINTS:
        reasons.append(f"only {snap.n_points} option quote(s) (need {MIN_POINTS})")
    if snap.n_expiries < MIN_EXPIRIES:
        reasons.append(f"only {snap.n_expiries} expiry(ies) (need {MIN_EXPIRIES})")
    if snap.svi_fits:
        share = sum(f.converged for f in snap.svi_fits) / len(snap.svi_fits)
        if share < MIN_SVI_CONVERGED_SHARE:
            reasons.append(f"SVI fit converged on {share:.0%} of expiries")
    return reasons


def read_vol_surface(symbol: str, snap: VolSurfaceSnapshot | None, horizon: str) -> tuple[QuantReading, list[SignalRecord]]:
    """Buckets for the combiner plus the signal rows that back them."""
    if snap is None:
        return QuantReading(notes=["No options-based math was supplied."]), []

    rows: list[SignalRecord] = []
    ids: dict[str, str] = {}
    reading = QuantReading(status="used", data_quality="ok")

    def add(bucket: str, name: str, value: float, unit: str, window: str = "surface", source: str | None = None) -> None:
        row = _signal(symbol, name, value, unit, window, snap, source or snap.source)
        rows.append(row)
        ids[bucket] = row.id

    add("data_quality", SURFACE_POINTS, float(snap.n_points), "count")

    if snap.atm_iv_mean is not None:
        add("priced_volatility", ATM_IV, snap.atm_iv_mean * 100, "percent_annualized")
        reading.atm_iv_pct = round(snap.atm_iv_mean * 100, 2)
        reading.priced_volatility = (
            "low" if snap.atm_iv_mean < VOL_LOW_BELOW else "high" if snap.atm_iv_mean >= VOL_HIGH_FROM else "moderate"
        )
        move = snap.atm_iv_mean * math.sqrt(HORIZON_DAYS[horizon] / 365) * 100
        add("implied_move", IMPLIED_MOVE, move, "percent", window=horizon, source=DERIVED_SOURCE)
        reading.implied_move_pct = round(move, 2)

        if snap.skew_25d_proxy is not None:
            add("skew", SKEW, snap.skew_25d_proxy * 100, "vol_points")
            reading.skew = "steep" if snap.skew_25d_proxy / snap.atm_iv_mean >= SKEW_STEEP_RATIO else "normal"

    ratio = _term_ratio(snap)
    if ratio is not None:
        add("term_structure", TERM_RATIO, ratio, "ratio")
        reading.term_structure = (
            "inverted" if ratio >= TERM_INVERTED_RATIO else "flat" if ratio >= TERM_FLAT_RATIO else "normal"
        )

    thin = _thin_reasons(snap)
    if thin:
        reading.status = "thin"
        reading.data_quality = "thin"
        reading.notes.append("Options data is thin: " + "; ".join(thin) + ".")
    reading.signal_ids = ids
    return reading, rows
