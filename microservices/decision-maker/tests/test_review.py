from decision_maker.explain import AGENT_ENGINE, TEMPLATE_ENGINE, Explanation
from decision_maker.models import EngineStatus, ExplanationPoint
from decision_maker.review import review_explanation

from factories import form4, news, review_result

BY_ID = {e.id: e for e in [news("n1"), news("n2"), form4("f1", buy=500_000)]}


def model_text(*points, answer=None, answer_ids=()) -> Explanation:
    return Explanation(
        answer=answer,
        answer_evidence_ids=list(answer_ids),
        points=[ExplanationPoint(text=text, evidence_ids=list(ids)) for text, ids in points],
        engine=EngineStatus(name=AGENT_ENGINE, status="used"),
    )


class Checker:
    """Answers per text; anything unlisted is fully supported and neutral."""

    def __init__(self, by_text=None, error=None) -> None:
        self.by_text, self.error, self.calls = by_text or {}, error, []

    def review(self, *, explanation, evidence):
        self.calls.append((explanation, [e["id"] for e in evidence]))
        if self.error:
            raise self.error
        return self.by_text.get(explanation, review_result())


def test_nothing_is_reviewed_without_a_checker_or_for_code_written_text() -> None:
    text = model_text(("News is positive.", ["n1"]))
    template = text.model_copy(update={"engine": EngineStatus(name=TEMPLATE_ENGINE, status="used")})
    checker = Checker()

    assert review_explanation(text, BY_ID, None).meta is None
    assert review_explanation(template, BY_ID, checker).meta is None
    assert checker.calls == []


def test_only_text_resting_on_news_alone_is_compared_with_its_evidence() -> None:
    checker = Checker()
    text = model_text(
        ("News is positive.", ["n1", "n2"]),
        ("News is positive and an insider bought.", ["n1", "f1"]),
        ("An insider bought.", ["f1"]),
        ("The price rose.", ["a-signal-id"]),
    )

    outcome = review_explanation(text, BY_ID, checker)

    assert checker.calls[0] == ("News is positive.", ["n1", "n2"])
    assert len(checker.calls) == 2 and checker.calls[1][1] == []  # the second call is the wording check
    assert [p["status"] for p in outcome.meta["points"]] == ["checked", "not_checked", "not_checked", "not_checked"]
    assert outcome.explanation.points == text.points
    assert not outcome.replace_with_template


def test_text_that_also_rests_on_a_filing_is_not_removed_for_what_the_news_cannot_show() -> None:
    mixed = "Insiders sold under a plan while news was upbeat."
    checker = Checker({mixed: review_result(unsupported=[mixed])})
    text = model_text(("News is positive.", ["n2"]), answer=mixed, answer_ids=["n1", "f1"])

    outcome = review_explanation(text, BY_ID, checker)

    assert outcome.explanation.answer == mixed
    assert outcome.meta["answer"]["status"] == "not_checked"


def test_an_unsupported_point_is_removed_and_reported() -> None:
    checker = Checker({"Revenue tripled.": review_result(unsupported=["Revenue tripled."])})
    text = model_text(("Revenue tripled.", ["n1"]), ("News is positive.", ["n2"]))

    outcome = review_explanation(text, BY_ID, checker)

    assert [p.text for p in outcome.explanation.points] == ["News is positive."]
    assert [w.code for w in outcome.explanation.warnings] == ["unsupported_point_removed"]
    assert outcome.meta["points"][0]["unsupported_sentences"] == 1


def test_an_unsupported_answer_is_removed_but_the_points_stay() -> None:
    checker = Checker({"It will double.": review_result(unsupported=["It will double."])})
    text = model_text(("News is positive.", ["n2"]), answer="It will double.", answer_ids=["n1"])

    outcome = review_explanation(text, BY_ID, checker)

    assert outcome.explanation.answer is None
    assert outcome.explanation.answer_evidence_ids == []
    assert len(outcome.explanation.points) == 1
    assert outcome.meta["answer"]["status"] == "checked"


def test_only_the_unsupported_sentence_of_an_answer_is_cut() -> None:
    answer = "News reports weaker iPhone demand. Insiders are buying heavily."
    checker = Checker({answer: review_result(unsupported=["Insiders are buying heavily."])})
    text = model_text(("News is positive.", ["n2"]), answer=answer, answer_ids=["n1"])

    outcome = review_explanation(text, BY_ID, checker)

    assert outcome.explanation.answer == "News reports weaker iPhone demand."
    assert outcome.explanation.answer_evidence_ids == ["n1"]
    assert [w.code for w in outcome.explanation.warnings] == ["unsupported_answer_sentence_removed"]


def test_advice_or_promise_wording_sends_the_caller_to_the_template() -> None:
    whole = "You should buy now."
    advice = review_explanation(model_text((whole, ["f1"])), BY_ID, Checker({whole: review_result(advice=0.97)}))
    promise = review_explanation(model_text((whole, ["f1"])), BY_ID, Checker({whole: review_result(promise=0.9)}))

    assert advice.replace_with_template and promise.replace_with_template
    assert advice.meta["personal_advice"] == 0.97
    assert "personal investment advice" in advice.explanation.warnings[-1].message
    assert "presented as certain" in promise.explanation.warnings[-1].message


def test_losing_every_point_also_falls_back_to_the_template() -> None:
    checker = Checker({"Revenue tripled.": review_result(unsupported=["Revenue tripled."])})

    outcome = review_explanation(model_text(("Revenue tripled.", ["n1"])), BY_ID, checker)

    assert outcome.replace_with_template
    assert [w.code for w in outcome.explanation.warnings] == ["unsupported_point_removed", "explanation_replaced"]


def test_when_jev_does_not_answer_the_text_passes_unreviewed_and_says_so() -> None:
    text = model_text(("News is positive.", ["n1"]))
    down = Checker({"News is positive.": review_result(status="unavailable", error="Jev is disabled (JEV_ENABLED is not true).")})

    for checker in (down, Checker(error=TimeoutError("slow"))):
        outcome = review_explanation(text, BY_ID, checker)

        assert outcome.meta["engine"] == "unavailable"
        assert outcome.explanation.points == text.points
        assert not outcome.replace_with_template
        assert [w.code for w in outcome.explanation.warnings] == ["explanation_review_unavailable"]
    assert review_explanation(text, BY_ID, down).meta["error"] == "Jev is disabled (JEV_ENABLED is not true)."
