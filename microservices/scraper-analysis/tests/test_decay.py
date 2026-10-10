import math

from scraper_analysis.pipeline.decay import (
    classify_congressional_timing,
    effective_impact,
    effective_impact_congressional,
    effective_impact_news,
)


def test_effective_impact_at_zero_lag_equals_raw():
    assert effective_impact(1.0, 0, lambda_rate=2.0) == 1.0


def test_effective_impact_decays_monotonically():
    a = effective_impact(1.0, 1, lambda_rate=0.5)
    b = effective_impact(1.0, 2, lambda_rate=0.5)
    c = effective_impact(1.0, 3, lambda_rate=0.5)
    assert a > b > c > 0


def test_effective_impact_matches_formula():
    raw, delta_t, lam = 0.8, 3.0, 0.05
    expected = raw * math.exp(-lam * delta_t)
    assert effective_impact(raw, delta_t, lam) == expected


def test_effective_impact_negative_lag_clamped_to_zero():
    assert effective_impact(1.0, -5, lambda_rate=1.0) == 1.0


def test_effective_impact_news_uses_per_hour_rate():
    assert effective_impact_news(1.0, 0) == 1.0
    assert effective_impact_news(1.0, 1) < 1.0


def test_effective_impact_congressional_uses_per_day_rate():
    assert effective_impact_congressional(1.0, 0) == 1.0
    assert effective_impact_congressional(1.0, 45) < effective_impact_congressional(1.0, 1)


def test_classify_congressional_timing_near_stock_act_limit():
    assert classify_congressional_timing(44) == "Historical Position Adjustment"
    assert classify_congressional_timing(40) == "Historical Position Adjustment"


def test_classify_congressional_timing_recent():
    assert classify_congressional_timing(5) == "Recent Disclosure"
    assert classify_congressional_timing(0) == "Recent Disclosure"
