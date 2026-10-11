import pytest

from decision_maker.legs import congress_leg, current_strength, in_window, insider_leg, is_gated, news_leg, price_leg, strength

from factories import NOW, form4, news, price, senate


def test_window_drops_old_and_undated_records() -> None:
    recent, old = news("recent", hours_ago=24), news("old", hours_ago=24 * 60)
    undated = news("undated").model_copy(update={"published_at": None, "observed_at": None})

    kept, excluded = in_window([recent, old, undated], NOW)

    assert [e.id for e in kept] == ["recent"]
    assert excluded == {"undated": 1, "outside_window": 1}


def test_news_leg_needs_three_on_topic_stories() -> None:
    leg = news_leg([news("a"), news("b")], NOW)

    assert leg.direction is None
    assert leg.inputs["stories_used"] == 2


def test_news_leg_reads_weighted_tone() -> None:
    positive = news_leg([news("a"), news("b"), news("c")], NOW)
    negative = news_leg([news("a", "negative"), news("b", "negative"), news("c", "neutral")], NOW)
    mixed = news_leg([news("a", "positive"), news("b", "negative"), news("c", "mixed")], NOW)

    assert (positive.direction, positive.reading) == (1.0, "positive")
    assert negative.reading == "negative" and negative.direction < -0.25
    assert mixed.reading == "mixed_or_neutral" and abs(mixed.direction) < 0.25
    assert positive.record_ids == ["a", "b", "c"]


def test_off_topic_and_unusable_records_do_not_count() -> None:
    off_topic = news("off", "negative", relevant=0.1)
    junk = news("junk", "negative", usable_content=0.2)
    leg = news_leg([news("a"), news("b"), news("c"), off_topic, junk], NOW)

    assert is_gated(off_topic) and is_gated(junk)
    assert leg.direction == 1.0
    assert leg.inputs["records_gated"] == 2
    assert "off" not in leg.record_ids


def test_a_stored_grade_decides_gating_and_strength() -> None:
    graded = news("g", relevant=0.9)
    graded.details["grade"] = {"basis": "jev", "strength": 0.123, "gated": True, "gate_reasons": ["off_topic"]}

    assert is_gated(graded)
    assert strength(graded) == 0.123


def test_one_event_repeated_by_several_outlets_counts_once() -> None:
    first = news("a", same_story_as=["b", "c"])
    echoes = [news("b", same_story_as=["a"]), news("c", same_story_as=["a"])]

    leg = news_leg([first, *echoes, news("d")], NOW)

    assert leg.inputs["stories_used"] == 2
    assert leg.direction is None


def test_unjudged_news_is_counted_but_never_given_a_direction() -> None:
    unavailable = news("u", None)
    unavailable.details["jev"] = {"engine": "unavailable", "error": "timeout"}
    leg = news_leg([news("a"), news("b"), news("c"), news("plain", None), unavailable], NOW)

    assert leg.inputs["records_unjudged"] == 2
    assert leg.record_ids == ["a", "b", "c"]
    assert strength(unavailable) is None


def test_a_fixture_judgment_counts_only_on_a_sample_record() -> None:
    labelled_sample = news("s", engine="fixture", data_mode="sample")
    mislabelled_live = news("l", engine="fixture", data_mode="live")

    assert labelled_sample.jev is not None
    assert mislabelled_live.jev is None


def test_older_news_weighs_less() -> None:
    assert current_strength(news("new", hours_ago=1), NOW) > current_strength(news("old", hours_ago=72), NOW)
    assert current_strength(news("old", hours_ago=72), NOW) == pytest.approx(strength(news("old")) * 0.5)


def test_upcoming_events_are_surfaced_for_the_combiner() -> None:
    leg = news_leg([news("a"), news("b"), news("c", "neutral", upcoming_event=0.9)], NOW)

    assert leg.inputs["upcoming_event_ids"] == ["c"]


@pytest.mark.parametrize(
    ("buy", "sell", "direction", "reading"),
    [(500_000, 0, 1.0, "buying"), (0, 500_000, -1.0, "selling"), (60_000, 0, 0.0, "neutral"), (100_000, 0, 1.0, "buying")],
)
def test_insider_leg_nets_discretionary_trades(buy: float, sell: float, direction: float, reading: str) -> None:
    leg = insider_leg([form4("f1", buy=buy, sell=sell)])

    assert (leg.direction, leg.reading) == (direction, reading)
    assert leg.record_ids == ["f1"]


def test_pre_scheduled_sales_are_excluded_from_insider_direction() -> None:
    only_planned = insider_leg([form4("p", sell=900_000, planned=True)])
    with_buy = insider_leg([form4("p", sell=900_000, planned=True), form4("d", buy=200_000)])

    assert only_planned.direction is None
    assert only_planned.inputs["pre_scheduled_sell_usd"] == 900_000
    assert (with_buy.direction, with_buy.record_ids) == (1.0, ["d"])


def test_insider_leg_without_trades_is_unusable() -> None:
    assert insider_leg([news("a")]).direction is None
    assert insider_leg([form4("empty")]).direction is None


def test_congress_leg_compares_purchases_and_sales() -> None:
    assert congress_leg([senate("a"), senate("b"), senate("c", "Sale (Full)")]).reading == "buying"
    assert congress_leg([senate("a", "Sale (Partial)")]).direction == -1.0
    assert congress_leg([senate("a"), senate("b", "Sale")]).reading == "mixed"
    assert congress_leg([senate("a", "Exchange")]).direction is None


@pytest.mark.parametrize(("change", "reading"), [(5.0, "up"), (4.9, "flat"), (-4.9, "flat"), (-5.0, "down")])
def test_price_leg_thresholds(change: float, reading: str) -> None:
    assert price_leg([price(change)]).reading == reading


def test_price_leg_uses_the_newest_signal() -> None:
    leg = price_leg([price(-9.0, "old", hours_ago=48), price(7.0, "new", hours_ago=2)])

    assert (leg.reading, leg.record_ids) == ("up", ["new"])
    assert price_leg([]).direction is None
