"""Pluggable evidence/signal store. Defaults to an in-memory store so the
service runs and is fully testable before the Akamai Postgres cluster
exists; switches to PostgresEvidenceStore automatically once DATABASE_URL
is set (see config.Settings.akamai_db_configured). This is the 'graceful
failure path' AGENTS.md requires -- storage is never silently mocked and
reported as done."""

import json
import logging
from typing import Protocol

from ..config import Settings, get_settings
from ..models.evidence import Evidence
from ..models.signal import Signal
from .embeddings import get_embedding

logger = logging.getLogger(__name__)


class EvidenceStore(Protocol):
    def filter_new_evidence(self, items: list[Evidence]) -> list[Evidence]: ...
    def save_evidence(self, items: list[Evidence]) -> None: ...
    def query_evidence(self, symbol: str) -> list[Evidence]: ...
    def save_signals(self, items: list[Signal]) -> None: ...
    def query_signals(self, symbol: str) -> list[Signal]: ...


class InMemoryEvidenceStore:
    def __init__(self) -> None:
        self._evidence: dict[str, Evidence] = {}
        self._signals: list[Signal] = []

    def filter_new_evidence(self, items: list[Evidence]) -> list[Evidence]:
        return [i for i in items if i.id not in self._evidence]

    def save_evidence(self, items: list[Evidence]) -> None:
        for item in items:
            self._evidence[item.id] = item

    def query_evidence(self, symbol: str) -> list[Evidence]:
        return [e for e in self._evidence.values() if e.symbol.upper() == symbol.upper()]

    def save_signals(self, items: list[Signal]) -> None:
        # Same natural key the Postgres table enforces, so re-ingesting
        # doesn't pile up duplicate signals in memory either.
        keys = {(s.symbol, s.name, s.as_of, s.source) for s in self._signals}
        for s in items:
            if (s.symbol, s.name, s.as_of, s.source) not in keys:
                self._signals.append(s)

    def query_signals(self, symbol: str) -> list[Signal]:
        return [s for s in self._signals if s.symbol.upper() == symbol.upper()]


class PostgresEvidenceStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def filter_new_evidence(self, items: list[Evidence]) -> list[Evidence]:
        if not items:
            return []
        from .db import connect

        with connect(self._settings) as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM evidence WHERE id = ANY(%s::uuid[])", ([i.id for i in items],))
            existing = {str(row[0]) for row in cur.fetchall()}
        return [i for i in items if i.id not in existing]

    def save_evidence(self, items: list[Evidence]) -> None:
        from .db import connect

        with connect(self._settings) as conn, conn.cursor() as cur:
            for item in items:
                embedding = get_embedding(f"{item.title}\n{item.summary or ''}")
                cur.execute(
                    """
                    INSERT INTO evidence (
                        id, symbol, title, summary, source_name, source_type,
                        source_url, published_at, observed_at, retrieved_at,
                        reporting_lag_days, entities, sentiment, credibility,
                        data_mode, embedding, details
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        item.id,
                        item.symbol,
                        item.title,
                        item.summary,
                        item.source_name,
                        item.source_type,
                        item.source_url,
                        item.published_at,
                        item.observed_at,
                        item.retrieved_at,
                        item.reporting_lag_days,
                        json.dumps(item.entities.model_dump()),
                        json.dumps(item.sentiment.model_dump()),
                        json.dumps(item.credibility.model_dump()),
                        item.data_mode,
                        embedding,
                        json.dumps(item.details),
                    ),
                )

    def query_evidence(self, symbol: str) -> list[Evidence]:
        from .db import connect

        with connect(self._settings) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, symbol, title, summary, source_name, source_type,
                       source_url, published_at, observed_at, retrieved_at,
                       reporting_lag_days, entities, sentiment, credibility, data_mode, details
                FROM evidence WHERE symbol = %s ORDER BY retrieved_at DESC
                """,
                (symbol.upper(),),
            )
            rows = cur.fetchall()

        columns = [
            "id", "symbol", "title", "summary", "source_name", "source_type",
            "source_url", "published_at", "observed_at", "retrieved_at",
            "reporting_lag_days", "entities", "sentiment", "credibility", "data_mode", "details",
        ]
        results = []
        for row in rows:
            record = dict(zip(columns, row))
            record["id"] = str(record["id"])
            results.append(Evidence(**record))
        return results

    def save_signals(self, items: list[Signal]) -> None:
        from .db import connect

        with connect(self._settings) as conn, conn.cursor() as cur:
            for item in items:
                cur.execute(
                    """
                    INSERT INTO signals (id, symbol, name, value, unit, "window", as_of, source, data_mode)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol, name, as_of, source) DO NOTHING
                    """,
                    (item.id, item.symbol, item.name, item.value, item.unit, item.window,
                     item.as_of, item.source, item.data_mode),
                )

    def query_signals(self, symbol: str) -> list[Signal]:
        from .db import connect

        with connect(self._settings) as conn, conn.cursor() as cur:
            cur.execute(
                'SELECT id, symbol, name, value, unit, "window", as_of, source, data_mode '
                "FROM signals WHERE symbol = %s ORDER BY as_of DESC",
                (symbol.upper(),),
            )
            rows = cur.fetchall()
        columns = ["id", "symbol", "name", "value", "unit", "window", "as_of", "source", "data_mode"]
        results = []
        for row in rows:
            record = dict(zip(columns, row))
            record["id"] = str(record["id"])
            results.append(Signal(**record))
        return results


_store: EvidenceStore | None = None


def get_store() -> EvidenceStore:
    global _store
    if _store is None:
        settings = get_settings()
        if settings.akamai_db_configured:
            logger.info("using PostgresEvidenceStore (Akamai)")
            _store = PostgresEvidenceStore(settings)
        else:
            logger.info("DATABASE_URL not configured; using InMemoryEvidenceStore")
            _store = InMemoryEvidenceStore()
    return _store
