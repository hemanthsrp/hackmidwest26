import uuid
from datetime import timedelta

import pytest

from decision_maker.models import ProviderUnavailableError
from decision_maker.retrieval import MAX_EVIDENCE_ROWS, FixtureEvidenceSource, PgEvidenceSource, require_tls

from factories import NOW

LOCAL_URL = "postgresql://user:secret@localhost:5432/db"
EVIDENCE_ID = uuid.UUID("13124c2c-19a8-501f-b700-8734b165bf03")
SIGNAL_ID = uuid.UUID("3606605f-0000-5000-8000-000000000001")

EVIDENCE_ROW = (
    EVIDENCE_ID, "AAPL", "Title", None, "SEC EDGAR", "sec_filing", "https://example.invalid/f",
    NOW, NOW, NOW, 2.0, {"tickers": []}, {"direction": None}, {"overall_score": 1.0}, "live", {"is_10b5_1": True},
    "sec", "filing", "insider_activity", "high", {"form": "4"}, "available", "fresh", NOW, None, None, None, None,
)
SIGNAL_ROW = (SIGNAL_ID, "AAPL", "30-day price change", 8.8, "percent", "30d", NOW, "Yahoo Finance (yfinance)", "live")


class FakeCursor:
    def __init__(self, results, fail_on=None) -> None:
        self.results, self.fail_on, self.executed = list(results), fail_on, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None) -> None:
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("relation does not exist: postgresql://user:secret@host/db")
        self.executed.append((sql, params))

    def fetchall(self):
        return self.results.pop(0)


class FakeConnection:
    def __init__(self, cursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self._cursor


def source_with(cursor, embedder=None) -> PgEvidenceSource:
    return PgEvidenceSource(LOCAL_URL, embedder=embedder, connect=lambda: FakeConnection(cursor))


def test_remote_databases_must_use_tls() -> None:
    with pytest.raises(ValueError, match="sslmode=require"):
        PgEvidenceSource("postgresql://user:secret@db.example.com:5432/db")

    assert require_tls("postgresql://u:p@db.example.com/db?sslmode=require")
    assert require_tls(LOCAL_URL) == LOCAL_URL


def test_sessions_are_opened_read_only(monkeypatch) -> None:
    import psycopg

    seen = {}
    monkeypatch.setattr(psycopg, "connect", lambda url, **kwargs: seen.update(url=url, **kwargs) or FakeConnection(FakeCursor([[], []])))

    PgEvidenceSource(LOCAL_URL).load("AAPL")

    assert seen["options"] == "-c default_transaction_read_only=on"
    assert seen["autocommit"] is True


def test_load_maps_rows_onto_contract_records() -> None:
    cursor = FakeCursor([[EVIDENCE_ROW], [SIGNAL_ROW]])

    evidence, signals = source_with(cursor).load("AAPL")

    assert evidence[0].id == str(EVIDENCE_ID)
    assert evidence[0].details == {"is_10b5_1": True}
    assert evidence[0].credibility_score == 1.0
    assert (evidence[0].provider, evidence[0].impact_category, evidence[0].lifecycle_status) == (
        "sec",
        "insider_activity",
        "fresh",
    )
    assert (signals[0].id, signals[0].window, signals[0].value) == (str(SIGNAL_ID), "30d", 8.8)


def test_load_only_reads_and_bounds_what_it_reads() -> None:
    cursor = FakeCursor([[], []])

    source_with(cursor).load("AAPL")

    for sql, params in cursor.executed:
        assert sql.lstrip().upper().startswith("SELECT")
        assert not any(word in sql.upper() for word in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER"))
        assert params[0] == "AAPL"
    assert cursor.executed[0][1][1] == MAX_EVIDENCE_ROWS


def test_a_store_failure_is_provider_unavailable_and_leaks_nothing() -> None:
    cursor = FakeCursor([], fail_on="FROM evidence")

    with pytest.raises(ProviderUnavailableError) as raised:
        source_with(cursor).load("AAPL")

    assert raised.value.details == {"provider": "evidence_store"}
    assert "secret" not in raised.value.message
    assert raised.value.retryable is True


def test_search_without_embeddings_returns_none_rather_than_an_unrelated_order() -> None:
    def broken(text):
        raise OSError("connection refused")

    assert source_with(FakeCursor([])).search("AAPL", "earnings", 5) is None
    assert source_with(FakeCursor([]), embedder=lambda text: None).search("AAPL", "earnings", 5) is None
    assert source_with(FakeCursor([]), embedder=broken).search("AAPL", "earnings", 5) is None


def test_search_ranks_the_symbols_rows_by_vector_distance() -> None:
    cursor = FakeCursor([[(EVIDENCE_ID,), (SIGNAL_ID,)]])

    ids = source_with(cursor, embedder=lambda text: [0.25, -1.0, 3]).search("AAPL", "earnings guidance", 4)

    sql, params = cursor.executed[0]
    assert ids == [str(EVIDENCE_ID), str(SIGNAL_ID)]
    assert "WHERE symbol = %s" in sql and "<=> %s::vector" in sql
    assert params == ("AAPL", "[0.25,-1,3]", 4)


def test_a_failed_vector_query_is_reported_as_unavailable() -> None:
    cursor = FakeCursor([], fail_on="scoped")

    assert source_with(cursor, embedder=lambda text: [0.1]).search("AAPL", "earnings", 5) is None


def test_fixture_records_are_labelled_sample_and_stay_inside_the_window() -> None:
    evidence, signals = FixtureEvidenceSource(clock=lambda: NOW).load("NVDA")

    assert evidence and signals
    assert {r.data_mode for r in [*evidence, *signals]} == {"sample"}
    assert {r.symbol for r in [*evidence, *signals]} == {"NVDA"}
    assert all("NVDA" in e.title or "{symbol}" not in e.title for e in evidence)
    assert all(NOW - timedelta(days=45) < e.event_time <= NOW for e in evidence)
    assert all(e.source_url.startswith("https://example.invalid/") for e in evidence)
    assert all(e.details["jev"]["engine"] == "fixture" for e in evidence if "jev" in e.details)


def test_fixture_quant_and_search_work_offline() -> None:
    source = FixtureEvidenceSource(clock=lambda: NOW)

    assert source.quant("NVDA").vol_surface.data_mode == "sample"
    assert source.search("NVDA", "What happened with the regulator inquiry?", 3)[0] == "sample-news-004"
    assert source.search("NVDA", "zzzzzz", 3) == []
