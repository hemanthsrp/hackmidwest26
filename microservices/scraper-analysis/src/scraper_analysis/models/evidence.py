from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

DataMode = Literal["live", "cached", "sample"]


class Entities(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    key_people: list[str] = Field(default_factory=list)


class Sentiment(BaseModel):
    direction: Literal["Bullish", "Bearish", "Neutral"] | None = None
    score: float | None = None


class Credibility(BaseModel):
    overall_score: float | None = None
    source_reliability_weight: float | None = None
    verified_filing: bool = False


class Evidence(BaseModel):
    """Normalized evidence record. Field names/semantics follow the v0 contract
    proposed in docs/ARCHITECTURE.md so decision-maker can consume this without
    renegotiating the schema."""

    id: str = Field(default_factory=lambda: str(uuid4()))
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

    # Typed provenance and lifecycle fields are frontend-sortable metadata.
    # They are not an investment-confidence score or a vector similarity score.
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

    # Structured, source-specific facts (e.g. Form 4 buy/sell totals, Senate
    # transaction type) so downstream code never has to parse titles.
    details: dict[str, Any] = Field(default_factory=dict)

    entities: Entities = Field(default_factory=Entities)
    sentiment: Sentiment = Field(default_factory=Sentiment)
    credibility: Credibility = Field(default_factory=Credibility)

    data_mode: DataMode = "sample"
