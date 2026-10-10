from datetime import datetime, timezone

from ..models.evidence import Evidence
from ..sources.base import RawRecord
from .decay import classify_congressional_timing

_NORMALIZERS: dict[str, "callable"] = {}


def register(source_type: str):
    def _wrap(fn):
        _NORMALIZERS[source_type] = fn
        return fn

    return _wrap


def normalize(record: RawRecord, data_mode: str) -> Evidence:
    normalizer = _NORMALIZERS.get(record.source_type, _normalize_generic)
    return normalizer(record, data_mode)


def _reporting_lag_days(published_at: datetime | None, observed_at: datetime | None) -> float | None:
    if not published_at or not observed_at:
        return None
    return (published_at - observed_at).total_seconds() / 86400


@register("sec_filing")
def _normalize_sec_filing(record: RawRecord, data_mode: str) -> Evidence:
    payload = record.payload
    form_type = payload.get("form_type", "")
    items = payload.get("items", "")
    title = f"{payload.get('company_name', record.symbol)} filed Form {form_type}"
    if items:
        title += f" (items {items})"
    return Evidence(
        symbol=record.symbol,
        title=title,
        summary=None,
        source_name="SEC EDGAR",
        source_type=record.source_type,
        source_url=record.url,
        published_at=record.published_at,
        observed_at=record.observed_at,
        retrieved_at=record.retrieved_at,
        reporting_lag_days=_reporting_lag_days(record.published_at, record.observed_at),
        credibility={"overall_score": 1.0, "source_reliability_weight": 1.0, "verified_filing": True},
        data_mode=data_mode,
    )


@register("general_news")
def _normalize_general_news(record: RawRecord, data_mode: str) -> Evidence:
    payload = record.payload
    return Evidence(
        symbol=record.symbol,
        title=payload.get("title") or "(untitled)",
        summary=payload.get("description"),
        source_name=record.source_name,
        source_type=record.source_type,
        source_url=record.url,
        published_at=record.published_at,
        observed_at=record.observed_at,
        retrieved_at=record.retrieved_at,
        reporting_lag_days=_reporting_lag_days(record.published_at, record.observed_at),
        data_mode=data_mode,
    )


@register("congressional_disclosure")
def _normalize_congressional(record: RawRecord, data_mode: str) -> Evidence:
    payload = record.payload
    lag_days = _reporting_lag_days(record.published_at, record.observed_at)
    timing = classify_congressional_timing(lag_days) if lag_days is not None else None
    title = (
        f"Sen. {payload.get('filer_name', 'Unknown')} reported "
        f"{payload.get('transaction_type', 'a transaction')} of {payload.get('ticker', record.symbol)} "
        f"({payload.get('amount_range', 'amount undisclosed')})"
    )
    if timing:
        title += f" -- {timing}"
    summary = f"{payload.get('asset_name', '')} ({payload.get('asset_type', '')}), owner: {payload.get('owner', '')}"
    return Evidence(
        symbol=record.symbol,
        title=title,
        summary=summary,
        source_name=record.source_name,
        source_type=record.source_type,
        source_url=record.url,
        published_at=record.published_at,
        observed_at=record.observed_at,
        retrieved_at=record.retrieved_at,
        reporting_lag_days=lag_days,
        credibility={"overall_score": 1.0, "source_reliability_weight": 1.0, "verified_filing": True},
        data_mode=data_mode,
    )


@register("social_media")
def _normalize_social_media(record: RawRecord, data_mode: str) -> Evidence:
    payload = record.payload
    return Evidence(
        symbol=record.symbol,
        title=payload.get("title") or "(untitled)",
        summary=payload.get("description"),
        source_name=record.source_name,
        source_type=record.source_type,
        source_url=record.url,
        published_at=record.published_at,
        observed_at=record.observed_at,
        retrieved_at=record.retrieved_at,
        reporting_lag_days=_reporting_lag_days(record.published_at, record.observed_at),
        credibility={"overall_score": 0.3, "source_reliability_weight": 0.3, "verified_filing": False},
        data_mode=data_mode,
    )


def _normalize_generic(record: RawRecord, data_mode: str) -> Evidence:
    payload = record.payload
    return Evidence(
        symbol=record.symbol,
        title=str(payload.get("title") or payload.get("form_type") or "(untitled)"),
        summary=payload.get("description") or payload.get("summary"),
        source_name=record.source_name,
        source_type=record.source_type,
        source_url=record.url,
        published_at=record.published_at,
        observed_at=record.observed_at,
        retrieved_at=record.retrieved_at or datetime.now(timezone.utc),
        reporting_lag_days=_reporting_lag_days(record.published_at, record.observed_at),
        data_mode=data_mode,
    )
