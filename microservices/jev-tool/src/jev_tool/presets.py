"""Question wording for repeated judgments, kept in one place.

Bump the version whenever wording or options change, so cached judgments can be invalidated.
The wording is a first draft and has not been tuned against labelled examples.
"""

from typesafe_sdk import Choice, Noul, Score

ARTICLE_QUESTION_SET_VERSION = "article-v1"

MATERIALITY_LEVELS = ["routine or promotional", "notable", "major"]


def article_state(symbol: str, company: str, title: str, summary: str) -> dict:
    return {
        "company": {"name": company, "ticker": symbol},
        "article": {"title": title, "summary": summary},
    }


def article_questions() -> dict:
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
            criteria={
                "negative": "Reports bad news for the company's business.",
                "neutral": "Reports nothing clearly good or bad for the company's business.",
                "positive": "Reports good news for the company's business.",
                "mixed": "Reports both clearly good and clearly bad news for the company's business.",
            },
        ),
        "materiality": Score(
            instructions="How significant is the event reported in `article` for the company's business?",
            criteria=MATERIALITY_LEVELS,
        ),
    }
