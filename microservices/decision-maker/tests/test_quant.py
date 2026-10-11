import math

import pytest

from decision_maker.models import ExpiryIV, SviFit
from decision_maker.quant import ATM_IV, IMPLIED_MOVE, read_vol_surface

from factories import vol


def test_no_math_is_reported_as_unavailable_without_inventing_rows() -> None:
    reading, rows = read_vol_surface("ACME", None, "30d")

    assert reading.status == "unavailable"
    assert reading.implied_move_pct is None
    assert rows == []


@pytest.mark.parametrize(
    ("atm_iv", "band"),
    [(0.15, "low"), (0.1999, "low"), (0.20, "moderate"), (0.39, "moderate"), (0.40, "high"), (0.75, "high")],
)
def test_priced_volatility_bands_use_absolute_levels(atm_iv: float, band: str) -> None:
    reading, _ = read_vol_surface("ACME", vol(atm_iv_mean=atm_iv), "30d")

    assert reading.priced_volatility == band


@pytest.mark.parametrize(("horizon", "days"), [("7d", 7), ("30d", 30), ("90d", 90)])
def test_implied_move_scales_with_the_square_root_of_the_horizon(horizon: str, days: int) -> None:
    reading, rows = read_vol_surface("ACME", vol(atm_iv_mean=0.31), horizon)

    assert reading.implied_move_pct == pytest.approx(0.31 * math.sqrt(days / 365) * 100, abs=0.01)
    move = next(r for r in rows if r.name == IMPLIED_MOVE)
    assert move.window == horizon
    assert move.id == reading.signal_ids["implied_move"]


def test_horizon_does_not_change_the_volatility_band() -> None:
    bands = {read_vol_surface("ACME", vol(atm_iv_mean=0.25), h)[0].priced_volatility for h in ("7d", "30d", "90d")}

    assert bands == {"moderate"}


@pytest.mark.parametrize(("skew", "bucket"), [(0.03, "normal"), (0.074, "normal"), (0.075, "steep"), (0.2, "steep")])
def test_skew_is_read_relative_to_atm_volatility(skew: float, bucket: str) -> None:
    reading, _ = read_vol_surface("ACME", vol(atm_iv_mean=0.25, skew_25d_proxy=skew), "30d")

    assert reading.skew == bucket


@pytest.mark.parametrize(
    ("short_iv", "long_iv", "bucket"),
    [(0.33, 0.30, "inverted"), (0.30, 0.30, "flat"), (0.285, 0.30, "flat"), (0.25, 0.30, "normal")],
)
def test_term_structure_compares_shortest_and_longest_expiry(short_iv: float, long_iv: float, bucket: str) -> None:
    surface = vol(atm_iv_by_expiry=[ExpiryIV(T=0.08, iv=short_iv), ExpiryIV(T=0.25, iv=0.31), ExpiryIV(T=1.0, iv=long_iv)])

    assert read_vol_surface("ACME", surface, "30d")[0].term_structure == bucket


def test_term_structure_ignores_expiries_inside_a_week_and_needs_a_real_spread() -> None:
    too_short = vol(atm_iv_by_expiry=[ExpiryIV(T=0.005, iv=0.9), ExpiryIV(T=0.08, iv=0.3), ExpiryIV(T=1.0, iv=0.3)])
    too_close = vol(atm_iv_by_expiry=[ExpiryIV(T=0.08, iv=0.4), ExpiryIV(T=0.1, iv=0.3)])

    assert read_vol_surface("ACME", too_short, "30d")[0].term_structure == "flat"
    assert read_vol_surface("ACME", too_close, "30d")[0].term_structure is None
    assert read_vol_surface("ACME", vol(), "30d")[0].term_structure is None


def test_nan_from_the_builder_is_read_as_missing_and_marks_the_surface_thin() -> None:
    reading, rows = read_vol_surface("ACME", vol(atm_iv_mean=float("nan"), skew_25d_proxy=float("nan")), "30d")

    assert reading.status == "thin"
    assert reading.priced_volatility is None
    assert reading.implied_move_pct is None
    assert reading.skew is None
    assert ATM_IV not in {r.name for r in rows}


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_points": 12},
        {"n_expiries": 2},
        {"svi_fits": [SviFit(T=0.1, rmse=0.2, converged=False), SviFit(T=0.5, rmse=0.2, converged=False), SviFit(T=1.0, rmse=0.01, converged=True)]},
    ],
)
def test_sparse_or_badly_fitted_surfaces_are_thin(overrides: dict) -> None:
    reading, _ = read_vol_surface("ACME", vol(**overrides), "30d")

    assert reading.status == "thin"
    assert reading.data_quality == "thin"
    assert reading.notes


def test_signal_rows_carry_provenance_and_stable_distinct_ids() -> None:
    surface = vol(data_mode="cached")
    _, first = read_vol_surface("ACME", surface, "30d")
    _, again = read_vol_surface("ACME", surface, "30d")
    _, other_symbol = read_vol_surface("OTHER", surface, "30d")

    assert [r.id for r in first] == [r.id for r in again]
    assert len({r.id for r in first}) == len(first)
    assert {r.id for r in first}.isdisjoint({r.id for r in other_symbol})
    assert {r.data_mode for r in first} == {"cached"}
    assert all(r.symbol == "ACME" and r.as_of == surface.as_of for r in first)
