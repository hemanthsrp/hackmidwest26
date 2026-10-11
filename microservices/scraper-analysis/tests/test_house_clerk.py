from datetime import datetime, timedelta, timezone

import httpx
import pytest

from scraper_analysis.pipeline.normalize import normalize
from scraper_analysis.sources import house_clerk as h
from scraper_analysis.sources.base import SourceUnavailableError

# Layout copied from real e-filed PTRs (2026-10-10), with a fictional member.
# Ticker position varies by row: before the type, after it, on the next line,
# or bare ("DIA [OT]"). Description blocks (F S:, S O:, D:) separate rows.
SAMPLE_TEXT = """Filing ID #20000001
P T R
Name: Hon. Jane Q. Example
Status: Member
ID Owner Asset Transaction Date Notification Amount Cap.
Type Date Gains >
$200?
Amazon.com, Inc. - Common Stock S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000
(AMZN) [ST]
F\x00\x00 S\x00\x00: New
S\x00\x00 O\x00: Brokerage
D\x00\x00: The full transaction included the following sales: AAPL – 20 shares sold @ $253.45/share
Apple Inc. - Common Stock (AAPL) S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000
[ST]
F S: New
AT&T Inc. (T) [ST] P 03/17/2026 03/17/2026 $15,001 - $50,000
F S: New
SP Berkshire Hathaway Inc. New P 03/18/2026 03/18/2026 $50,001 - $100,000
York Class B (BRK/B) [ST]
F S: New
DIA - State Street SPDR Dow Jones S 03/19/2026 03/19/2026 $1,001 - $15,000
DIA [OT]
F S: New
JT Microsoft Corporation - Common E 03/20/2026 03/20/2026 $15,001 -
Stock (MSFT) [ST] $50,000
F S: New
U.S. Treasury Bill [GS] P 03/21/2026 03/21/2026 $250,001 - $500,000
F S: New
SP Indiana ST 5.00% 02/01/32 [GS] S 03/22/2026 03/22/2026 $50,001 - $100,000
F S: New
"""


@pytest.fixture(scope="module")
def rows():
    return {r["ticker"]: r for r in h.parse_ptr_text(SAMPLE_TEXT)}


def test_ticker_in_parens_before_the_type(rows):
    r = rows["AAPL"]
    assert r["transaction_type"] == "Sale (Partial)"
    assert (r["transaction_date"], r["amount_range"]) == ("03/16/2026", "$1,001 - $15,000")
    assert r["asset_type_code"] == "ST" and r["owner"] == "Self"


def test_ticker_on_the_next_line(rows):
    assert rows["AMZN"]["transaction_type"] == "Sale (Partial)"
    assert rows["AMZN"]["asset_name"].startswith("Amazon.com")


def test_ticker_after_asset_name_and_before_type(rows):
    assert rows["T"]["transaction_type"] == "Purchase"
    assert rows["T"]["amount_range"] == "$15,001 - $50,000"


def test_slash_ticker_and_owner_prefix(rows):
    assert "BRK.B" in rows  # BRK/B normalized to the symbol form we validate against
    assert rows["BRK.B"]["owner"] == "Spouse"


def test_bare_ticker_and_other_asset_type(rows):
    assert rows["DIA"]["asset_type_code"] == "OT"
    assert rows["DIA"]["transaction_type"] == "Sale (Full)"


def test_wrapped_amount_range_is_completed_not_dropped(rows):
    assert rows["MSFT"]["amount_range"] == "$15,001 - $50,000"
    assert rows["MSFT"]["transaction_type"] == "Exchange"
    assert rows["MSFT"]["owner"] == "Joint"


def test_assets_without_a_ticker_are_skipped_not_guessed():
    # The Treasury bill and the municipal bond have no ticker: 6 tickered rows only.
    parsed = h.parse_ptr_text(SAMPLE_TEXT)
    assert len(parsed) == 6
    assert all("Treasury" not in r["asset_name"] and "Indiana" not in r["asset_name"] for r in parsed)


def test_tickers_inside_description_blocks_are_not_rows(rows):
    # The D: block mentions AAPL; it must not create a second AAPL row.
    assert len([r for r in h.parse_ptr_text(SAMPLE_TEXT) if r["ticker"] == "AAPL"]) == 1


def test_scanned_or_empty_text_yields_nothing():
    assert h.parse_ptr_text("") == []
    assert h.parse_ptr_text("\n\n") == []


INDEX_XML = """<FinancialDisclosure>
  <Member><First>Jane</First><Last>Example</Last><Suffix/><FilingType>P</FilingType><Year>2026</Year><FilingDate>10/1/2026</FilingDate><DocID>111</DocID></Member>
  <Member><First>Scott Scott</First><Last>Franklin</Last><Suffix/><FilingType>P</FilingType><Year>2026</Year><FilingDate>9/20/2026</FilingDate><DocID>222</DocID></Member>
  <Member><First>Not</First><Last>APtr</Last><Suffix/><FilingType>C</FilingType><Year>2026</Year><FilingDate>9/20/2026</FilingDate><DocID>333</DocID></Member>
  <Member><First>Bad</First><Last>Date</Last><Suffix/><FilingType>P</FilingType><Year>2026</Year><FilingDate>garbage</FilingDate><DocID>444</DocID></Member>
</FinancialDisclosure>"""


def test_index_keeps_only_ptrs_dedupes_repeated_name_words_and_skips_bad_dates():
    filings = h.parse_index(INDEX_XML)
    assert [f.doc_id for f in filings] == ["111", "222"]
    assert filings[1].member == "Scott Franklin"


# --- adapter behavior (network replaced) -------------------------------------

NOW = datetime.now(timezone.utc)


def filing(doc, days_ago, member="Jane Example"):
    return h.HouseFiling(doc, NOW.year, NOW - timedelta(days=days_ago), member)


@pytest.fixture
def adapter(monkeypatch):
    h._pdf_cache.clear()
    return h.HouseClerkAdapter()


def row(ticker="AAPL", kind="Purchase"):
    return {"ticker": ticker, "asset_name": "Apple Inc.", "asset_type_code": "ST", "transaction_type": kind,
            "transaction_date": "09/15/2026", "notification_date": "09/16/2026",
            "amount_range": "$1,001 - $15,000", "owner": "Spouse"}


def test_lookback_cap_and_symbol_filter(adapter, monkeypatch):
    filings = [filing(str(i), days_ago=i) for i in range(1, 60)] + [filing("old", days_ago=h.LOOKBACK_DAYS + 5)]
    monkeypatch.setattr(h, "_load_index", lambda client, year: filings)
    scanned = []

    def load(client, f):
        scanned.append(f.doc_id)
        return [row("AAPL"), row("MSFT")]

    monkeypatch.setattr(h, "_load_transactions", load)
    records = adapter.fetch_live("AAPL")
    assert "old" not in scanned and len(scanned) == h.MAX_FILINGS_TO_SCAN
    assert scanned[0] == "1"  # newest first
    assert len(records) == h.MAX_FILINGS_TO_SCAN and all(r.payload["ticker"] == "AAPL" for r in records)


def test_record_shape_and_normalized_evidence(adapter, monkeypatch):
    monkeypatch.setattr(h, "_load_index", lambda client, year: [filing("999", 10, "Jane Example")])
    monkeypatch.setattr(h, "_load_transactions", lambda client, f: [row("AAPL", "Sale (Partial)")])
    rec = adapter.fetch_live("AAPL")[0]
    assert rec.source_name == "House Clerk" and rec.source_type == "congressional_disclosure"
    assert rec.url.endswith("/999.pdf") and rec.published_at < NOW
    ev = normalize(rec, "live")
    assert ev.title.startswith("Rep. Jane Example reported Sale (Partial) of AAPL")
    assert ev.details["chamber"] == "House" and ev.details["transaction_type"] == "Sale (Partial)"
    assert ev.credibility.verified_filing is True


def test_senate_titles_are_unchanged():
    from scraper_analysis.sources.congressional import SenateEfdAdapter
    ev = normalize(SenateEfdAdapter().fetch_sample("AAPL")[0], "sample")
    assert ev.title.startswith("Sen. ") and ev.details["chamber"] == "Senate"


def test_no_recent_filings_is_an_empty_live_result_not_an_error(adapter, monkeypatch):
    monkeypatch.setattr(h, "_load_index", lambda client, year: [filing("old", h.LOOKBACK_DAYS + 30)])
    assert adapter.fetch_live("AAPL") == []


def test_all_pdfs_unreachable_raises_so_strict_mode_reports_unavailable(adapter, monkeypatch):
    monkeypatch.setattr(h, "_load_index", lambda client, year: [filing("1", 3), filing("2", 4)])
    monkeypatch.setattr(h, "_load_transactions", lambda client, f: None)
    with pytest.raises(SourceUnavailableError):
        adapter.fetch_live("AAPL")


def test_one_unreadable_pdf_does_not_discard_the_rest(adapter, monkeypatch):
    monkeypatch.setattr(h, "_load_index", lambda client, year: [filing("1", 3), filing("2", 4)])
    monkeypatch.setattr(h, "_load_transactions", lambda client, f: None if f.doc_id == "1" else [row("AAPL")])
    assert len(adapter.fetch_live("AAPL")) == 1


def test_index_failure_is_unavailable_and_error_text_has_no_url(adapter, monkeypatch):
    def boom(client, year):
        raise httpx.ConnectError("failed for url 'https://disclosures-clerk.house.gov/x?token=SECRET'")

    monkeypatch.setattr(h, "_load_index", boom)
    with pytest.raises(SourceUnavailableError) as exc:
        adapter.fetch_live("AAPL")
    assert "SECRET" not in str(exc.value) and "token" not in str(exc.value)


def test_pdf_parses_are_cached(monkeypatch):
    h._pdf_cache.clear()
    calls = []

    class Resp:
        content = b"%PDF"

        def raise_for_status(self):
            pass

    class Client:
        def get(self, url):
            calls.append(url)
            return Resp()

    monkeypatch.setattr(h, "_extract_pdf_text", lambda content: SAMPLE_TEXT)
    f = filing("555", 2)
    first = h._load_transactions(Client(), f)
    second = h._load_transactions(Client(), f)
    assert first == second and len(first) == 6 and len(calls) == 1


def test_network_failure_is_not_cached_so_it_retries(monkeypatch):
    h._pdf_cache.clear()

    class Client:
        def get(self, url):
            raise httpx.ConnectError("down")

    assert h._load_transactions(Client(), filing("556", 2)) is None
    assert ("2026", "556") not in h._pdf_cache and not h._pdf_cache


def test_text_less_pdf_is_cached_as_empty_not_retried(monkeypatch):
    h._pdf_cache.clear()

    class Resp:
        content = b"%PDF"

        def raise_for_status(self):
            pass

    class Client:
        def get(self, url):
            return Resp()

    monkeypatch.setattr(h, "_extract_pdf_text", lambda content: "")
    assert h._load_transactions(Client(), filing("557", 2)) == []


def test_fetch_sample_and_fallback(adapter):
    records, mode = adapter.fetch("AAPL", allow_live=False)
    assert mode == "sample" and len(records) == 1 and records[0].payload["chamber"] == "House"
