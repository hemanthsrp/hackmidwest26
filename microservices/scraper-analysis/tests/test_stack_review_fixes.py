"""Regression tests for Hemanth's ACHEN-STACK-REVIEW findings on #10/#12/#13.

1) #13 HIGH   provider errors (MarketAux api_token in URL) leaked via /ingest/run
2) #12 HIGH   fixture signal reached a live briefing (evidence/signals filtered separately)
3) #12 MEDIUM agent_factory construction failure escaped as a 500
4) #10 MEDIUM Form 4 observed_at used periodOfReport, and enrichment changed stable IDs
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from scraper_analysis import config
from scraper_analysis.agents import synthesis_agent as sa
from scraper_analysis.api import app
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.models.signal import Signal
from scraper_analysis.pipeline import ingest
from scraper_analysis.pipeline.dedup import assign_stable_ids, stable_id
from scraper_analysis.pipeline.normalize import normalize
from scraper_analysis.sources import market_signals, news_marketaux
from scraper_analysis.sources.base import (
    RawRecord,
    SourceUnavailableError,
    resolve,
    sanitize_error,
)
from scraper_analysis.sources.form4 import parse_form4
from scraper_analysis.storage import store as store_module
from scraper_analysis.storage.migrations import (
    migrate_sec_filing_ids,
    plan_sec_filing_rekey,
)

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
DUMMY_TOKEN = "dummy-marketaux-token-1234567890"
client = TestClient(app)


# --- 1) error sanitization -------------------------------------------------

@pytest.fixture
def marketaux_401(monkeypatch):
    """Real httpx behaviour: a 401 whose raise_for_status() text contains the
    full request URL, api_token included."""
    monkeypatch.setattr(config, "_settings", config.Settings(news_api_key=DUMMY_TOKEN, database_url=None))

    def fake_get(url, params=None, timeout=None):
        request = httpx.Request("GET", url, params=params)
        assert DUMMY_TOKEN in str(request.url)  # precondition: token really is in the URL
        return httpx.Response(401, request=request, json={"error": "invalid token"})

    monkeypatch.setattr(news_marketaux.httpx, "get", fake_get)
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    monkeypatch.setattr(ingest, "build_adapters", lambda: [news_marketaux.MarketauxNewsAdapter()])
    monkeypatch.setattr(
        market_signals, "fetch_live",
        lambda sym: (_ for _ in ()).throw(SourceUnavailableError(f"see https://x/q?api_token={DUMMY_TOKEN}")),
    )
    yield
    monkeypatch.setattr(store_module, "_store", None)
    monkeypatch.setattr(config, "_settings", None)


def test_marketaux_error_does_not_contain_token(marketaux_401):
    with pytest.raises(SourceUnavailableError) as info:
        news_marketaux.MarketauxNewsAdapter().fetch_live("AAPL")
    assert DUMMY_TOKEN not in str(info.value)
    assert "401" in str(info.value)
    assert info.value.__cause__ is None  # original (token-bearing) exception not chained


@pytest.mark.parametrize("fallback", [True, False])
def test_ingest_run_never_returns_token(marketaux_401, fallback):
    r = client.post("/ingest/run", params={"symbol": "AAPL", "tag": False, "fallback": fallback})
    assert DUMMY_TOKEN not in r.text
    assert r.status_code == (200 if fallback else 503)
    body = r.json()
    sources = body["sources"] if fallback else body["error"]["details"]["sources"]
    errors = {s["name"]: s["error"] for s in sources}
    assert "HTTP 401" in errors["marketaux"]
    assert "<redacted>" in errors["market_signals"]
    if fallback:
        assert body["warnings"] and all(DUMMY_TOKEN not in w for w in body["warnings"])


def test_sanitize_error_strips_query_userinfo_and_secret_params():
    raw = (
        "Client error '401 Unauthorized' for url "
        "'https://api.marketaux.com/v1/news/all?symbols=AAPL&api_token=abc123secret' "
        "db postgresql://user:hunter2@db.example:5432/x?sslmode=require key=zzz"
    )
    clean = sanitize_error(raw)
    for secret in ("abc123secret", "hunter2", "zzz", "symbols=AAPL"):
        assert secret not in clean
    assert "https://api.marketaux.com/v1/news/all?<redacted>" in clean
    assert "postgresql://db.example:5432/x?<redacted>" in clean


def test_sanitize_error_masks_configured_secret_values(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(noaa_cdo_token="noaa-secret-xyz", database_url=None))
    try:
        assert "noaa-secret-xyz" not in sanitize_error("header token noaa-secret-xyz rejected")
    finally:
        monkeypatch.setattr(config, "_settings", None)


def test_resolve_sanitizes_error():
    def boom():
        raise SourceUnavailableError("GET https://h/p?api_token=leak failed")
    r = resolve(boom, list, allow_live=True, fallback=False)
    assert "leak" not in r.error and r.status == "unavailable"


def test_briefing_503_message_is_sanitized(monkeypatch):
    def boom(_s):
        raise sa.BriefingUnavailableError("ConnectError: https://bedrock/x?X-Amz-Signature=sig123")
    monkeypatch.setattr(sa, "generate_briefing", boom)
    r = client.post("/briefing", params={"symbol": "AAPL"})
    assert r.status_code == 503 and "sig123" not in r.text


# --- 2) no fixtures in a live briefing --------------------------------------

def _ev(mode, title):
    return Evidence(symbol="AAPL", title=title, source_name="x", source_type="general_news",
                    retrieved_at=NOW, data_mode=mode)


def _sig(mode, name):
    return Signal(symbol="AAPL", name=name, value=1.0, unit="pct", window="1d", as_of=NOW,
                  source="yf", data_mode=mode)


def test_live_evidence_plus_sample_only_signal_hides_the_signal():
    ev, sig = sa.select_briefing_records([_ev("live", "real")], [_sig("sample", "fixture_sig")])
    assert [e.title for e in ev] == ["real"] and sig == []


def test_live_signal_plus_sample_only_evidence_hides_the_evidence():
    ev, sig = sa.select_briefing_records([_ev("sample", "fixture")], [_sig("live", "real_sig")])
    assert ev == [] and [s.name for s in sig] == ["real_sig"]


def test_all_sample_is_kept_and_flagged():
    ev, sig = sa.select_briefing_records([_ev("sample", "f")], [_sig("sample", "s")])
    assert len(ev) == 1 and len(sig) == 1


def test_briefing_agent_never_sees_fixture_signal_when_evidence_is_live():
    s = store_module.InMemoryEvidenceStore()
    live = _ev("live", "Real live headline")
    s.save_evidence([live])
    s.save_signals([_sig("sample", "fixture_price_change")])
    seen_tool_output = []

    class Agent:
        def __init__(self, tools):
            self.tools = tools

        def __call__(self, _p):
            for t in self.tools:
                if t.tool_name in ("get_evidence", "get_signals"):
                    seen_tool_output.append(t())
            return ('{"headline":"h","overall_tone":"neutral","points":[{"theme":"news","text":"t",'
                    f'"direction":"neutral","evidence_ids":["{live.id}"]}}],"conflicts":[],'
                    '"data_gaps":[],"uncertainty":"u"}')

    out = sa.generate_briefing("AAPL", store=s, agent_factory=lambda sp, tools=None: Agent(tools))
    assert out["status"] == "ok"
    assert "fixture_price_change" not in "".join(seen_tool_output)
    assert out["meta"]["data_modes"] == ["live"] and out["meta"]["signal_count"] == 0
    assert not any("sample" in w for w in out["warnings"])


# --- 3) agent setup failure -> 503 briefing_unavailable --------------------

def _store_with_evidence():
    s = store_module.InMemoryEvidenceStore()
    s.save_evidence([_ev("live", "x")])
    return s


def test_agent_factory_failure_is_briefing_unavailable():
    def bad_factory(system_prompt, tools=None):
        raise ValueError("invalid model id / boto session error")
    with pytest.raises(sa.BriefingUnavailableError, match="setup failed"):
        sa.generate_briefing("AAPL", store=_store_with_evidence(), agent_factory=bad_factory)


def test_tool_construction_failure_is_briefing_unavailable(monkeypatch):
    monkeypatch.setattr(sa, "build_tools", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tool reg")))
    with pytest.raises(sa.BriefingUnavailableError):
        sa.generate_briefing("AAPL", store=_store_with_evidence(), agent_factory=lambda *a, **k: None)


def test_api_agent_setup_failure_is_503_not_500(monkeypatch):
    s = _store_with_evidence()
    monkeypatch.setattr(store_module, "_store", s)
    real = sa.generate_briefing
    monkeypatch.setattr(sa, "generate_briefing",
                        lambda sym: real(sym, agent_factory=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))))
    try:
        r = TestClient(app, raise_server_exceptions=False).post("/briefing", params={"symbol": "AAPL"})
    finally:
        monkeypatch.setattr(store_module, "_store", None)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "briefing_unavailable"


# --- 4) Form 4 trade dates + stable IDs ------------------------------------

MULTI_DATE_XML = """<ownershipDocument>
  <periodOfReport>2026-10-06</periodOfReport>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-10-03</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>10</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-10-01-05:00</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>50</value></transactionShares>
        <transactionPricePerShare><value>11</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000099/form4.xml"


def test_transaction_date_is_actual_trade_date_not_period_of_report():
    f = parse_form4(MULTI_DATE_XML)
    assert f["transaction_date"] == "2026-10-01"  # earliest trade; tz suffix stripped
    assert f["last_transaction_date"] == "2026-10-03"
    assert f["transaction_dates"] == ["2026-10-01", "2026-10-03"]
    assert f["period_of_report"] == "2026-10-06"


def test_enrichment_sets_observed_at_to_earliest_trade_date():
    from scraper_analysis.sources.sec_edgar import SecEdgarAdapter

    class C:
        def get(self, url):
            return httpx.Response(200, text=MULTI_DATE_XML, request=httpx.Request("GET", url))

    rec = RawRecord(source_name="sec_edgar", source_type="sec_filing", symbol="AAPL",
                    payload={"form_type": "4", "accession_number": "0000320193-26-000099",
                             "primary_document": "xslF345X05/form4.xml", "company_name": "Apple Inc."},
                    published_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
                    observed_at=datetime(2026, 10, 8, tzinfo=timezone.utc), url=URL)
    SecEdgarAdapter._enrich_form4(C(), rec, 320193)
    assert rec.observed_at == datetime(2026, 10, 1, tzinfo=timezone.utc)
    ev = normalize(rec, "live")
    assert ev.details["transaction_dates"] == ["2026-10-01", "2026-10-03"]
    assert ev.details["period_of_report"] == "2026-10-06"
    assert "(trades 2026-10-01 to 2026-10-03)" in ev.title
    assert ev.reporting_lag_days == 7


def _filing(enriched: bool, retrieved: datetime = NOW) -> Evidence:
    payload = {"form_type": "4", "company_name": "Apple Inc."}
    observed = datetime(2026, 10, 8, tzinfo=timezone.utc)
    if enriched:
        payload["form4"] = parse_form4(MULTI_DATE_XML)
        observed = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return normalize(RawRecord(source_name="sec_edgar", source_type="sec_filing", symbol="AAPL",
                               payload=payload, retrieved_at=retrieved,
                               published_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
                               observed_at=observed, url=URL), "live")


def test_enrichment_does_not_change_stable_id():
    assert stable_id(_filing(False)) == stable_id(_filing(True))


def test_enriched_copy_replaces_metadata_only_row_but_not_vice_versa():
    s = store_module.InMemoryEvidenceStore()
    meta, rich = _filing(False), _filing(True)
    assign_stable_ids([meta, rich])
    s.save_evidence([meta])
    assert s.filter_new_evidence([rich]) == [rich]
    s.save_evidence([rich])
    [stored] = s.query_evidence("AAPL")
    assert "insider" in stored.details
    # A later metadata-only copy (XML fetch failed) must not downgrade it.
    assert s.filter_new_evidence([meta]) == []
    s.save_evidence([meta])
    assert "insider" in s.query_evidence("AAPL")[0].details


def _legacy_id(e: Evidence) -> str:
    """The pre-fix fingerprint: url::title::observed day."""
    from uuid import NAMESPACE_URL, uuid5
    day = e.observed_at.date().isoformat()
    return str(uuid5(NAMESPACE_URL, f"{e.source_url.lower()}::{e.title.strip().lower()}::{day}"))


def test_migration_collapses_legacy_duplicates_to_one_enriched_row():
    s = store_module.InMemoryEvidenceStore()
    meta = _filing(False, NOW - timedelta(days=1))
    rich = _filing(True, NOW - timedelta(days=2))
    other_meta = _filing(False, NOW)
    other_meta.source_url = URL.replace("99", "98")
    for e in (meta, rich, other_meta):
        e.id = _legacy_id(e)
    s.save_evidence([meta, rich, other_meta, _ev("live", "news untouched")])

    dry = migrate_sec_filing_ids(s, apply=False)
    assert dry.groups == 2 and dry.delete_ids == [meta.id] and len(dry.renames) == 2
    assert len(s.query_evidence("AAPL")) == 4  # dry run wrote nothing

    migrate_sec_filing_ids(s, apply=True)
    filings = s.query_evidence_by_source_type("sec_filing")
    assert len(filings) == 2
    kept = next(e for e in filings if e.source_url == URL)
    assert "insider" in kept.details and kept.id == stable_id(kept)
    assert len(s.query_evidence("AAPL")) == 3  # news row untouched
    assert plan_sec_filing_rekey(s.query_evidence_by_source_type("sec_filing")).is_noop  # idempotent


def test_reingest_after_migration_does_not_duplicate(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    try:
        ingest.run_ingestion("AAPL", allow_live=False, tag=False)
        before = len(s.query_evidence("AAPL"))
        migrate_sec_filing_ids(s, apply=True)
        ingest.run_ingestion("AAPL", allow_live=False, tag=False)
        assert len(s.query_evidence("AAPL")) == before
    finally:
        monkeypatch.setattr(store_module, "_store", None)
