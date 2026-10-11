"""Read access to the evidence store.

``PgEvidenceSource`` reads the ``evidence`` and ``signals`` tables that
``scraper-analysis`` writes (``storage/schema.sql`` there). It never writes:
every session is opened read-only, so a bug here cannot alter another lane's
data. ``FixtureEvidenceSource`` serves the packaged sample for offline runs and
is only ever selected deliberately.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from importlib import resources
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

from .models import EvidenceRecord, ProviderUnavailableError, QuantInput, SignalRecord, VolSurfaceSnapshot

logger = logging.getLogger(__name__)

# Text in, one vector out. None when embeddings are unavailable.
Embedder = Callable[[str], Sequence[float] | None]

MAX_EVIDENCE_ROWS = 300
MAX_SIGNAL_ROWS = 100
CONNECT_TIMEOUT_SECONDS = 10

_EVIDENCE_COLUMNS = (
    "id", "symbol", "title", "summary", "source_name", "source_type", "source_url",
    "published_at", "observed_at", "retrieved_at", "reporting_lag_days",
    "entities", "sentiment", "credibility", "data_mode", "details",
    "provider", "value_origin", "impact_category", "impact_level", "impact_basis",
    "embedding_status", "lifecycle_status", "fresh_until", "stale_at", "archived_at",
    "retention_until", "retention_reason",
)
_SIGNAL_COLUMNS = ("id", "symbol", "name", "value", "unit", "window", "as_of", "source", "data_mode")


class EvidenceSource(Protocol):
    def load(self, symbol: str) -> tuple[list[EvidenceRecord], list[SignalRecord]]:
        """Stored evidence and signals for the symbol, newest first."""
        ...

    def search(self, symbol: str, query: str, limit: int) -> list[str] | None:
        """Evidence ids for the symbol, closest to the query first. None when
        semantic search is unavailable; never an unrelated ordering."""
        ...


def require_tls(database_url: str) -> str:
    """Same rule as scraper-analysis: a non-local host must use sslmode=require."""
    parsed = urlparse(database_url)
    if parsed.hostname in ("localhost", "127.0.0.1"):
        return database_url
    sslmode = parse_qs(parsed.query).get("sslmode", [None])[0]
    if sslmode != "require":
        raise ValueError(f"DATABASE_URL must set sslmode=require for non-local hosts (got sslmode={sslmode!r})")
    return database_url


def _connect_read_only(database_url: str) -> Any:
    import psycopg

    return psycopg.connect(
        database_url,
        autocommit=True,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        options="-c default_transaction_read_only=on",
    )


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(x):.8g}" for x in vector) + "]"


class PgEvidenceSource:
    def __init__(
        self,
        database_url: str,
        embedder: Embedder | None = None,
        connect: Callable[[], Any] | None = None,
    ) -> None:
        url = require_tls(database_url)
        self._embedder = embedder
        self._connect = connect or (lambda: _connect_read_only(url))

    def load(self, symbol: str) -> tuple[list[EvidenceRecord], list[SignalRecord]]:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(_EVIDENCE_COLUMNS)} FROM evidence "
                    "WHERE symbol = %s ORDER BY retrieved_at DESC LIMIT %s",
                    (symbol, MAX_EVIDENCE_ROWS),
                )
                evidence_rows = cur.fetchall()
                cur.execute(
                    'SELECT id, symbol, name, value, unit, "window", as_of, source, data_mode FROM signals '
                    "WHERE symbol = %s ORDER BY as_of DESC LIMIT %s",
                    (symbol, MAX_SIGNAL_ROWS),
                )
                signal_rows = cur.fetchall()
        except Exception as exc:  # connection, auth, missing driver: all mean no store
            # The exception text can carry the connection string, so only its type is logged.
            logger.warning("evidence store read failed: %s", type(exc).__name__)
            raise ProviderUnavailableError(
                "The evidence store is unavailable; no assessment was generated.",
                {"provider": "evidence_store"},
            ) from exc

        evidence = [EvidenceRecord(**{**dict(zip(_EVIDENCE_COLUMNS, row)), "id": str(row[0])}) for row in evidence_rows]
        signals = [SignalRecord(**{**dict(zip(_SIGNAL_COLUMNS, row)), "id": str(row[0])}) for row in signal_rows]
        return evidence, signals

    def search(self, symbol: str, query: str, limit: int) -> list[str] | None:
        if self._embedder is None:
            return None
        try:
            vector = self._embedder(query)
        except Exception as exc:
            logger.warning("query embedding failed: %s", type(exc).__name__)
            return None
        if not vector:
            return None
        try:
            with self._connect() as conn, conn.cursor() as cur:
                # Scope to the symbol first, then rank that bounded set exactly.
                # Ordering the whole table through the HNSW index and filtering
                # afterwards can return too few rows for a symbol.
                cur.execute(
                    "WITH scoped AS MATERIALIZED ("
                    "  SELECT id, embedding FROM evidence WHERE symbol = %s AND embedding IS NOT NULL"
                    ") SELECT id FROM scoped ORDER BY embedding <=> %s::vector LIMIT %s",
                    (symbol, _vector_literal(vector), limit),
                )
                return [str(row[0]) for row in cur.fetchall()]
        except Exception as exc:
            logger.warning("semantic search failed: %s", type(exc).__name__)
            return None


def _fixture() -> dict[str, Any]:
    text = resources.files("decision_maker").joinpath("fixtures/sample_inputs.json").read_text(encoding="utf-8")
    return json.loads(text)


class FixtureEvidenceSource:
    """The packaged sample, re-labelled to the requested symbol. Every record is
    ``data_mode: "sample"``."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._data = _fixture()

    def _ago(self, hours: float) -> datetime:
        return self._clock() - timedelta(hours=hours)

    def load(self, symbol: str) -> tuple[list[EvidenceRecord], list[SignalRecord]]:
        evidence = []
        for raw in self._data["evidence"]:
            record = {k: v for k, v in raw.items() if not k.endswith("_hours_ago")}
            published = self._ago(raw["published_hours_ago"])
            observed = self._ago(raw["observed_hours_ago"]) if "observed_hours_ago" in raw else published
            evidence.append(
                EvidenceRecord(
                    **{
                        **record,
                        "symbol": symbol,
                        "title": raw["title"].replace("{symbol}", symbol),
                        "published_at": published,
                        "observed_at": observed,
                        "retrieved_at": self._ago(0.1),
                        "data_mode": "sample",
                    }
                )
            )
        signals = [
            SignalRecord(
                **{k: v for k, v in raw.items() if k != "as_of_hours_ago"},
                symbol=symbol,
                as_of=self._ago(raw["as_of_hours_ago"]),
                data_mode="sample",
            )
            for raw in self._data["signals"]
        ]
        return evidence, signals

    def quant(self, symbol: str) -> QuantInput:
        raw = self._data["vol_surface"]
        snapshot = VolSurfaceSnapshot(
            **{k: v for k, v in raw.items() if k != "as_of_hours_ago"},
            as_of=self._ago(raw["as_of_hours_ago"]),
            data_mode="sample",
        )
        return QuantInput(vol_surface=snapshot)

    def search(self, symbol: str, query: str, limit: int) -> list[str] | None:
        # No embeddings offline: rank by shared words, as the scraper's in-memory store does.
        words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 4}
        evidence, _ = self.load(symbol)
        scored = [(sum(w in f"{e.title} {e.summary or ''}".lower() for w in words), e.id) for e in evidence]
        return [record_id for score, record_id in sorted(scored, key=lambda pair: -pair[0]) if score > 0][:limit]
