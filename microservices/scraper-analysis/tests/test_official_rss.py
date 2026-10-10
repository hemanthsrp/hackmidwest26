from scraper_analysis.sources.official_rss import (
    CnbcNewsAdapter,
    MarketWatchNewsAdapter,
    SeekingAlphaNewsAdapter,
    YahooFinanceNewsAdapter,
    _matches_symbol,
    _parse_rss_items,
)

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Apple supplier flags constraints</title>
  <description>Some detail about Apple</description>
  <link>https://example.com/a</link>
  <pubDate>Fri, 09 Oct 2026 19:18:24 GMT</pubDate>
</item>
<item>
  <title>Unrelated company news</title>
  <description>Nothing to do with our symbol</description>
  <link>https://example.com/b</link>
  <pubDate>Fri, 09 Oct 2026 20:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def test_parse_rss_items_extracts_fields():
    items = _parse_rss_items(SAMPLE_RSS)
    assert len(items) == 2
    assert items[0]["title"] == "Apple supplier flags constraints"
    assert items[0]["link"] == "https://example.com/a"
    assert items[0]["published_at"] is not None


def test_matches_symbol_by_company_hint():
    items = _parse_rss_items(SAMPLE_RSS)
    assert _matches_symbol(items[0], "AAPL") is True
    assert _matches_symbol(items[1], "AAPL") is False


def test_matches_symbol_by_literal_ticker():
    item = {"title": "AAPL moves on earnings", "description": ""}
    assert _matches_symbol(item, "AAPL") is True


def test_yahoo_finance_sample_fixture():
    adapter = YahooFinanceNewsAdapter()
    records = adapter.fetch_sample("AAPL")
    assert len(records) == 1
    assert records[0].source_name == "yahoo_finance"  # fixture path uses adapter.name


def test_category_adapters_have_sample_fixtures():
    for adapter in [CnbcNewsAdapter(), MarketWatchNewsAdapter(), SeekingAlphaNewsAdapter()]:
        records = adapter.fetch_sample("AAPL")
        assert len(records) == 1
        assert records[0].symbol == "AAPL"


def test_fetch_falls_back_to_sample_when_live_disallowed():
    adapter = CnbcNewsAdapter()
    records, data_mode = adapter.fetch("AAPL", allow_live=False)
    assert data_mode == "sample"
    assert len(records) == 1
