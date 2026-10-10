"""Question wording for repeated judgments, kept in one place.

Bump the version whenever wording or options change, so cached judgments can be invalidated.
The wording is a first draft and has not been tuned against labelled examples.
"""

from collections.abc import Sequence

from typesafe_sdk import Choice, Noul, Score

ARTICLE_QUESTION_SET_VERSION = "article-v1"

MATERIALITY_LEVELS = ["routine or promotional", "notable", "major"]


def article_state(symbol: str, company: str, title: str, summary: str) -> dict:
    return {
        "company": {"name": company, "ticker": symbol},
        "article": {"title": title, "summary": summary},
    }


DIRECTION_OPTIONS = {
    "negative": "Reports bad news for the company's business.",
    "neutral": "Reports nothing clearly good or bad for the company's business.",
    "positive": "Reports good news for the company's business.",
    "mixed": "Reports both clearly good and clearly bad news for the company's business.",
}


def article_questions(direction_order: Sequence[str] | None = None) -> dict:
    """`direction_order` only changes the order the options are listed in (used by evals)."""
    direction_criteria = {name: DIRECTION_OPTIONS[name] for name in direction_order or DIRECTION_OPTIONS}
    return {
        "relevant": Noul(
            instructions="Is the article in `article` primarily about the company named in `company`?",
            criteria={
                "true": "The company is the main subject of the article.",
                "false": "The company is only mentioned in passing, or the article is about a different company.",
            },
        ),
        "direction": Choice(
            instructions=(
                "For the company in `company`, what does the article in `article` report "
                "about its business outlook?"
            ),
            criteria=direction_criteria,
        ),
        "materiality": Score(
            instructions="How significant is the event reported in `article` for the company's business?",
            criteria=MATERIALITY_LEVELS,
        ),
    }
