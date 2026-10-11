from datetime import datetime, timezone

from scraper_analysis.config import Settings
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.storage import db, store


class _Cursor:
    def __init__(self) -> None:
        self.statement = ""
        self.parameters = ()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, parameters=()):
        self.statement = statement
        self.parameters = parameters


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self._cursor


def test_postgres_evidence_insert_binds_every_lifecycle_column(monkeypatch):
    cursor = _Cursor()
    monkeypatch.setattr(db, "connect", lambda settings: _Connection(cursor))
    monkeypatch.setattr(store, "get_embedding", lambda text: None)

    item = Evidence(
        symbol="AAPL",
        title="Lifecycle persistence test",
        source_name="test",
        source_type="general_news",
        retrieved_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
    )
    store.PostgresEvidenceStore(Settings(database_url="postgresql://localhost/test")).save_evidence([item])

    assert cursor.statement.count("%s") == 29
    assert len(cursor.parameters) == 29
