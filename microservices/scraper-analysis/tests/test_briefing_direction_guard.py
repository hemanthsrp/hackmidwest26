"""PR #17 review (hbot): "Invalid-date briefing claim is accepted". The
evidence tool marks an impossible-dated House purchase date_valid=false /
direction_usable=false, but a briefing agent could still cite that row as
present-tense buying and POST /briefing returned it with no warning. The
server now strips such citations from directional points, drops points left
uncited, and warns -- the rule is enforced in code, not only in the prompt."""

import functools
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from scraper_analysis.agents import synthesis_agent as sa
from scraper_analysis.api import app
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.storage import store as store_module

NOW = datetime.now(timezone.utc)


def _house(title, observed_at, date_issue, owner):
    return Evidence(symbol="AAPL", title=title, source_name="House Clerk", source_type="congressional_disclosure",
                    retrieved_at=NOW, published_at=NOW - timedelta(days=10), observed_at=observed_at,
                    data_mode="live",
                    details={"chamber": "House", "filer_name": "Jane Example", "owner": owner, "ticker": "AAPL",
                             "transaction_type": "Purchase", "amount_range": "$1,001 - $15,000",
                             "date_issue": date_issue})


@pytest.fixture
def store(monkeypatch):
    s = store_module.InMemoryEvidenceStore()
    s.save_evidence([
        _house("Rep. Jane Example reported Purchase of AAPL (invalid trade date)", None, "unparseable", "Self"),
        _house("Rep. Jane Example reported Purchase of AAPL", NOW - timedelta(days=14), None, "Spouse"),
    ])
    monkeypatch.setattr(store_module, "_store", s)
    yield s
    monkeypatch.setattr(store_module, "_store", None)


def ids(store):
    ev = store.query_evidence("AAPL")
    bad = next(e.id for e in ev if e.details.get("date_issue"))
    good = next(e.id for e in ev if not e.details.get("date_issue"))
    return bad, good


def factory(points_fn):
    class Agent:
        def __init__(self, tools):
            self.tools = {t.tool_name: t for t in tools}

        def __call__(self, _prompt):
            self.tools["get_evidence"]()  # the agent really retrieved the rows (citations verifiable)
            return json.dumps({"headline": "h", "overall_tone": "positive", "conflicts": [], "data_gaps": [],
                               "uncertainty": "u", "points": points_fn()})

    return lambda system_prompt, tools=None: Agent(tools)


def point(ids_, direction="positive", theme="congressional", text="Rep. Jane Example is buying AAPL."):
    return {"theme": theme, "text": text, "direction": direction, "evidence_ids": list(ids_)}


def test_directional_claim_on_only_an_invalid_dated_row_is_dropped(store):
    bad, _ = ids(store)
    out = sa.generate_briefing("AAPL", store=store, agent_factory=factory(lambda: [point([bad])]))
    assert out["status"] == "insufficient_data" and out["briefing"] is None
    assert any("invalid or missing trade date" in w and "1" in w for w in out["warnings"])


def test_buy_sell_wording_under_a_neutral_label_is_still_a_directional_claim(store):
    bad, _ = ids(store)
    out = sa.generate_briefing("AAPL", store=store,
                               agent_factory=factory(lambda: [point([bad], direction="neutral")]))
    assert out["status"] == "insufficient_data"
    assert any("invalid or missing trade date" in w for w in out["warnings"])


def test_invalid_citation_is_stripped_but_a_valid_dated_row_still_supports_the_point(store):
    bad, good = ids(store)
    out = sa.generate_briefing("AAPL", store=store, agent_factory=factory(lambda: [point([bad, good])]))
    assert out["status"] == "ok"
    (p,) = out["briefing"]["points"]
    assert p["evidence_ids"] == [good] and p["direction"] == "positive"
    assert any("invalid or missing trade date" in w for w in out["warnings"])


def test_valid_dated_row_supports_a_directional_point_without_warning(store):
    _, good = ids(store)
    out = sa.generate_briefing("AAPL", store=store, agent_factory=factory(lambda: [point([good])]))
    assert out["status"] == "ok" and out["briefing"]["points"][0]["evidence_ids"] == [good]
    assert not any("trade date" in w for w in out["warnings"])


def test_invalid_dated_row_may_back_a_neutral_data_quality_point(store):
    bad, _ = ids(store)
    text = "One House filing has an invalid trade date and is a data-quality gap."
    out = sa.generate_briefing("AAPL", store=store,
                               agent_factory=factory(lambda: [point([bad], direction="neutral", text=text)]))
    assert out["status"] == "ok" and out["briefing"]["points"][0]["evidence_ids"] == [bad]


def _post(monkeypatch, points_fn):
    monkeypatch.setattr(sa, "generate_briefing",
                        functools.partial(sa.generate_briefing, agent_factory=factory(points_fn)))
    resp = TestClient(app).post("/briefing", params={"symbol": "AAPL"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_api_briefing_drops_positive_claim_resting_on_invalid_dated_row(store, monkeypatch):
    bad, _ = ids(store)
    body = _post(monkeypatch, lambda: [point([bad])])
    assert body["status"] == "insufficient_data" and body["briefing"] is None
    assert any("invalid or missing trade date" in w for w in body["warnings"])


def test_api_briefing_keeps_positive_claim_on_valid_dated_row(store, monkeypatch):
    bad, good = ids(store)
    body = _post(monkeypatch, lambda: [point([bad]), point([good])])
    assert body["status"] == "ok"
    assert [p["evidence_ids"] for p in body["briefing"]["points"]] == [[good]]
    assert any("invalid or missing trade date" in w for w in body["warnings"])
