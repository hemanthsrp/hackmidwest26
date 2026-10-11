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


# --- PR #17 review regressions -----------------------------------------------


def test_description_line_shaped_like_a_trade_is_not_a_row():
    # A D: (description) block whose text happens to contain a full
    # "type date date amount" run must never become a transaction.
    text = (
        "U.S. Treasury Bill [GS] S 03/16/2026 03/16/2026 $250,001 - $500,000\n"
        "D: proceeds allocated to Apple (AAPL) P 03/17/2026 03/17/2026 $1,001 - $15,000\n"
        "F S: New\n"
        "S O: Brokerage (MSFT) S 03/17/2026 03/17/2026 $1,001 - $15,000\n"
        "C: see Alphabet (GOOGL) P 03/17/2026 03/17/2026 $1,001 - $15,000\n"
        "L: Austin (TSLA) P 03/17/2026 03/17/2026 $1,001 - $15,000\n"
        "F\x00\x00 S\x00\x00: New (NVDA) P 03/17/2026 03/17/2026 $1,001 - $15,000\n"
    )
    assert h.parse_ptr_text(text) == []


def _zip_with(member_name: str, data: bytes) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member_name, data)
    return buf.getvalue()


def _fake_client(monkeypatch, content: bytes):
    class Resp:
        def __init__(self):
            self.content = content

        def raise_for_status(self):
            pass

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url):
            return Resp()

    monkeypatch.setattr(h.httpx, "Client", Client)
    h._index_cache.clear()


@pytest.mark.parametrize(
    "content",
    [
        _zip_with("2026FD.xml", b"<FinancialDisclosure>\xff\xfe\xfa</FinancialDisclosure>"),  # invalid UTF-8
        _zip_with("2026FD.xml", b"<FinancialDisclosure><Member>"),  # truncated XML
        b"not a zip at all https://disclosures-clerk.house.gov/x?token=SECRET",
    ],
    ids=["bad-utf8", "bad-xml", "bad-zip"],
)
def test_malformed_index_is_unavailable_with_a_fixed_message(adapter, monkeypatch, content):
    _fake_client(monkeypatch, content)
    result = adapter.fetch_result("AAPL", fallback=False)
    assert result.status == "unavailable" and result.items == []
    assert "http" not in result.error and "SECRET" not in result.error and "0xff" not in result.error
    fallback = adapter.fetch_result("AAPL")
    assert fallback.status == "fallback" and fallback.data_mode == "sample"


def _ev(adapter, monkeypatch, rows_, filed_days_ago=10):
    from scraper_analysis.pipeline.dedup import assign_stable_ids

    monkeypatch.setattr(h, "_load_index", lambda client, year: [filing("999", filed_days_ago)])
    monkeypatch.setattr(h, "_load_transactions", lambda client, f: rows_)
    evs = [normalize(r, "live") for r in adapter.fetch_live("AAPL")]
    assign_stable_ids(evs)
    return evs


def _d(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%m/%d/%Y")


def dated_row(tx, notified, owner="Spouse", **kw):
    r = row("AAPL")
    r.update(transaction_date=tx, notification_date=notified, owner=owner, **kw)
    return r


def test_valid_trade_date_still_gets_lag_and_timing(adapter, monkeypatch):
    (ev,) = _ev(adapter, monkeypatch, [dated_row(_d(20), _d(19))])
    assert ev.reporting_lag_days == pytest.approx(10, abs=1)
    assert ev.details["timing"] == "Recent Disclosure" and not ev.details.get("date_issue")


@pytest.mark.parametrize(
    "tx,notified,filed_days_ago,issue",
    [
        ("02/30/2026", "03/01/2026", 10, "unparseable"),  # impossible calendar date
        ("garbage", "03/01/2026", 10, "unparseable"),
        (_d(-5), _d(-5), 10, "future"),  # after retrieval
        (_d(5), _d(5), 10, "after_filing"),  # after the filing date
        (_d(15), _d(20), 10, "after_notification"),  # traded after the member was notified of it
    ],
)
def test_invalid_trade_dates_never_produce_lag_or_timing(adapter, monkeypatch, tx, notified, filed_days_ago, issue):
    (ev,) = _ev(adapter, monkeypatch, [dated_row(tx, notified)], filed_days_ago)
    assert ev.reporting_lag_days is None and ev.details["timing"] is None
    assert ev.details["date_issue"] == issue
    assert ev.observed_at is None  # never guessed (e.g. silently replaced by the filing date)
    assert "Recent Disclosure" not in ev.title and "Historical" not in ev.title


def test_negative_lag_never_gets_a_timing_class():
    from scraper_analysis.sources.base import RawRecord

    rec = RawRecord("Senate eFD", "congressional_disclosure", "AAPL", {"ticker": "AAPL"},
                    published_at=NOW - timedelta(days=5), observed_at=NOW - timedelta(days=1))
    ev = normalize(rec, "live")
    assert ev.details["timing"] is None


def test_distinct_same_day_rows_keep_distinct_ids_and_reingest_is_idempotent(adapter, monkeypatch):
    from scraper_analysis.pipeline.dedup import dedup_evidence

    rows_ = [
        dated_row(_d(20), _d(19), owner="Spouse"),
        dated_row(_d(20), _d(19), owner="Joint"),
        dated_row(_d(20), _d(19), owner="Joint"),  # a second identical lot in the same filing
    ]
    first = _ev(adapter, monkeypatch, rows_)
    assert len({e.id for e in first}) == 3 and len(dedup_evidence(first)) == 3
    again = _ev(adapter, monkeypatch, [dict(r) for r in rows_])
    assert [e.id for e in again] == [e.id for e in first]


def test_senate_fingerprints_are_unchanged():
    from scraper_analysis.pipeline.dedup import _fingerprint
    from scraper_analysis.sources.congressional import SenateEfdAdapter

    ev = normalize(SenateEfdAdapter().fetch_sample("AAPL")[0], "sample")
    day = ev.observed_at.date().isoformat()
    assert _fingerprint(ev) == f"{ev.source_url.strip().lower()}::{' '.join(ev.title.lower().split())}::{day}"


def test_house_trades_feed_the_divergence_congress_leg_with_neutral_labels():
    """After the stack merge, House records share source_type with Senate ones,
    so the divergence congress leg must count them and not call them Senate."""
    from datetime import datetime, timezone

    from scraper_analysis.models.evidence import Evidence
    from scraper_analysis.pipeline.divergence import _congress_leg

    def house(tx_type):
        return Evidence(symbol="AAPL", title=f"Rep. X {tx_type}", source_name="House Clerk",
                        source_type="congressional_disclosure", data_mode="live",
                        retrieved_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
                        details={"chamber": "House", "transaction_type": tx_type})

    leg = _congress_leg([house("Sale (Full)"), house("Sale (Partial)"), house("Purchase")])
    assert leg.direction == "selling"
    assert "Senate" not in (leg.summary or "")
    assert "House" in _congress_leg([]).summary  # empty-leg text names both chambers


# --- PR #17 second review (hbot on eec8096) -----------------------------------


def test_unmarked_description_continuation_shaped_like_a_trade_is_not_a_row():
    # hbot: a D: description that wraps onto unmarked lines, one of which looks
    # exactly like a trade row, must not become a (fabricated) purchase.
    text = (
        "Amazon.com, Inc. - Common Stock (AMZN) [ST] S 03/16/2026 03/16/2026 $1,001 - $15,000\n"
        "F S: New\n"
        "D: The full transaction included the following, reinvested into\n"
        "Apple (AAPL) P 03/17/2026 03/17/2026 $1,001 - $15,000\n"
        "per the advisor's instructions.\n"
    )
    assert [r["ticker"] for r in h.parse_ptr_text(text)] == ["AMZN"]


def test_description_continuation_followed_by_a_real_row_keeps_the_real_row():
    text = (
        "D: proceeds went to\n"
        "Apple (AAPL) P 03/17/2026 03/17/2026 $1,001 - $15,000\n"
        "SP Microsoft Corporation (MSFT) [ST] P 03/18/2026 03/18/2026 $15,001 - $50,000\n"
        "F S: New\n"
        "C: comment that wraps\n"
        "Tesla (TSLA) S 03/19/2026 03/19/2026 $1,001 - $15,000\n"
        "Alphabet Inc. - Class A Common S 03/20/2026 03/20/2026 $1,001 - $15,000\n"
        "Stock (GOOGL) [ST]\n"
        "F S: New\n"
    )
    parsed = h.parse_ptr_text(text)
    assert [r["ticker"] for r in parsed] == ["MSFT", "GOOGL"]
    assert parsed[0]["owner"] == "Spouse"


def test_sample_text_rows_survive_the_description_state_rule():
    # Every real row in the sample follows a field block; all six still parse.
    assert sorted(r["ticker"] for r in h.parse_ptr_text(SAMPLE_TEXT)) == ["AAPL", "AMZN", "BRK.B", "DIA", "MSFT", "T"]


def test_partial_pdf_failures_are_surfaced_on_a_live_result(adapter, monkeypatch):
    filings = [filing("1", 3), filing("2", 4), filing("3", 5), filing("4", 6)]
    monkeypatch.setattr(h, "_load_index", lambda client, year: filings)

    class Resp:
        def __init__(self, url):
            self.url = url
            self.content = url.encode()

        def raise_for_status(self):
            if self.url.endswith("/1.pdf"):
                raise httpx.HTTPStatusError("503 for url 'https://x/1.pdf?token=SECRET'", request=None, response=None)

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url):
            return Resp(url)

    def extract(content):
        if content.endswith(b"/2.pdf"):
            return ""  # scanned: no text layer
        if content.endswith(b"/3.pdf"):
            raise ValueError("pdfminer choked on https://x/3.pdf")
        return "Apple Inc. (AAPL) [ST] P 09/15/2026 09/16/2026 $1,001 - $15,000\nF S: New\n"

    monkeypatch.setattr(h.httpx, "Client", Client)
    monkeypatch.setattr(h, "_extract_pdf_text", extract)
    result = adapter.fetch_result("AAPL", fallback=False)
    assert result.status == "live" and len(result.items) == 1
    assert result.error is not None
    assert "3 of 4" in result.error
    assert "no text layer" in result.error and "unreadable" in result.error and "download" in result.error
    assert "http" not in result.error and "SECRET" not in result.error

    # Cached failures stay visible on the next run (no re-download needed).
    again = adapter.fetch_result("AAPL", fallback=False)
    assert again.error is not None and "no text layer" in again.error and "unreadable" in again.error


def test_full_coverage_live_result_has_no_partial_note(adapter, monkeypatch):
    monkeypatch.setattr(h, "_load_index", lambda client, year: [filing("1", 3)])
    monkeypatch.setattr(h, "_load_transactions", lambda client, f: [row("AAPL")])
    result = adapter.fetch_result("AAPL", fallback=False)
    assert (result.status, result.error, len(result.items)) == ("live", None, 1)


def test_partial_coverage_reaches_ingest_run_sources_and_warnings(monkeypatch):
    from fastapi.testclient import TestClient

    from scraper_analysis.api import app
    from scraper_analysis.pipeline import ingest
    from scraper_analysis.sources import market_signals
    from scraper_analysis.storage import store as store_module

    monkeypatch.setattr(store_module, "_store", store_module.InMemoryEvidenceStore())
    monkeypatch.setattr(market_signals, "fetch_live",
                        lambda sym: (_ for _ in ()).throw(SourceUnavailableError("yf down")))
    h._pdf_cache.clear()
    monkeypatch.setattr(h, "_load_index", lambda client, year: [filing("1", 3), filing("2", 4)])
    monkeypatch.setattr(h, "_load_transactions", lambda client, f: None if f.doc_id == "1" else [row("AAPL")])
    monkeypatch.setattr(ingest, "build_adapters", lambda: [h.HouseClerkAdapter()])
    try:
        resp = TestClient(app).post("/ingest/run?symbol=AAPL&fallback=false&tag=false")
    finally:
        monkeypatch.setattr(store_module, "_store", None)
    assert resp.status_code == 200
    body = resp.json()
    (src,) = [s for s in body["sources"] if s["name"] == "house_clerk"]
    assert src["status"] == "live" and src["count"] == 1 and "1 of 2" in src["error"]
    assert any(w.startswith("house_clerk:") and "partial" in w for w in body["warnings"])


def test_invalid_trade_date_contract_divergence_relies_on(adapter, monkeypatch):
    # The divergence fix keys off this: rejected House dates mean
    # observed_at is None and details.date_issue says why.
    (ev,) = _ev(adapter, monkeypatch, [dated_row(_d(-5), _d(-5))])
    assert ev.observed_at is None and ev.details["date_issue"] == "future"
    assert ev.details["transaction_date_reported"] == _d(-5)
    assert ev.published_at is not None and ev.data_mode == "live"
