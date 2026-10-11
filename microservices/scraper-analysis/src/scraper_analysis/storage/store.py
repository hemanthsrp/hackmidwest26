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
from ..pipeline.dedup import is_enrichment_upgrade
from .embeddings import get_embedding

logger = logging.getLogger(__name__)


class EvidenceStore(Protocol):
    def search_evidence(self, symbol: str, query: str, limit: int = 5) -> list[Evidence]: ...
    def filter_new_evidence(self, items: list[Evidence]) -> list[Evidence]: ...
    def save_evidence(self, items: list[Evidence]) -> None: ...
    def query_evidence(self, symbol: str) -> list[Evidence]: ...
    def query_evidence_by_source_type(self, source_type: str) -> list[Evidence]: ...
    def rekey_evidence(self, renames: dict[str, str], delete_ids: list[str]) -> None: ...
    def save_signals(self, items: list[Signal]) -> None: ...
    def query_signals(self, symbol: str) -> list[Signal]: ...


class InMemoryEvidenceStore:
    def __init__(self) -> None:
        self._evidence: dict[str, Evidence] = {}
        self._signals: list[Signal] = []

    def search_evidence(self, symbol: str, query: str, limit: int = 5) -> list[Evidence]:
        # No embeddings in memory: rank by query-word overlap. Good enough
        # for tests and local runs; Postgres does real vector search.
        words = {w for w in query.lower().split() if len(w) > 2}
        scored = [
            (sum(w in f"{e.title} {e.summary or ''}".lower() for w in words), e)
            for e in self.query_evidence(symbol)
        ]
        return [e for score, e in sorted(scored, key=lambda t: -t[0]) if score > 0][:limit]

    def filter_new_evidence(self, items: list[Evidence]) -> list[Evidence]:
        return [
            i for i in items
            if i.id not in self._evidence or is_enrichment_upgrade(self._evidence[i.id].details, i.details)
        ]

    def save_evidence(self, items: list[Evidence]) -> None:
        for item in items:
            old = self._evidence.get(item.id)
            if old is None or is_enrichment_upgrade(old.details, item.details):
                self._evidence[item.id] = item

    def query_evidence(self, symbol: str) -> list[Evidence]:
        return [e for e in self._evidence.values() if e.symbol.upper() == symbol.upper()]

    def query_evidence_by_source_type(self, source_type: str) -> list[Evidence]:
        return [e for e in self._evidence.values() if e.source_type == source_type]

    def rekey_evidence(self, renames: dict[str, str], delete_ids: list[str]) -> None:
        for old_id in delete_ids:
            self._evidence.pop(old_id, None)
        moved = {new: self._evidence.pop(old) for old, new in renames.items() if old in self._evidence}
        for new_id, item in moved.items():
            item.id = new_id
            self._evidence[new_id] = item

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

    def search_evidence(self, symbol: str, query: str, limit: int = 5) -> list[Evidence]:
        """Semantic search: embed the query via Akamai, rank by pgvector
        cosine distance. If embedding is unavailable, return nothing rather
        than silently substituting an unrelated ordering."""
        vector = get_embedding(query)
        if vector is None:
            return []
        from .db import connect

        with connect(self._settings) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM evidence WHERE symbol = %s AND embedding IS NOT NULL "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (symbol.upper(), vector, limit),
            )
            ranked = [str(r[0]) for r in cur.fetchall()]
        by_id = {e.id: e for e in self.query_evidence(symbol)}
        return [by_id[i] for i in ranked if i in by_id]

    def filter_new_evidence(self, items: list[Evidence]) -> list[Evidence]:
        if not items:
            return []
        from .db import connect

        with connect(self._settings) as conn, conn.cursor() as cur:
            cur.execute("SELECT id, details FROM evidence WHERE id = ANY(%s::uuid[])", ([i.id for i in items],))
            existing = {str(row[0]): row[1] for row in cur.fetchall()}
        return [
            i for i in items
            if i.id not in existing or is_enrichment_upgrade(existing[i.id], i.details)
        ]

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
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title, summary = EXCLUDED.summary,
                        observed_at = EXCLUDED.observed_at, retrieved_at = EXCLUDED.retrieved_at,
                        reporting_lag_days = EXCLUDED.reporting_lag_days,
                        entities = EXCLUDED.entities, sentiment = EXCLUDED.sentiment,
                        credibility = EXCLUDED.credibility, data_mode = EXCLUDED.data_mode,
                        embedding = EXCLUDED.embedding, details = EXCLUDED.details
                    -- only a metadata-only row gaining parsed details is replaced
                    -- (pipeline.dedup.is_enrichment_upgrade); otherwise first write wins
                    WHERE NOT (evidence.details ? 'insider') AND (EXCLUDED.details ? 'insider')
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
        return self._select_evidence("symbol = %s", symbol.upper())

    def query_evidence_by_source_type(self, source_type: str) -> list[Evidence]:
        return self._select_evidence("source_type = %s", source_type)

    def rekey_evidence(self, renames: dict[str, str], delete_ids: list[str]) -> None:
        """Delete duplicates then move kept rows to their new IDs, in one
        transaction so a failure leaves the table untouched."""
        from .db import connect

        with connect(self._settings) as conn, conn.transaction(), conn.cursor() as cur:
            if delete_ids:
                cur.execute("DELETE FROM evidence WHERE id = ANY(%s::uuid[])", (delete_ids,))
            for old_id, new_id in renames.items():
                cur.execute("UPDATE evidence SET id = %s WHERE id = %s", (new_id, old_id))

    def _select_evidence(self, where: str, value: str) -> list[Evidence]:
        from .db import connect

        with connect(self._settings) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, symbol, title, summary, source_name, source_type,
                       source_url, published_at, observed_at, retrieved_at,
                       reporting_lag_days, entities, sentiment, credibility, data_mode, details
                FROM evidence WHERE """ + where + """ ORDER BY retrieved_at DESC
                """,
                (value,),
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
