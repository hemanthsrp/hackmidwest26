from scraper_analysis.sources.sec_edgar import SecEdgarAdapter


def test_fetch_sample_returns_fixture_records_for_known_symbol():
    adapter = SecEdgarAdapter()
    records = adapter.fetch_sample("AAPL")

    assert len(records) == 2
    forms = {r.payload["form_type"] for r in records}
    assert forms == {"4", "8-K"}
    assert all(r.symbol == "AAPL" for r in records)
    assert all(r.source_type == "sec_filing" for r in records)


def test_fetch_sample_filters_by_symbol():
    adapter = SecEdgarAdapter()
    records = adapter.fetch_sample("TSLA")
    assert records == []


def test_fetch_falls_back_to_sample_when_live_disallowed():
    adapter = SecEdgarAdapter()
    records, data_mode = adapter.fetch("AAPL", allow_live=False)
    assert data_mode == "sample"
    assert len(records) == 2
