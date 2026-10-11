from types import SimpleNamespace

from decision_maker.judging import MAX_FRESH_JUDGMENTS, judge_missing

from factories import form4, news


def judged(direction="positive", **fields) -> SimpleNamespace:
    """The shape research_api.decision.DecisionResult has."""
    base = {
        "status": "available", "engine": "jev", "error": None, "direction": direction, "materiality": 1.4,
        "relevant": 0.9, "direction_confidence": 0.8, "content_type": "news_report", "event_type": "other",
        "upcoming_event": 0.1, "sensational": 0.1, "usable_content": 0.95, "materiality_confidence": 0.7,
        "model": "jev-1.13.0", "request_id": "req_1", "question_set_version": "article-v4",
    }
    return SimpleNamespace(**{**base, **fields})


UNAVAILABLE = SimpleNamespace(status="unavailable", engine="unavailable", error="TypeSafeTimeoutError", direction=None, materiality=None)


class Judge:
    def __init__(self, answers=None, default=None) -> None:
        self.answers, self.default, self.asked = answers or {}, default or judged(), []

    def judge_evidence(self, evidence, *, company):
        self.asked.append((evidence["id"], company))
        answer = self.answers.get(evidence["id"], self.default)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_only_unjudged_live_news_is_sent() -> None:
    records = [news("judged"), news("plain", None), news("sample", None, data_mode="sample"), form4("f1", buy=1)]
    judge = Judge()

    updated, stats = judge_missing(records, judge, "Acme Corp")

    assert judge.asked == [("plain", "Acme Corp")]
    assert [e.id for e in updated] == [e.id for e in records]
    assert (stats["unjudged"], stats["asked"], stats["judged"], stats["unavailable"]) == (1, 1, 1, 0)


def test_an_article_is_not_sent_twice_in_one_process() -> None:
    records = [news("a", None), news("b", None)]
    judge, cache = Judge({"b": UNAVAILABLE}), {}

    judge_missing(records, judge, "Acme Corp", cache)
    updated, stats = judge_missing(records, judge, "Acme Corp", cache)

    assert [i for i, _ in judge.asked] == ["a", "b", "b"]  # the unanswered one is asked again, the judged one is not
    assert (stats["from_cache"], stats["asked"], stats["judged"]) == (1, 1, 0)
    assert updated[0].jev["judged_at"] == "decision" and updated[1].jev is None


def test_a_fresh_judgment_is_attached_and_marked_without_touching_the_original() -> None:
    record = news("plain", None)

    updated, _ = judge_missing([record], Judge(default=judged("negative")), "Acme Corp")

    assert record.details == {}
    judgment = updated[0].jev
    assert (judgment["engine"], judgment["judged_at"], judgment["direction"]) == ("jev", "decision", "negative")
    assert (judgment["model"], judgment["request_id"], judgment["question_set_version"]) == ("jev-1.13.0", "req_1", "article-v4")


def test_a_record_jev_does_not_answer_for_stays_unjudged() -> None:
    records = [news("a", None), news("b", None), news("c", None)]
    judge = Judge({"a": UNAVAILABLE, "b": RuntimeError("boom")})

    updated, stats = judge_missing(records, judge, "Acme Corp")

    assert [e.jev is None for e in updated] == [True, True, False]
    assert (stats["judged"], stats["unavailable"]) == (1, 2)
    assert stats["error"]


def test_the_newest_records_are_asked_first_and_the_number_is_bounded() -> None:
    records = [news(f"n{i:02d}", None, hours_ago=i + 1) for i in range(MAX_FRESH_JUDGMENTS + 5)]
    judge = Judge()

    _, stats = judge_missing(records, judge, "Acme Corp")

    assert sorted(i for i, _ in judge.asked) == [f"n{i:02d}" for i in range(MAX_FRESH_JUDGMENTS)]
    assert (stats["unjudged"], stats["asked"]) == (MAX_FRESH_JUDGMENTS + 5, MAX_FRESH_JUDGMENTS)
