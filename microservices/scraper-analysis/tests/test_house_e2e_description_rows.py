"""PR #17 review (hbot): "a trade-shaped line with [ST] inside a description
block was persisted as a House purchase through /ingest/run". End to end:
only the network is replaced (index + PDF bytes); the real fetch_live,
_load_transactions, PDF-line parsing, normalize, store and /divergence run.
Each filing has one real AMZN row, then a D:/C: block whose continuation
copies an AAPL purchase -- with and without an owner code, ticker before or
after the amount, [ST] on the same or the next line -- as plain text (no
header row found) and as positioned words (the live layout path)."""

import types
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from scraper_analysis.api import app
from scraper_analysis.pipeline import ingest
from scraper_analysis.sources import house_clerk as h
from scraper_analysis.sources import market_signals
from scraper_analysis.sources.base import SourceUnavailableError
from scraper_analysis.storage import store as store_module

from .test_house_clerk import HEADER, row_at, text_at, to_pages

NOW = datetime.now(timezone.utc)
TX = (NOW - timedelta(days=15)).strftime("%m/%d/%Y")
NOTIFIED = (NOW - timedelta(days=14)).strftime("%m/%d/%Y")
AMOUNT = "$1,001 - $15,000"
REAL_PLAIN = f"Amazon.com (AMZN) [ST] S {TX} {NOTIFIED} {AMOUNT}\nF S: New\n"
REAL_LAYOUT = HEADER + [row_at("Amazon.com (AMZN) [ST]", "S", TX, NOTIFIED, AMOUNT), text_at(104, "F S: New")]

COPIED_ROWS = {
    "no_owner_ticker_before": f"Apple Inc. (AAPL) [ST] P {TX} {NOTIFIED} {AMOUNT}",
    "owner_ticker_before": f"SP Apple Inc. (AAPL) [ST] P {TX} {NOTIFIED} {AMOUNT}",
    "owner_ticker_after_amount": f"SP Apple Inc. P {TX} {NOTIFIED} {AMOUNT} (AAPL) [ST]",
    "no_owner_ticker_after_amount": f"Apple Inc. P {TX} {NOTIFIED} {AMOUNT} (AAPL) [ST]",
    "joint_owner_ticker_before": f"JT Apple Inc. (AAPL) [ST] P {TX} {NOTIFIED} {AMOUNT}",
}
COPIED_NEXT_LINE_ST = (f"SP Apple Inc. (AAPL) P {TX} {NOTIFIED} {AMOUNT}", "[ST]")


def _plain_cases():
    for name, line in COPIED_ROWS.items():
        for marker in ("D", "C"):
            yield f"plain-{marker}-{name}", REAL_PLAIN + f"{marker}: proceeds were reinvested into\n{line}\n"
            yield (f"plain-{marker}-wrapped-{name}",
                   REAL_PLAIN + f"{marker}: the full transaction included\nthe following lots\n{line}\nper advisor.\n")
    yield "plain-D-st-next-line", REAL_PLAIN + "D: proceeds of\n" + "\n".join(COPIED_NEXT_LINE_ST) + "\n"


def _layout_cases():
    for name, line in COPIED_ROWS.items():
        yield f"layout-D-{name}", REAL_LAYOUT + [text_at(104, "D: proceeds were reinvested into"), text_at(104, line)]
        yield f"layout-C-{name}", REAL_LAYOUT + [text_at(104, "C: see"), text_at(104, line)]
    yield "layout-D-st-next-line", REAL_LAYOUT + [text_at(104, "D: proceeds of")] + [
        text_at(104, t) for t in COPIED_NEXT_LINE_ST]


CASES = [(n, ("plain", t)) for n, t in _plain_cases()] + [(n, ("layout", ls)) for n, ls in _layout_cases()]


def _ptr_lines(kind, content):
    if kind == "plain":
        return [h.PtrLine(ln) for ln in content.split("\n")]
    return h.lines_from_pages(to_pages(content))


@pytest.fixture
def run_ingest(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    h._pdf_cache.clear()
    filing = h.HouseFiling("888", NOW.year, NOW - timedelta(days=10), "Jane Example")
    monkeypatch.setattr(h, "_load_index", lambda client, year: [filing])
    monkeypatch.setattr(ingest, "build_adapters", lambda: [h.HouseClerkAdapter()])
    monkeypatch.setattr(market_signals, "fetch_live",
                        lambda sym: (_ for _ in ()).throw(SourceUnavailableError("offline in tests")))

    def run(kind, content):
        h._pdf_cache.clear()
        # Real HTTP client code path, served by a mock transport; the "PDF"
        # bytes are turned into lines by the same parser the live path uses.
        transport = httpx.MockTransport(lambda req: httpx.Response(200, content=b"%PDF-fake"))
        fake_httpx = types.SimpleNamespace(Client=lambda **kw: httpx.Client(transport=transport, **kw),
                                           HTTPError=httpx.HTTPError)
        monkeypatch.setattr(h, "httpx", fake_httpx)
        monkeypatch.setattr(h, "_extract_pdf_lines", lambda content_bytes: _ptr_lines(kind, content))
        resp = TestClient(app).post("/ingest/run?symbol=AAPL&fallback=false&tag=false")
        assert resp.status_code == 200, resp.text
        (src,) = [x for x in resp.json()["sources"] if x["name"] == "house_clerk"]
        assert src["status"] == "live"
        return src, s

    yield run
    monkeypatch.setattr(store_module, "_store", None)
    h._pdf_cache.clear()


@pytest.mark.parametrize("kind_content", [c for _, c in CASES], ids=[n for n, _ in CASES])
def test_trade_shaped_description_line_is_never_a_persisted_house_purchase(run_ingest, kind_content):
    src, stored = run_ingest(*kind_content)
    assert src["count"] == 0
    assert [e for e in stored.query_evidence("AAPL") if e.source_name == "House Clerk"] == []
    body = TestClient(app).get("/divergence", params={"symbol": "AAPL"}).json()
    assert body["legs"]["congress"]["direction"] is None
    assert body["legs"]["congress"]["evidence_ids"] == []


def test_harness_control_a_real_aligned_row_is_persisted(run_ingest):
    # Same harness, but the AAPL purchase is a real column-aligned row: it must
    # be ingested, proving the cases above are rejected by the parser and not
    # by the test plumbing.
    src, stored = run_ingest("layout", REAL_LAYOUT + [
        text_at(104, "D: proceeds were reinvested into"),
        row_at("Apple Inc. (AAPL) [ST]", "P", TX, NOTIFIED, AMOUNT, owner="SP"),
        text_at(104, "F S: New"),
    ])
    assert src["count"] == 1
    (e,) = [e for e in stored.query_evidence("AAPL") if e.source_name == "House Clerk"]
    assert e.details["transaction_type"] == "Purchase" and e.details["owner"] == "Spouse"
    assert e.observed_at is not None
