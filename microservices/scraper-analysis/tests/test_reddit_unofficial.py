from scraper_analysis.sources.base import SourceUnavailableError
from scraper_analysis.sources.reddit_unofficial import RedditUnofficialAdapter


def test_fetch_sample_returns_fixture_for_known_symbol():
    adapter = RedditUnofficialAdapter()
    records = adapter.fetch_sample("AAPL")
    assert len(records) == 1
    assert records[0].symbol == "AAPL"
    assert records[0].source_type == "social_media"


def test_fetch_live_raises_when_feature_flag_disabled(monkeypatch):
    import scraper_analysis.sources.reddit_unofficial as module

    class DisabledSettings:
        enable_reddit_scraper = False

    monkeypatch.setattr(module, "get_settings", lambda: DisabledSettings())
    adapter = RedditUnofficialAdapter()
    try:
        adapter.fetch_live("AAPL")
        assert False, "expected SourceUnavailableError"
    except SourceUnavailableError as exc:
        assert "ENABLE_REDDIT_SCRAPER" in str(exc)


def test_fetch_falls_back_to_sample_when_live_disallowed():
    adapter = RedditUnofficialAdapter()
    records, data_mode = adapter.fetch("AAPL", allow_live=False)
    assert data_mode == "sample"
    assert len(records) == 1
