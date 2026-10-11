from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .evidence import DataMode


class Signal(BaseModel):
    """Dated, unit-labeled quant/market signal. Matches the v0 contract in
    docs/ARCHITECTURE.md and docs/api-contract-v0.md (Jet's A1 proposal,
    which references signal `id` from assessment.reason_codes). Historical/
    realized measures only -- never a forward-looking claim without an
    explicit evaluation horizon."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    name: str
    value: float
    unit: str
    window: str
    as_of: datetime
    source: str
    value_origin: str = "market_signal"
    impact_category: str = "market_mover"
    impact_level: Literal["unknown", "low", "medium", "high"] = "unknown"
    impact_basis: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime | None = None
    lifecycle_status: Literal["fresh", "stale", "archived"] = "fresh"
    stale_at: datetime | None = None
    retention_until: datetime | None = None
    data_mode: DataMode = "sample"
