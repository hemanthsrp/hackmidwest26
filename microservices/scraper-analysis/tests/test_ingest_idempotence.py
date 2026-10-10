from datetime import datetime, timezone

import pytest

from scraper_analysis.models.evidence import Evidence
from scraper_analysis.pipeline import ingest
from scraper_analysis.pipeline.dedup import assign_stable_ids, dedup_evidence, stable_id
from scraper_analysis.storage import store as store_module

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def ev(title, url="https://example.com/a", observed=None, **kw):
    return Evidence(
        symbol="AAPL", title=title, source_name="Senate eFD",
        source_type="congressional_disclosure", source_url=url,
        observed_at=observed, retrieved_at=NOW, **kw,
    )


def test_stable_id_is_deterministic_across_instances():
    assert stable_id(ev("same")) == stable_id(ev("same"))


def test_stable_id_differs_for_different_items():
    assert stable_id(ev("one")) != stable_id(ev("two"))


def test_distinct_transactions_sharing_one_filing_url_are_kept():
    # One Senate PTR page, two transactions on different dates.
    a = ev("Sen. X reported Sale of JPM ($1,001 - $15,000)", observed=datetime(2026, 9, 1, tzinfo=timezone.utc))
    b = ev("Sen. X reported Sale of JPM ($1,001 - $15,000)", observed=datetime(2026, 9, 2, tzinfo=timezone.utc))
    assert len(dedup_evidence([a, b])) == 2


def test_assign_stable_ids_overwrites_random_ids():
    item = ev("x")
    random_id = item.id
    assign_stable_ids([item])
    assert item.id != random_id
    assert item.id == stable_id(item)


@pytest.fixture
def memory_store(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    yield s
    monkeypatch.setattr(store_module, "_store", None)


def test_reingesting_stores_nothing_new(memory_store):
    first = ingest.run_ingestion("AAPL", allow_live=False, tag=False)
    second = ingest.run_ingestion("AAPL", allow_live=False, tag=False)
    assert len(first) > 0
    assert second == []
    assert len(memory_store.query_evidence("AAPL")) == len(first)


def test_ingestion_populates_credibility_for_news(memory_store):
    items = ingest.run_ingestion("AAPL", allow_live=False, tag=False)
    news = [i for i in items if i.source_type == "general_news"]
    assert news and all(i.credibility.overall_score is not None for i in news)
