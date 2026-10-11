import pytest

from decision_maker.combiner import BASE_THRESHOLD, RAISED_THRESHOLD, combine
from decision_maker.models import QuantReading

from factories import legs

NO_QUANT = QuantReading()


def test_no_evidence_is_insufficient_data_with_the_contract_reason() -> None:
    decision = combine(legs(price_dir=1.0), NO_QUANT, has_evidence=False)

    assert decision.label == "insufficient_data"
    assert decision.reason_codes == ["missing_attributable_evidence"]
    assert decision.net_direction is None


def test_a_single_usable_leg_is_not_enough() -> None:
    decision = combine(legs(news_dir=0.9), NO_QUANT, has_evidence=True)

    assert decision.label == "insufficient_data"
    assert decision.reason_codes == ["insufficient_direction_signals"]


@pytest.mark.parametrize(
    ("directions", "label", "net"),
    [
        ({"news_dir": 0.8, "insider": 1.0, "price_dir": 1.0, "congress": 1.0}, "buy", 0.92),
        ({"news_dir": -0.8, "insider": -1.0, "price_dir": -1.0}, "sell", -0.9111),
        ({"news_dir": 0.6, "insider": -1.0, "price_dir": 1.0}, "hold", 0.1556),
        ({"news_dir": 0.0, "price_dir": 0.0}, "hold", 0.0),
        # Weights are renormalised over the legs that have data.
        ({"news_dir": 0.5, "price_dir": 0.0}, "buy", 0.3333),
        ({"insider": -1.0, "congress": 1.0}, "sell", -0.5),
    ],
)
def test_label_follows_the_weighted_direction(directions: dict, label: str, net: float) -> None:
    decision = combine(legs(**directions), NO_QUANT, has_evidence=True)

    assert decision.label == label
    assert decision.net_direction == pytest.approx(net, abs=1e-4)
    assert decision.threshold == BASE_THRESHOLD


@pytest.mark.parametrize(
    ("reading", "reason"),
    [
        (QuantReading(status="used", priced_volatility="high"), "priced_volatility_high"),
        (QuantReading(status="used", skew="steep"), "skew_steep"),
        (QuantReading(status="used", term_structure="inverted"), "term_structure_inverted"),
    ],
)
def test_options_readings_raise_the_bar_but_never_set_direction(reading: QuantReading, reason: str) -> None:
    directions = {"news_dir": 0.5, "price_dir": 0.0}  # net 0.33: a buy at the base threshold

    assert combine(legs(**directions), NO_QUANT, has_evidence=True).label == "buy"
    decision = combine(legs(**directions), reading, has_evidence=True)
    assert decision.label == "hold"
    assert decision.threshold == RAISED_THRESHOLD
    assert decision.threshold_raised_by == [reason]
    # The same reading cannot push an already-negative mix anywhere but hold or sell.
    assert combine(legs(news_dir=-0.5, price_dir=0.0), reading, has_evidence=True).label == "hold"
    assert combine(legs(news_dir=-0.9, price_dir=-1.0), reading, has_evidence=True).label == "sell"


def test_thin_options_data_is_not_acted_on() -> None:
    thin = QuantReading(status="thin", priced_volatility="high", skew="steep", term_structure="inverted")

    decision = combine(legs(news_dir=0.5, price_dir=0.0), thin, has_evidence=True)

    assert decision.threshold == BASE_THRESHOLD
    assert decision.label == "buy"


def test_an_upcoming_event_in_the_news_raises_the_bar() -> None:
    decision = combine(legs(news_dir=0.5, price_dir=0.0, upcoming_event_ids=["n9"]), NO_QUANT, has_evidence=True)

    assert decision.label == "hold"
    assert decision.threshold_raised_by == ["upcoming_event_in_news"]
    assert "n9" in decision.reason_codes


def test_reason_codes_are_the_records_behind_the_label() -> None:
    reading = QuantReading(status="used", skew="steep", signal_ids={"skew": "q-skew", "implied_move": "q-move"})
    buy = combine(legs(news_dir=0.9, insider=1.0, price_dir=1.0, congress=-1.0), reading, has_evidence=True)
    hold = combine(legs(news_dir=0.3, insider=-1.0, price_dir=1.0), reading, has_evidence=True)

    assert buy.label == "buy"
    assert buy.reason_codes == ["n1", "n2", "f1", "p1", "q-skew"]  # the opposing congress leg is not a reason to buy
    assert hold.reason_codes == ["n1", "n2", "f1", "p1", "q-skew"]


def test_opposing_legs_are_named_as_conflicts() -> None:
    decision = combine(legs(news_dir=0.6, insider=-1.0, price_dir=1.0, congress=0.0), NO_QUANT, has_evidence=True)

    assert decision.conflicts == ["news (positive) against insider (negative)", "insider (negative) against price (positive)"]


def test_the_same_inputs_always_give_the_same_decision() -> None:
    make = lambda: combine(legs(news_dir=0.4, insider=1.0, price_dir=-1.0), NO_QUANT, has_evidence=True)  # noqa: E731

    assert make() == make()
