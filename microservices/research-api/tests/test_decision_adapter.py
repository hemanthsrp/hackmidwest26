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
