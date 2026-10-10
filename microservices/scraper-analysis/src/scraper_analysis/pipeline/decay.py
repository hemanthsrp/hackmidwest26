"""Reporting-lag decay, per microservices/scraper-analysis/README.md 3.3:

    I_effective = I_raw * e^(-lambda * delta_t)

where delta_t = t_f - t_e (filing timestamp minus event timestamp). Prevents
treating a delayed disclosure (e.g. a congressional trade reported near the
STOCK Act's 45-day limit) as a fresh, actionable catalyst.
"""

import math

LAMBDA_NEWS_PER_HOUR = 2.0
LAMBDA_CONGRESSIONAL_PER_DAY = 0.05

STOCK_ACT_DISCLOSURE_LIMIT_DAYS = 45
HISTORICAL_ADJUSTMENT_THRESHOLD_DAYS = 40  # "near" the 45-day limit, per README


def effective_impact(raw_impact: float, delta_t: float, lambda_rate: float) -> float:
    if delta_t < 0:
        delta_t = 0  # never apply negative lag (future-dated filings are a data error, not a bonus)
    return raw_impact * math.exp(-lambda_rate * delta_t)


def effective_impact_news(raw_impact: float, lag_hours: float) -> float:
    return effective_impact(raw_impact, lag_hours, LAMBDA_NEWS_PER_HOUR)


def effective_impact_congressional(raw_impact: float, lag_days: float) -> float:
    return effective_impact(raw_impact, lag_days, LAMBDA_CONGRESSIONAL_PER_DAY)


def classify_congressional_timing(lag_days: float) -> str:
    """README 3.3: trades disclosed near the 45-day STOCK Act limit are
    'Historical Position Adjustments', not immediate trade signals."""
    if lag_days >= HISTORICAL_ADJUSTMENT_THRESHOLD_DAYS:
        return "Historical Position Adjustment"
    return "Recent Disclosure"
