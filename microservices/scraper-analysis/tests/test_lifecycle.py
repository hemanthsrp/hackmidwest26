"""Evidence/signal lifecycle stages: derived forward-only, never reset by a re-ingest."""

from datetime import UTC, datetime, timedelta

from scraper_analysis.models.evidence import Evidence
from scraper_analysis.models.signal import Signal
from scraper_analysis.pipeline.lifecycle import current_evidence, current_signal, stage
from scraper_analysis.storage.store import InMemoryEvidenceStore

RETRIEVED = datetime(2026, 10, 10, 12, tzinfo=UTC)


def evidence(**fields) -> Evidence:
    return Evidence(**{"symbol": "AAPL", "title": "t", "source_name": "s", "source_type": "general_news",
                       "retrieved_at": RETRIEVED, **fields})


def test_stages_follow_the_timestamps_and_only_move_forward():
    stale_at, archived_at = RETRIEVED + timedelta(days=7), RETRIEVED + timedelta(days=30)
    assert stage("fresh", stale_at, None, RETRIEVED) == "fresh"
    assert stage("fresh", stale_at, None, stale_at) == "stale"  # an overdue job cannot keep it fresh
    assert stage("fresh", stale_at, archived_at, archived_at) == "archived"
    assert stage("archived", stale_at, None, RETRIEVED) == "archived"  # never back to fresh
    assert stage("unknown", None, None, RETRIEVED) == "fresh"


def test_new_evidence_gets_the_policy_timestamps_and_goes_stale_after_seven_days():
    record = current_evidence(evidence(), now=RETRIEVED + timedelta(days=1))
    assert (record.fresh_until, record.stale_at) == (RETRIEVED + timedelta(hours=24), RETRIEVED + timedelta(days=7))
    assert record.lifecycle_status == "fresh"
    assert current_evidence(evidence(), now=RETRIEVED + timedelta(days=8)).lifecycle_status == "stale"


def test_a_signal_is_stale_a_day_after_its_as_of_time():
    signal = Signal(symbol="AAPL", name="30-day price change", value=1.0, unit="percent", window="30d",
                    as_of=RETRIEVED, source="Yahoo Finance")
    assert current_signal(signal, now=RETRIEVED + timedelta(hours=23)).lifecycle_status == "fresh"
    assert current_signal(signal, now=RETRIEVED + timedelta(hours=25)).lifecycle_status == "stale"


def test_store_reads_report_the_current_stage():
    store = InMemoryEvidenceStore()
    store.save_evidence([evidence(id="old"), evidence(id="new", retrieved_at=datetime.now(UTC))])
    stages = {e.id: e.lifecycle_status for e in store.query_evidence("AAPL")}
    assert stages == {"old": "stale", "new": "fresh"}
