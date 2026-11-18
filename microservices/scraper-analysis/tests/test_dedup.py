from datetime import datetime, timezone

from scraper_analysis.models.evidence import Evidence
from scraper_analysis.pipeline.dedup import dedup_evidence, stable_id

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def make_evidence(**overrides) -> Evidence:
    defaults = dict(
        symbol="AAPL",
        title="Some headline",
        source_name="Sample Wire",
        source_type="general_news",
        source_url="https://example.com/a",
        retrieved_at=NOW,
    )
    defaults.update(overrides)
    return Evidence(**defaults)


def test_dedup_removes_exact_url_duplicates():
    items = [make_evidence(), make_evidence()]
    result = dedup_evidence(items)
    assert len(result) == 1


def test_dedup_keeps_distinct_urls():
    items = [make_evidence(source_url="https://example.com/a"), make_evidence(source_url="https://example.com/b")]
    result = dedup_evidence(items)
    assert len(result) == 2


def test_dedup_falls_back_to_title_when_no_url():
    items = [
        make_evidence(source_url=None, title="Same Headline  "),
        make_evidence(source_url=None, title="same headline"),
    ]
    result = dedup_evidence(items)
    assert len(result) == 1


def test_dedup_empty_list_returns_empty():
    assert dedup_evidence([]) == []


def test_retitled_news_article_keeps_its_id():
    # Outlets edit headlines and bump the published time; it is still one article (issue #46).
    first = make_evidence(title="Nvidia Stock Rises On Report (Live Coverage)", observed_at=NOW.replace(hour=14))
    edited = make_evidence(title="Nvidia Stock Rises On Report", observed_at=NOW.replace(hour=17))
    assert stable_id(first) == stable_id(edited)
    assert len(dedup_evidence([first, edited])) == 1


def test_same_news_url_on_another_day_is_a_new_record():
    today = make_evidence(observed_at=NOW)
    tomorrow = make_evidence(observed_at=NOW.replace(day=11))
    assert stable_id(today) != stable_id(tomorrow)


def test_news_migration_keeps_the_latest_headline_once():
    from uuid import NAMESPACE_URL, uuid5

    from scraper_analysis.storage.migrations import migrate_news_ids
    from scraper_analysis.storage.store import InMemoryEvidenceStore

    def legacy_id(e):  # the pre-#46 fingerprint: url::title::day
        return str(uuid5(NAMESPACE_URL, f"{e.source_url.lower()}::{e.title.strip().lower()}::{e.observed_at.date()}"))

    old = make_evidence(title="Old headline", observed_at=NOW, retrieved_at=NOW)
    new = make_evidence(title="New headline", observed_at=NOW.replace(hour=3), retrieved_at=NOW.replace(hour=4))
    other = make_evidence(source_url="https://example.com/b", observed_at=NOW)
    for e in (old, new, other):
        e.id = legacy_id(e)
    store = InMemoryEvidenceStore()
    store.save_evidence([old, new, other])

    dry = migrate_news_ids(store, apply=False)
    assert dry.groups == 2 and dry.delete_ids == [old.id]
    assert len(store.query_evidence("AAPL")) == 3  # dry run wrote nothing

    migrate_news_ids(store, apply=True)
    rows = store.query_evidence("AAPL")
    assert sorted(r.title for r in rows) == ["New headline", "Some headline"]
    assert all(r.id == stable_id(r) for r in rows)
    assert migrate_news_ids(store, apply=False).is_noop  # idempotent
