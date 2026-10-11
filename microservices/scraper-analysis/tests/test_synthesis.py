import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from scraper_analysis.agents import synthesis_agent as sa
from scraper_analysis.api import app
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.pipeline import ingest
from scraper_analysis.storage import store as store_module

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


@pytest.fixture
def store(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    monkeypatch.setattr(store_module, "_store", s)
    ingest.run_ingestion("AAPL", allow_live=False, tag=False)
    ingest.run_signal_ingestion("AAPL", allow_live=False)
    yield s
    monkeypatch.setattr(store_module, "_store", None)


class FakeAgent:
    """Calls the real tools (so seen_ids fills in) then returns canned text."""

    def __init__(self, tools, reply):
        self.tools, self.reply = tools, reply

    def __call__(self, _prompt):
        for t in self.tools:
            if t.tool_name in ("get_evidence", "get_signals"):
                t()
        return self.reply(self.tools) if callable(self.reply) else self.reply


def factory(reply):
    return lambda system_prompt, tools=None: FakeAgent(tools, reply)


def payload(points, **kw):
    base = {"headline": "h", "overall_tone": "mixed", "points": points,
            "conflicts": [], "data_gaps": [], "uncertainty": "u"}
    base.update(kw)
    return json.dumps(base)


def real_ids(store):
    return [e.id for e in store.query_evidence("AAPL")][:2]


def test_no_evidence_makes_no_model_call():
    called = []
    out = sa.generate_briefing("ZZZZ", store=store_module.InMemoryEvidenceStore(),
                               agent_factory=lambda *a, **k: called.append(1))
    assert out["status"] == "insufficient_data" and not called


def test_valid_citations_are_kept(store):
    ids = real_ids(store)
    reply = payload([{"theme": "news", "text": "t", "direction": "neutral", "evidence_ids": ids}])
    out = sa.generate_briefing("AAPL", store=store, agent_factory=factory(reply))
    assert out["status"] == "ok"
    assert out["briefing"]["points"][0]["evidence_ids"] == ids
    assert out["meta"]["evidence_count"] > 0


def test_hallucinated_citations_are_stripped_and_uncited_points_dropped(store):
    good = real_ids(store)[0]
    reply = payload([
        {"theme": "news", "text": "kept", "direction": "neutral", "evidence_ids": [good, "made-up-id"]},
        {"theme": "insider", "text": "pure fiction", "direction": "negative", "evidence_ids": ["fake-1"]},
    ])
    out = sa.generate_briefing("AAPL", store=store, agent_factory=factory(reply))
    texts = [p["text"] for p in out["briefing"]["points"]]
    assert texts == ["kept"]
    assert out["briefing"]["points"][0]["evidence_ids"] == [good]
    assert any("unverifiable" in w for w in out["warnings"])
    assert any("dropped uncited" in w for w in out["warnings"])


def test_all_points_uncited_becomes_insufficient_data(store):
    reply = payload([{"theme": "news", "text": "x", "direction": "neutral", "evidence_ids": ["nope"]}])
    out = sa.generate_briefing("AAPL", store=store, agent_factory=factory(reply))
    assert out["status"] == "insufficient_data" and out["briefing"] is None


def test_cannot_cite_ids_the_agent_never_retrieved(store):
    # Real id from the store, but the agent never called a tool that returned it.
    stored_id = real_ids(store)[0]

    def silent_factory(system_prompt, tools=None):
        class A:
            def __call__(self, _p):
                return payload([{"theme": "news", "text": "x", "direction": "neutral", "evidence_ids": [stored_id]}])
        return A()

    out = sa.generate_briefing("AAPL", store=store, agent_factory=silent_factory)
    assert out["status"] == "insufficient_data"


def test_fenced_json_is_accepted(store):
    ids = real_ids(store)
    reply = "```json\n" + payload([{"theme": "news", "text": "t", "direction": "neutral", "evidence_ids": ids}]) + "\n```"
    assert sa.generate_briefing("AAPL", store=store, agent_factory=factory(reply))["status"] == "ok"


def test_sample_data_is_flagged(store):
    ids = real_ids(store)
    reply = payload([{"theme": "news", "text": "t", "direction": "neutral", "evidence_ids": ids}])
    out = sa.generate_briefing("AAPL", store=store, agent_factory=factory(reply))
    assert "sample" in out["meta"]["data_modes"]
    assert any("sample" in w for w in out["warnings"])


@pytest.mark.parametrize("reply", ["not json at all", json.dumps({"headline": "missing fields"})])
def test_unparseable_or_invalid_output_raises(store, reply):
    with pytest.raises(sa.BriefingUnavailableError):
        sa.generate_briefing("AAPL", store=store, agent_factory=factory(reply))


def test_model_failure_raises_not_fabricates(store):
    def boom_factory(system_prompt, tools=None):
        class A:
            def __call__(self, _p):
                raise RuntimeError("bedrock down")
        return A()

    with pytest.raises(sa.BriefingUnavailableError):
        sa.generate_briefing("AAPL", store=store, agent_factory=boom_factory)


def test_missing_bedrock_credentials_raise(store, monkeypatch):
    class NoCreds:
        bedrock_configured = False
        bedrock_synthesis_model_id = "m"
    monkeypatch.setattr(sa, "get_settings", lambda: NoCreds())
    with pytest.raises(sa.BriefingUnavailableError, match="credentials"):
        sa.generate_briefing("AAPL", store=store)


def test_tools_are_bound_to_one_symbol(store):
    other = Evidence(symbol="MSFT", title="Microsoft thing", source_name="x", source_type="general_news", retrieved_at=NOW)
    store.save_evidence([other])
    seen = set()
    get_evidence = sa.build_tools(store, "AAPL", seen)[0]
    rows = json.loads(get_evidence())
    assert rows and all("Microsoft thing" != r["title"] for r in rows)
    assert other.id not in seen


def test_search_tool_returns_matching_records(store):
    seen = set()
    search = sa.build_tools(store, "AAPL", seen)[2]
    rows = json.loads(search(query="supplier component constraints"))
    assert rows and any("supplier" in r["title"].lower() for r in rows)
    assert {r["id"] for r in rows} <= seen


client = TestClient(app)


def test_api_briefing_invalid_symbol_is_400():
    assert client.post("/briefing", params={"symbol": "bad!"}).status_code == 400


def test_api_briefing_unavailable_uses_error_envelope(monkeypatch):
    def boom(_s):
        raise sa.BriefingUnavailableError("no creds")
    monkeypatch.setattr(sa, "generate_briefing", boom)
    r = client.post("/briefing", params={"symbol": "AAPL"})
    assert r.status_code == 503
    assert r.json()["error"] == {"code": "briefing_unavailable", "message": "no creds", "retryable": True}


def test_api_briefing_passthrough(monkeypatch):
    monkeypatch.setattr(sa, "generate_briefing", lambda s: {"symbol": s, "status": "ok"})
    assert client.post("/briefing", params={"symbol": "aapl"}).json() == {"symbol": "AAPL", "status": "ok"}


def test_prefer_real_drops_samples_when_live_exists():
    live = Evidence(symbol="AAPL", title="live", source_name="x", source_type="general_news",
                    retrieved_at=NOW, data_mode="live")
    fake = Evidence(symbol="AAPL", title="fixture", source_name="x", source_type="general_news",
                    retrieved_at=NOW, data_mode="sample")
    assert sa.prefer_real([live, fake]) == [live]


def test_prefer_real_keeps_samples_when_nothing_else():
    fake = Evidence(symbol="AAPL", title="fixture", source_name="x", source_type="general_news",
                    retrieved_at=NOW, data_mode="sample")
    assert sa.prefer_real([fake]) == [fake]


def test_tools_hide_fixture_records_once_live_data_exists(store):
    live = Evidence(symbol="AAPL", title="Real live headline", source_name="x",
                    source_type="general_news", retrieved_at=NOW, data_mode="live")
    store.save_evidence([live])
    seen = set()
    rows = json.loads(sa.build_tools(store, "AAPL", seen)[0]())
    assert [r["title"] for r in rows] == ["Real live headline"]
    assert seen == {live.id}
    # search can't smuggle a fixture back in either
    hits = json.loads(sa.build_tools(store, "AAPL", set())[2](query="supplier component constraints"))
    assert all(r["data_mode"] != "sample" for r in hits)


def test_unknown_theme_and_direction_are_coerced_not_fatal(store):
    ids = real_ids(store)
    reply = payload(
        [{"theme": "corporate", "text": "t", "direction": "bullish!!", "evidence_ids": ids}],
        overall_tone="vibes",
    )
    out = sa.generate_briefing("AAPL", store=store, agent_factory=factory(reply))
    point = out["briefing"]["points"][0]
    assert point["theme"] == "other" and point["direction"] == "neutral"
    assert out["briefing"]["overall_tone"] == "neutral"


def test_invalid_output_gets_one_retry_then_succeeds(store):
    ids = real_ids(store)
    good = payload([{"theme": "news", "text": "t", "direction": "neutral", "evidence_ids": ids}])
    replies = iter(["sorry, here is some prose instead of JSON", good])
    prompts = []

    def retry_factory(system_prompt, tools=None):
        class A:
            def __call__(self, p):
                prompts.append(p)
                for t in tools:
                    if t.tool_name == "get_evidence":
                        t()
                return next(replies)
        return A()

    out = sa.generate_briefing("AAPL", store=store, agent_factory=retry_factory)
    assert out["status"] == "ok"
    assert len(prompts) == 2 and "could not be parsed" in prompts[1]


def test_infrastructure_failure_is_not_retried(store):
    calls = []

    def boom_factory(system_prompt, tools=None):
        class A:
            def __call__(self, p):
                calls.append(1)
                raise RuntimeError("bedrock down")
        return A()

    with pytest.raises(sa.BriefingUnavailableError):
        sa.generate_briefing("AAPL", store=store, agent_factory=boom_factory)
    assert len(calls) == 1


def test_briefing_uses_the_synthesis_model_and_reports_it(store, monkeypatch):
    from scraper_analysis.config import Settings

    seen = {}
    reply = payload([{"theme": "news", "text": "t", "direction": "neutral", "evidence_ids": real_ids(store)}])

    def fake_builder(system_prompt, tools=None, model_id=None):
        seen["model_id"] = model_id
        return FakeAgent(tools, reply)

    settings = Settings(_env_file=None, aws_access_key_id="a", aws_secret_access_key="b")
    monkeypatch.setattr(sa, "get_settings", lambda: settings)
    monkeypatch.setattr(sa, "build_bedrock_agent", fake_builder)

    out = sa.generate_briefing("AAPL", store=store)

    assert seen["model_id"] == "us.anthropic.claude-sonnet-5-5"
    assert out["meta"]["model"] == "us.anthropic.claude-sonnet-5-5"


def test_tagging_uses_the_cheaper_tagging_model(monkeypatch):
    from scraper_analysis.agents import tagging_agent
    from scraper_analysis.config import Settings

    seen = {}
    monkeypatch.setattr(tagging_agent, "_agent", None)
    monkeypatch.setattr(tagging_agent, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(
        tagging_agent, "build_bedrock_agent", lambda prompt, tools=None, model_id=None: seen.setdefault("model_id", model_id)
    )

    tagging_agent._get_agent()

    assert seen["model_id"] == "us.anthropic.claude-haiku-5-5"
