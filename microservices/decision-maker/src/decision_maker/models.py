"""Shapes that cross the decision-maker boundary.

Evidence and signal records follow ``docs/api-contract-v0.md`` and the superset
``scraper-analysis`` stores (``microservices/scraper-analysis/INTEGRATION.md``).
``VolSurfaceSnapshot`` mirrors what ``hemanthsrp/vol-surface-builder`` computes, so
the math in ``research-api`` can hand its numbers over nearly as they are.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DataMode = Literal["live", "cached", "sample"]
Horizon = Literal["7d", "30d", "90d"]
RiskProfile = Literal["conservative", "balanced", "growth"]
Label = Literal["buy", "hold", "sell", "insufficient_data"]

HORIZON_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}
MAX_QUERY_CHARS = 500
_SYMBOL = re.compile(r"[A-Z]{1,5}")

# reason_codes are ids of returned evidence or signals, or one of these.
SYSTEM_REASON_CODES = frozenset({"missing_attributable_evidence", "insufficient_direction_signals"})


class DecisionError(Exception):
    """A failure the caller maps onto the contract's error envelope."""

    code = "decision_error"
    retryable = False

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidSymbolError(DecisionError):
    code = "invalid_symbol"


class ProviderUnavailableError(DecisionError):
    code = "provider_unavailable"
    retryable = True


class StaleDataError(DecisionError):
    code = "stale_data"
    retryable = True


def normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper()
    if not _SYMBOL.fullmatch(cleaned):
        raise InvalidSymbolError(
            "symbol must be an uppercase ticker containing 1 to 5 letters",
            {"field": "symbol", "received": symbol[:20]},
        )
    return cleaned


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon: Horizon = "30d"
    # Presentation only until a suitability method is agreed (api-contract-v0.md).
    risk_profile: RiskProfile = "balanced"


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    query: str | None = None
    preferences: Preferences = Field(default_factory=Preferences)
    # "sample" serves the packaged fixture, labelled as such. A failed live
    # request is never answered from it.
    mode: Literal["live", "sample"] = "live"


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    symbol: str
    title: str
    summary: str | None = None
    source_name: str
    source_type: str
    source_url: str | None = None
    published_at: datetime | None = None
    observed_at: datetime | None = None
    retrieved_at: datetime
    reporting_lag_days: float | None = None
    # Stored provenance/lifecycle metadata lets the frontend distinguish a
    # source-backed current record from an older retained record before using
    # semantic ranking. These fields are descriptive, not confidence scores.
    provider: str | None = None
    value_origin: str = "article"
    impact_category: str = "other"
    impact_level: Literal["unknown", "low", "medium", "high"] = "unknown"
    impact_basis: dict[str, Any] = Field(default_factory=dict)
    embedding_status: Literal["available", "unavailable", "not_applicable"] = "not_applicable"
    lifecycle_status: Literal["fresh", "stale", "archived"] = "fresh"
    fresh_until: datetime | None = None
    stale_at: datetime | None = None
    archived_at: datetime | None = None
    retention_until: datetime | None = None
    retention_reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    entities: dict[str, Any] = Field(default_factory=dict)
    sentiment: dict[str, Any] = Field(default_factory=dict)
    credibility: dict[str, Any] = Field(default_factory=dict)
    data_mode: DataMode = "sample"

    @property
    def jev(self) -> dict[str, Any] | None:
        """The Jev judgment on this record, only when Jev actually answered. A
        judgment marked ``engine: "fixture"`` is a labelled stand-in and counts
        only on a sample record."""
        judgment = self.details.get("jev")
        if not judgment:
            return None
        engine = judgment.get("engine")
        if engine == "jev" or (engine == "fixture" and self.data_mode == "sample"):
            return judgment
        return None

    @property
    def grade(self) -> dict[str, Any] | None:
        return self.details.get("grade") or None

    @property
    def credibility_score(self) -> float | None:
        return self.credibility.get("overall_score")

    @property
    def event_time(self) -> datetime | None:
        """When the underlying event happened: the trade date for filings and
        disclosures, the publication time for articles."""
        when = self.observed_at or self.published_at
        return as_utc(when) if when else None


class SignalRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    symbol: str
    name: str
    value: float
    unit: str
    window: str
    as_of: datetime
    source: str
    data_mode: DataMode = "sample"


def _nan_to_none(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class ExpiryIV(BaseModel):
    T: float = Field(gt=0, description="Time to expiry in years")
    iv: float = Field(gt=0, description="At-the-money implied volatility, annualized (0.24 = 24%)")


class SviFit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    T: float
    rmse: float | None = None
    converged: bool = False

    @field_validator("rmse", mode="before")
    @classmethod
    def _nan_is_missing(cls, value: Any) -> Any:
        return _nan_to_none(value)


class VolSurfaceSnapshot(BaseModel):
    """One implied-volatility surface summary for a symbol.

    The statistic names are the keys of ``compute_surface_statistics(df, S)`` in
    vol-surface-builder. That function returns NaN when it cannot compute a value;
    NaN is read as missing. ``spot``, ``as_of``, ``source`` and ``data_mode`` are
    provenance the builder does not emit and the caller must supply.
    """

    model_config = ConfigDict(extra="ignore")

    spot: float = Field(gt=0)
    as_of: datetime
    source: str
    data_mode: DataMode
    n_points: int = 0
    n_expiries: int = 0
    atm_iv_mean: float | None = None
    skew_25d_proxy: float | None = None
    iv_range: tuple[float, float] | None = None
    T_range: tuple[float, float] | None = None
    strike_range: tuple[float, float] | None = None
    # Optional. Lets the term structure be read; one entry per expiry.
    atm_iv_by_expiry: list[ExpiryIV] = Field(default_factory=list)
    # Optional. Rows of calibrate_svi_surface(df).
    svi_fits: list[SviFit] = Field(default_factory=list)

    @field_validator("atm_iv_mean", "skew_25d_proxy", mode="before")
    @classmethod
    def _nan_is_missing(cls, value: Any) -> Any:
        return _nan_to_none(value)


class QuantInput(BaseModel):
    """The math handed in by the caller. Either part may be absent."""

    vol_surface: VolSurfaceSnapshot | None = None
    # Any further dated signals in the contract shape. Returned and citable.
    signals: list[SignalRecord] = Field(default_factory=list)
    # Immutable provider snapshots surfaced separately from market signals.
    quant_citations: list[dict[str, Any]] = Field(default_factory=list)


class Leg(BaseModel):
    """One independent line of evidence about direction."""

    name: str
    # -1 (negative) to 1 (positive). None means the leg has no usable data.
    direction: float | None = None
    reading: str | None = None
    summary: str
    record_ids: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.direction is not None


class QuantReading(BaseModel):
    """Named buckets read off the vol surface. They describe how much movement
    options are pricing. None of them says which way the price will go."""

    status: Literal["used", "thin", "unavailable"] = "unavailable"
    atm_iv_pct: float | None = None
    implied_move_pct: float | None = None
    priced_volatility: Literal["low", "moderate", "high"] | None = None
    skew: Literal["normal", "steep"] | None = None
    term_structure: Literal["normal", "flat", "inverted"] | None = None
    data_quality: Literal["ok", "thin"] | None = None
    # Which returned signal row backs each bucket.
    signal_ids: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    label: Label
    reason_codes: list[str] = Field(default_factory=list)
    net_direction: float | None = None
    score: int | None = None
    threshold: float
    threshold_raised_by: list[str] = Field(default_factory=list)
    # Why a net direction past the threshold was still held at "hold".
    held_because: list[str] = Field(default_factory=list)
    usable_legs: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class ResponseWarning(BaseModel):
    code: str
    message: str
    retryable: bool = False


class Freshness(BaseModel):
    as_of: datetime | None = None
    retrieved_at: datetime | None = None
    status: Literal["fresh", "stale", "unknown"] = "unknown"
    stale_after_seconds: int


class EngineStatus(BaseModel):
    name: str
    status: str
    model: str | None = None
    # For the explanation agent: "tools" or "context" (data packed into the prompt).
    mode: str | None = None
    error: str | None = None


class ExplanationPoint(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class Assessment(BaseModel):
    label: Label
    # 0-100 rescale of the combiner's net direction (50 neutral). None for
    # insufficient_data. A heuristic position, not a probability.
    score: int | None = None
    # Scores at which the label would flip, so the number reads against the label.
    score_sell_at_or_below: int | None = None
    score_buy_at_or_above: int | None = None
    horizon: Horizon
    reason_codes: list[str]
    explanation: str
    explanation_points: list[ExplanationPoint] = Field(default_factory=list)
    # Reply to the user's question; None when there was no question or no model.
    answer: str | None = None
    uncertainty: str
    generated_at: datetime
    data_mode: DataMode
    decision_engine: EngineStatus


class DecisionResponse(BaseModel):
    request_id: str
    symbol: str
    query: str | None = None
    data_mode: DataMode
    freshness: Freshness
    evidence: list[EvidenceRecord]
    signals: list[SignalRecord]
    assessment: Assessment
    warnings: list[ResponseWarning] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
