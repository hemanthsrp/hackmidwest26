import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from scraper_analysis.agents import synthesis_agent as sa
from scraper_analysis.api import app
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.models.signal import Signal
from scraper_analysis.pipeline import divergence as dv
from scraper_analysis.storage import store as store_module

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def price(value, mode="live"):
    return Signal(symbol="AAPL", name="30-day price change", value=value, unit="percent", window="30d",
                  as_of=NOW, source="yf", data_mode=mode)


def form4(buy=0.0, sell=0.0, plan=False, mode="live"):
    return Evidence(symbol="AAPL", title="f4", source_name="SEC EDGAR", source_type="sec_filing",
                    retrieved_at=NOW, data_mode=mode,
                    details={"buy_shares": 1, "sell_shares": 1, "buy_value_usd": buy,
                             "sell_value_usd": sell, "is_10b5_1": plan})


def senate(kind):
    return Evidence(symbol="AAPL", title="s", source_name="Senate eFD", source_type="congressional_disclosure",
                    retrieved_at=NOW, details={"transaction_type": kind})


def news(direction, score=0.8, cred=0.5):
    return Evidence(symbol="AAPL", title="n", source_name="CNBC", source_type="general_news", retrieved_at=NOW,
                    sentiment={"direction": direction, "score": score}, credibility={"overall_score": cred})


def flag_ids(result):
    return {f["id"] for f in result["flags"]}


def test_insiders_selling_into_rally():
    r = dv.analyze("AAPL", [form4(sell=500_000)], [price(9.0)])
    assert r["status"] == "ok"
    assert flag_ids(r) == {"insiders_selling_into_rally"}
    flag = r["flags"][0]
    assert set(flag["legs"]) == {"price", "insider"} and flag["evidence_ids"]


def test_insiders_buying_into_weakness():
    r = dv.analyze("AAPL", [form4(buy=400_000)], [price(-8.0)])
    assert flag_ids(r) == {"insiders_buying_into_weakness"}


def test_10b5_1_sales_are_excluded_and_explained():
    r = dv.analyze("AAPL", [form4(sell=60_000_000, plan=True)], [price(9.0)])
    assert r["legs"]["insider"]["direction"] == "neutral"
    assert "insiders_selling_into_rally" not in flag_ids(r)
    assert any("10b5-1" in n for n in r["notes"])


def test_small_discretionary_trades_stay_below_threshold():
    r = dv.analyze("AAPL", [form4(sell=dv.INSIDER_NET_USD - 1)], [price(9.0)])
    assert r["legs"]["insider"]["direction"] == "neutral"
    assert r["flags"] == []


def test_price_flat_never_diverges():
    r = dv.analyze("AAPL", [form4(sell=900_000)], [price(1.0)])
    assert r["legs"]["price"]["direction"] == "flat" and r["flags"] == []
    assert any("No divergence" in n for n in r["notes"])


def test_news_price_mismatch_both_ways():
    bull = [news("Bullish") for _ in range(3)]
    bear = [news("Bearish") for _ in range(3)]
    assert flag_ids(dv.analyze("AAPL", bull, [price(-9.0)])) == {"bullish_news_falling_price"}
    assert flag_ids(dv.analyze("AAPL", bear, [price(9.0)])) == {"bearish_news_rising_price"}


def test_news_needs_enough_tagged_items():
    r = dv.analyze("AAPL", [news("Bullish"), news("Bullish")], [price(-9.0)])
    assert r["legs"]["news"]["direction"] is None
    assert r["status"] == "insufficient_data" and r["flags"] == []


def test_news_tone_is_credibility_weighted():
    # One high-credibility bearish item outweighs two low-credibility bullish ones.
    items = [news("Bullish", 0.6, 0.1), news("Bullish", 0.6, 0.1), news("Bearish", 0.9, 0.95)]
    assert dv.analyze("AAPL", items, [price(0)])["legs"]["news"]["direction"] == "bearish"


def test_congress_vs_insiders():
    r = dv.analyze("AAPL", [senate("Purchase"), senate("Purchase"), form4(sell=300_000)], [])
    assert flag_ids(r) == {"congress_buying_insiders_selling"}
    r = dv.analyze("AAPL", [senate("Sale (Partial)"), form4(buy=300_000)], [])
    assert flag_ids(r) == {"congress_selling_insiders_buying"}


def test_agreement_produces_no_flag():
    r = dv.analyze("AAPL", [form4(buy=500_000)], [price(9.0)])
    assert r["status"] == "ok" and r["flags"] == []


def test_fewer_than_two_legs_is_insufficient_data():
    r = dv.analyze("AAPL", [], [price(9.0)])
    assert r["status"] == "insufficient_data" and r["flags"] == []
    assert any("Unavailable" in n for n in r["notes"])


def test_deterministic_and_reports_thresholds():
    ev, sig = [form4(sell=500_000)], [price(9.0)]
    a, b = dv.analyze("AAPL", ev, sig), dv.analyze("AAPL", ev, sig)
    assert a == b
    assert a["thresholds"]["price_move_pct"] == dv.PRICE_MOVE_PCT
    assert "Not a prediction" in a["disclaimer"]


def test_latest_live_price_wins_and_fixture_loses():
    old = price(9.0)
    live_new = Signal(symbol="AAPL", name="30-day price change", value=-7.0, unit="percent", window="30d",
                      as_of=datetime(2026, 10, 11, tzinfo=timezone.utc), source="yf", data_mode="live")
    fixture = price(50.0, mode="sample")
    assert dv._price_leg([old, live_new, fixture]).direction == "down"
    assert dv._price_leg([fixture]).direction == "up"  # fixture only if nothing live


@pytest.fixture
def store(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    yield s
    monkeypatch.setattr(store_module, "_store", None)


client = TestClient(app)


def test_endpoint_ignores_fixtures_when_live_exists(store):
    live = form4(sell=500_000)
    fake = form4(buy=9_000_000, mode="sample")
    store.save_evidence([live, fake])
    store.save_signals([price(9.0)])
    body = client.get("/divergence", params={"symbol": "AAPL"}).json()
    assert body["data_modes"] == ["live"]
    assert flag_ids(body) == {"insiders_selling_into_rally"}  # the fixture's big buy didn't leak in


def test_endpoint_rejects_invalid_symbol():
    assert client.get("/divergence", params={"symbol": "no!"}).status_code == 400


def test_endpoint_with_no_data_is_insufficient(store):
    body = client.get("/divergence", params={"symbol": "ZZZZ"}).json()
    assert body["status"] == "insufficient_data"


def test_synthesis_tool_exposes_divergences_and_registers_citable_ids(store):
    ev = form4(sell=500_000)
    store.save_evidence([ev])
    store.save_signals([price(9.0)])
    seen: set[str] = set()
    tool = sa.build_tools(store, "AAPL", seen)[3]
    assert tool.tool_name == "get_divergences"
    out = json.loads(tool())
    assert out["flags"] and ev.id in seen


def test_filings_with_no_open_market_trades_do_not_count():
    withholding = Evidence(symbol="AAPL", title="f4", source_name="SEC EDGAR", source_type="sec_filing",
                           retrieved_at=NOW, details={"buy_shares": 0.0, "sell_shares": 0.0,
                                                      "buy_value_usd": 0.0, "sell_value_usd": 0.0,
                                                      "is_10b5_1": False, "other_codes": {"F": 40.0}})
    leg, _ = dv._insider_leg([withholding])
    assert leg.direction == "neutral" and leg.evidence_ids == []
    assert "5 filing" not in leg.summary
