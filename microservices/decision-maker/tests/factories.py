"""Small builders for test records. Nothing here touches the network."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from decision_maker.models import EvidenceRecord, Leg, SignalRecord, VolSurfaceSnapshot

NOW = datetime(2026, 10, 10, 22, 0, tzinfo=timezone.utc)


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def news(
    record_id: str,
    direction: str | None = "positive",
    *,
    relevant: float = 0.95,
    hours_ago: float = 10,
    data_mode: str = "live",
    engine: str = "jev",
    source_type: str = "general_news",
    title: str | None = None,
    **judgment,
) -> EvidenceRecord:
    """A news record. ``direction=None`` leaves it without a judgment."""
    details = {}
    if direction is not None:
        details["jev"] = {
            "engine": engine,
            "relevant": relevant,
            "direction": direction,
            "direction_confidence": 0.9,
            "content_type": "news_report",
            "upcoming_event": 0.05,
            "sensational": 0.05,
            "usable_content": 0.95,
            "materiality": 1.5,
            **judgment,
        }
    return EvidenceRecord(
        id=record_id,
        symbol="ACME",
        title=title or f"Headline {record_id}",
        summary=f"Summary of {record_id}.",
        source_name="Test Wire",
        source_type=source_type,
        published_at=ago(hours_ago),
        observed_at=ago(hours_ago),
        retrieved_at=ago(max(hours_ago - 1, 0.1)),
        credibility={"overall_score": 0.8},
        details=details,
        data_mode=data_mode,
    )


def form4(record_id: str, *, buy: float = 0.0, sell: float = 0.0, planned: bool = False, hours_ago: float = 48) -> EvidenceRecord:
    return EvidenceRecord(
        id=record_id,
        symbol="ACME",
        title=f"Form 4 {record_id}",
        source_name="SEC EDGAR",
        source_type="sec_filing",
        published_at=ago(hours_ago),
        observed_at=ago(hours_ago + 24),
        retrieved_at=ago(1),
        credibility={"overall_score": 1.0, "verified_filing": True},
        details={
            "is_10b5_1": planned,
            "buy_shares": buy / 100,
            "buy_value_usd": buy,
            "sell_shares": sell / 100,
            "sell_value_usd": sell,
        },
        data_mode="live",
    )


def senate(record_id: str, kind: str = "Purchase", hours_ago: float = 200) -> EvidenceRecord:
    return EvidenceRecord(
        id=record_id,
        symbol="ACME",
        title=f"Senate {record_id}",
        source_name="Senate eFD",
        source_type="congressional_disclosure",
        published_at=ago(hours_ago - 100),
        observed_at=ago(hours_ago),
        retrieved_at=ago(1),
        credibility={"overall_score": 1.0, "verified_filing": True},
        details={"transaction_type": kind, "amount_range": "$1,001 - $15,000"},
        data_mode="live",
    )


def price(value: float, record_id: str = "sig-price", hours_ago: float = 6, data_mode: str = "live") -> SignalRecord:
    return SignalRecord(
        id=record_id,
        symbol="ACME",
        name="30-day price change",
        value=value,
        unit="percent",
        window="30d",
        as_of=ago(hours_ago),
        source="Yahoo Finance (yfinance)",
        data_mode=data_mode,
    )


def vol(**overrides) -> VolSurfaceSnapshot:
    """A calm, well-populated surface unless overridden."""
    base = {
        "spot": 100.0,
        "as_of": ago(6),
        "source": "Test Options",
        "data_mode": "live",
        "n_points": 400,
        "n_expiries": 8,
        "atm_iv_mean": 0.25,
        "skew_25d_proxy": 0.03,
    }
    return VolSurfaceSnapshot(**{**base, **overrides})


def leg(name: str, direction: float | None, ids: list[str] | None = None, **inputs) -> Leg:
    reading = None if direction is None else "positive" if direction > 0 else "negative" if direction < 0 else "neutral"
    return Leg(name=name, direction=direction, reading=reading, summary=f"{name} summary", record_ids=ids or [], inputs=inputs)


def legs(news_dir=None, insider=None, price_dir=None, congress=None, **news_inputs) -> dict[str, Leg]:
    return {
        "news": leg("news", news_dir, ["n1", "n2"] if news_dir is not None else [], **news_inputs),
        "insider": leg("insider", insider, ["f1"] if insider is not None else []),
        "price": leg("price", price_dir, ["p1"] if price_dir is not None else []),
        "congress": leg("congress", congress, ["c1"] if congress is not None else []),
    }


class ListSource:
    """An evidence source over fixed lists."""

    def __init__(self, evidence=(), signals=(), hits=None, error: Exception | None = None) -> None:
        self.evidence, self.signals, self.hits, self.error = list(evidence), list(signals), hits, error
        self.searches: list[tuple[str, str, int]] = []

    def load(self, symbol):
        if self.error:
            raise self.error
        return list(self.evidence), list(self.signals)

    def search(self, symbol, query, limit):
        self.searches.append((symbol, query, limit))
        return None if self.hits is None else list(self.hits)[:limit]


def review_result(*, unsupported=(), advice=0.02, promise=0.02, status="available", error=None) -> SimpleNamespace:
    """The shape research_api.decision.ExplanationReview has."""
    return SimpleNamespace(
        status=status,
        engine="jev" if status == "available" else "unavailable",
        error=error,
        unsupported_sentences=tuple(unsupported),
        personal_advice=advice,
        promises_outcome=promise,
        reads_as_advice=advice >= 0.5,
        promises_result=promise >= 0.5,
    )
