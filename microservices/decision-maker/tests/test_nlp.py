"""The local NLP reader (nlp.py) and how its readings count in the news leg.
A keyword classifier stands in for the model: no network, no torch."""

from decision_maker import DecisionMaker, DecisionRequest
from decision_maker.legs import NLP_STORY_WEIGHT, news_leg, strength
from decision_maker.nlp import read_articles

from factories import NOW, ListSource, form4, news, price


class Keywords:
    """positive for "beats", negative for "misses", neutral otherwise; "unsure" is a coin flip."""

    model = "test-keywords"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[list[str]] = []

    def classify(self, texts):
        self.calls.append(list(texts))
        if self.error:
            raise self.error
        out = []
        for text in texts:
            lower = text.lower()
            if "unsure" in lower:
                out.append({"positive": 0.4, "negative": 0.3, "neutral": 0.3})
            elif "beats" in lower:
                out.append({"positive": 0.9, "negative": 0.05, "neutral": 0.05})
            elif "misses" in lower:
                out.append({"positive": 0.05, "negative": 0.9, "neutral": 0.05})
            else:
                out.append({"positive": 0.05, "negative": 0.05, "neutral": 0.9})
        return out


def unjudged(record_id: str, title: str, summary: str | None = None, **kwargs):
    record = news(record_id, None, title=title, **kwargs)
    return record if summary is None else record.model_copy(update={"summary": summary})


def read(records, classifier=None, cache=None):
    return read_articles(records, classifier or Keywords(), symbol="ACME", company="Acme", cache=cache)


def test_only_headlines_that_name_the_company_are_read() -> None:
    about = unjudged("a", "Acme beats quarterly forecasts")
    passing = unjudged("b", "Rival beats forecasts as industry grows", "Analysts compared it with Acme.")

    records, stats = read([about, passing])

    assert records[0].details["nlp"]["direction"] == "positive" and records[0].details["nlp"]["usable"]
    assert records[1].details["nlp"] == {
        "engine": "nlp", "version": "nlp-reader-v1", "model": "test-keywords", "usable": False, "skip_reason": "not_about_company",
    }
    assert stats["usable"] == 1 and stats["skipped"] == {"not_about_company": 1}


def test_a_ticker_that_is_also_a_word_only_matches_in_capitals() -> None:
    def about(symbol, company, title):
        record = unjudged("a", title).model_copy(update={"symbol": symbol})
        [out], _ = read_articles([record], Keywords(), symbol=symbol, company=company)
        return out.details["nlp"].get("skip_reason") != "not_about_company"

    assert not about("T", "AT&T", "Why markets don't care about rates today")
    assert about("T", "AT&T", "T beats estimates on wireless subscriber growth")
    assert about("T", "AT&T", "at&t beats estimates on wireless subscriber growth")
    assert not about("NOW", "ServiceNow", "Stocks now beat estimates across the board")
    assert about("NOW", "ServiceNow", "ServiceNow's quarter beats estimates on demand")


def test_only_the_headline_and_sentences_naming_the_company_are_classified() -> None:
    record = unjudged("a", "Acme beats forecasts again this year", "A rival misses badly. Acme's margins beats estimates.")
    classifier = Keywords()

    read([record], classifier)

    assert classifier.calls == [["Acme beats forecasts again this year", "Acme's margins beats estimates."]]


def test_sensational_short_and_unsure_text_never_votes() -> None:
    loud = unjudged("loud", "ACME STOCK beats everything, BELIEVE it")
    short = unjudged("short", "Acme")
    unsure = unjudged("unsure", "Acme outlook unsure after the meeting")

    records, stats = read([loud, short, unsure])

    assert [r.details["nlp"].get("skip_reason") for r in records] == ["sensational", "headline_too_short", "low_confidence"]
    assert stats["usable"] == 0
    assert all(strength(r) is None for r in records)


def test_a_failing_model_leaves_every_record_without_a_reading() -> None:
    records, stats = read([unjudged("a", "Acme beats quarterly forecasts")], Keywords(error=OSError("no weights")))

    assert "nlp" not in records[0].details
    assert stats["error"] == "classifier failed: OSError"


def test_readings_are_cached_by_evidence_id() -> None:
    cache: dict = {}
    classifier = Keywords()
    record = unjudged("a", "Acme beats quarterly forecasts")

    read([record], classifier, cache)
    records, stats = read([record], classifier, cache)

    assert len(classifier.calls) == 1
    assert stats["from_cache"] == 1 and records[0].details["nlp"]["direction"] == "positive"


def test_three_nlp_only_stories_give_a_news_reading_at_a_discount() -> None:
    records, _ = read([
        unjudged("a", "Acme beats first quarter forecasts"),
        unjudged("b", "Acme beats analyst estimates on cloud"),
        unjudged("c", "Acme names a new finance chief today"),
    ])
    leg = news_leg(records, NOW)

    assert leg.reading == "positive" and leg.direction > 0.25
    assert leg.inputs["stories_by_reader"] == {"jev": 0, "nlp": 3}
    assert "read only by the local NLP model" in leg.summary
    # credibility 0.8 x weight x confidence 0.9, against a Jev story of about 0.61.
    assert strength(records[0]) == 0.8 * NLP_STORY_WEIGHT * 0.9
    assert strength(records[0]) < strength(news("jev"))


def test_without_readings_unjudged_news_still_never_counts() -> None:
    leg = news_leg([unjudged("a", "Acme beats forecasts"), news("b"), news("c")], NOW)

    assert leg.direction is None and leg.inputs["stories_used"] == 2
    assert "stories_by_reader" not in leg.inputs


def test_a_jev_judgment_always_wins_and_disagreement_is_only_reported() -> None:
    judged = [news(i, "negative", title=f"Acme misses target {i}") for i in "abc"]
    judged[0] = news("a", "negative", title="Acme beats the street but cuts its outlook")
    plain = news_leg(judged, NOW)

    records, _ = read(judged)
    leg = news_leg(records, NOW)

    assert leg.direction == plain.direction == -1.0
    assert leg.inputs["stories_by_reader"] == {"jev": 3, "nlp": 0}
    assert leg.inputs["backs_label"] is True
    assert leg.inputs["nlp_cross_check"] == {"compared": 3, "agreed": 2, "disagreed_ids": ["a"]}


def test_a_repeated_headline_counts_once() -> None:
    records, _ = read([
        unjudged("a", "Acme beats first quarter forecasts"),
        unjudged("b", "Acme beats first quarter forecasts, shares up"),
        news("c", title="Acme opens a plant"),
        news("d", title="Acme hires engineers"),
    ])
    leg = news_leg(records, NOW)

    assert leg.inputs["stories_by_reader"] == {"jev": 2, "nlp": 1}
    assert leg.inputs["stories_used"] == 3


def test_news_confidence_falls_when_stories_disagree_or_are_few() -> None:
    agreeing = news_leg([news(i) for i in "abcdefghij"], NOW)
    split = news_leg([news(i, "positive" if i in "abcdefg" else "negative") for i in "abcdefghij"], NOW)
    few = news_leg([news(i) for i in "abc"], NOW)

    assert agreeing.inputs["agreement"] == 1.0 and agreeing.inputs["coverage"] == 1.0
    assert agreeing.inputs["confidence"] == 1.0
    assert split.inputs["agreement"] < 1.0 and split.inputs["confidence"] < agreeing.inputs["confidence"]
    assert few.inputs["coverage"] == 0.3 and few.inputs["confidence"] == 0.3


def test_the_service_reads_unjudged_news_and_says_so() -> None:
    evidence = [
        unjudged("a", "Acme beats first quarter forecasts"),
        unjudged("b", "Acme beats analyst estimates on cloud"),
        unjudged("c", "Acme names a new finance chief today"),
        form4("f1", buy=500_000),
    ]
    request = DecisionRequest(symbol="ACME")
    without = DecisionMaker(evidence_source=ListSource(evidence, [price(6.0)]), clock=lambda: NOW).decide(request)
    with_nlp = DecisionMaker(
        evidence_source=ListSource(evidence, [price(6.0)]), clock=lambda: NOW, companies={"ACME": "Acme"}, text_classifier=Keywords()
    ).decide(request)

    assert "news" not in without.meta["decision_trace"]["usable_legs"]
    assert "news" in with_nlp.meta["decision_trace"]["usable_legs"]
    # The label is backed by the insider and price legs either way; NLP-only news cannot back it.
    news_leg_inputs = next(l for l in with_nlp.meta["decision_trace"]["legs"] if l["name"] == "news")["inputs"]
    assert news_leg_inputs["backs_label"] is False
    assert with_nlp.assessment.label == without.assessment.label == "buy"
    assert with_nlp.meta["nlp_readings"]["usable"] == 3
    assert "read only by a local sentiment model" in with_nlp.assessment.uncertainty
    assert "left out of the news reading" not in with_nlp.assessment.uncertainty


def test_the_service_goes_on_without_a_failing_model() -> None:
    evidence = [unjudged("a", "Acme beats first quarter forecasts"), form4("f1", buy=500_000)]
    response = DecisionMaker(
        evidence_source=ListSource(evidence, [price(6.0)]), clock=lambda: NOW, companies={"ACME": "Acme"}, text_classifier=Keywords(error=OSError())
    ).decide(DecisionRequest(symbol="ACME"))

    assert "nlp_reader_unavailable" in [w.code for w in response.warnings]
    assert response.assessment.label in {"buy", "hold", "sell"}


def test_the_agent_sees_an_nlp_direction_labelled_but_not_its_numbers() -> None:
    from decision_maker.explain import _evidence_row

    [read_only, skipped], _ = read([unjudged("a", "Acme beats first quarter forecasts"), unjudged("b", "Rival beats forecasts")])

    row = _evidence_row(read_only, NOW)
    assert (row["reported_direction"], row["direction_read_by"]) == ("positive", "local sentiment model")
    assert "details" not in row
    assert "reported_direction" not in _evidence_row(skipped, NOW)


def test_headlines_about_other_companies_or_the_whole_market_are_not_read() -> None:
    others = {"NVDA": "Nvidia", "AMZN": "Amazon", "GOOG": "Alphabet", "ACME2": "Acme", "F": "Ford"}
    records = [
        unjudged("a", "Acme board member says Nvidia should reinstate its CEO"),
        unjudged("b", "Your fund holds Amazon and Acme in one basket"),
        unjudged("c", "Asia stocks slide as Acme results loom"),
        unjudged("d", "S&P 500 ends lower ahead of Acme earnings"),
        unjudged("e", "Acme beats forecasts as the F-150 rival ships"),
    ]
    out, _ = read_articles(records, Keywords(), symbol="ACME", company="Acme", other_companies=others)

    assert [r.details["nlp"].get("skip_reason") for r in out] == [
        "names_other_company", "names_other_company", "market_wide", "market_wide", None,
    ]
