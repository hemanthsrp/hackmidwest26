from types import SimpleNamespace

from research_api.decision import JevDecisionAdapter


class DisabledJev:
    def judge_article(
        self, symbol: str, company: str, title: str, summary: str
    ) -> SimpleNamespace:
        return SimpleNamespace(
            engine="unavailable",
            error="Jev is disabled (JEV_ENABLED is not true).",
            direction=None,
            materiality=None,
        )


class WorkingJev:
    def judge_article(
        self, symbol: str, company: str, title: str, summary: str
    ) -> SimpleNamespace:
        return SimpleNamespace(
            engine="jev",
            error=None,
            direction="positive",
            materiality=2.0,
        )


def test_jev_adapter_exposes_unavailable_result_without_a_fixture() -> None:
    result = JevDecisionAdapter(DisabledJev()).judge_article(
        symbol="ACME",
        company="ACME Corporation",
        title="ACME sample update",
        summary="Fixture-only evidence.",
    )

    assert result.status == "unavailable"
    assert result.engine == "unavailable"
    assert result.direction is None
    assert result.error == "Jev is disabled (JEV_ENABLED is not true)."


def test_jev_adapter_returns_real_jev_judgment_fields() -> None:
    result = JevDecisionAdapter(WorkingJev()).judge_article(
        symbol="ACME",
        company="ACME Corporation",
        title="ACME sample update",
        summary="Fixture-only evidence.",
    )

    assert result.status == "available"
    assert result.engine == "jev"
    assert result.direction == "positive"
    assert result.materiality == 2.0
    assert result.error is None


# --- additive: full judgment, stored judgments, explanation review ------------

from research_api.decision import JevExplanationAdapter  # noqa: E402


class FullJev:
    def __init__(self) -> None:
        self.calls = 0

    def judge_article(self, symbol: str, company: str, title: str, summary: str) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            engine="jev", error=None, direction="negative", materiality=1.0, relevant=0.6,
            direction_confidence=0.8, content_type="news_report", event_type="operations_or_supply",
            upcoming_event=0.1, sensational=0.05, usable_content=0.97, materiality_confidence=0.7,
            model="jev-1.13.0", request_id="req_1", question_set_version="article-v4",
        )


STORED = {
    "engine": "jev", "direction": "positive", "materiality": 1.9, "relevant": 0.98,
    "content_type": "news_report", "event_type": "earnings_or_guidance", "model": "jev-1.13.0",
    "question_set_version": "article-v4",
}
EVIDENCE = {"id": "e1", "symbol": "ACME", "title": "ACME raises forecast", "summary": None}


def test_adapter_passes_through_the_rest_of_the_judgment_when_present() -> None:
    result = JevDecisionAdapter(FullJev()).judge_article(
        symbol="ACME", company="Acme Corp", title="t", summary="s"
    )
    assert (result.relevant, result.content_type, result.event_type) == (
        0.6, "news_report", "operations_or_supply",
    )
    assert (result.model, result.question_set_version, result.source) == ("jev-1.13.0", "article-v4", "call")


def test_original_five_fields_still_work_with_a_minimal_tool() -> None:
    result = JevDecisionAdapter(WorkingJev()).judge_article(
        symbol="ACME", company="Acme Corp", title="t", summary="s"
    )
    assert (result.status, result.engine, result.direction, result.materiality) == (
        "available", "jev", "positive", 2.0,
    )
    assert result.relevant is None and result.event_type is None


def test_stored_judgment_is_read_without_calling_jev() -> None:
    jev = FullJev()
    result = JevDecisionAdapter(jev).judge_evidence({**EVIDENCE, "details": {"jev": STORED}}, company="Acme Corp")
    assert jev.calls == 0
    assert (result.source, result.direction, result.relevant) == ("stored", "positive", 0.98)


def test_evidence_without_a_stored_judgment_is_sent_to_jev() -> None:
    jev = FullJev()
    result = JevDecisionAdapter(jev).judge_evidence(EVIDENCE, company="Acme Corp")
    assert jev.calls == 1 and (result.source, result.direction) == ("call", "negative")


def test_stored_unavailable_or_missing_judgment_is_reported_as_unavailable() -> None:
    missing = JevDecisionAdapter.from_stored(None)
    failed = JevDecisionAdapter.from_stored({"engine": "unavailable", "error": "timed out"})
    assert (missing.status, missing.engine, missing.direction) == ("unavailable", "unavailable", None)
    assert "No stored Jev judgment" in missing.error
    assert (failed.status, failed.error) == ("unavailable", "timed out")


class Checker:
    def __init__(self, engine: str = "jev") -> None:
        self.engine = engine

    def check_explanation(self, explanation, evidence) -> SimpleNamespace:
        if self.engine != "jev":
            return SimpleNamespace(engine="unavailable", error="Jev is disabled (JEV_ENABLED is not true).")
        return SimpleNamespace(
            engine="jev", error=None,
            claims=[
                SimpleNamespace(text="ACME raised its forecast.", supported=0.97),
                SimpleNamespace(text="ACME announced a buyback.", supported=0.04),
            ],
            personal_advice=0.02, promises_outcome=0.91,
        )


def test_explanation_review_flags_without_editing() -> None:
    review = JevExplanationAdapter(Checker()).review(
        explanation="ACME raised its forecast. ACME announced a buyback.", evidence=[EVIDENCE]
    )
    assert (review.status, review.engine) == ("available", "jev")
    assert review.unsupported_sentences == ("ACME announced a buyback.",)
    assert review.reads_as_advice is False and review.promises_result is True


def test_explanation_review_exposes_unavailable() -> None:
    review = JevExplanationAdapter(Checker(engine="unavailable")).review(explanation="x.", evidence=[])
    assert (review.status, review.engine) == ("unavailable", "unavailable")
    assert review.unsupported_sentences == () and review.reads_as_advice is False
