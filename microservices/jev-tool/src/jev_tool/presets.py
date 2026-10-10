"""Question wording for repeated judgments, kept in one place.

Bump the version whenever wording or options change, so cached judgments can be invalidated.
The wording is a first draft and has not been tuned against labelled examples.
"""

from collections.abc import Mapping, Sequence

from typesafe_sdk import Choice, Noul, Score

import re

ARTICLE_QUESTION_SET_VERSION = "article-v3"
EXPLANATION_QUESTION_SET_VERSION = "explanation-v1"
MAX_CLAIMS = 12

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


CONTENT_TYPE_OPTIONS = {
    "company_announcement": (
        "Issued by the company itself and written in its own voice: a press release, "
        "promotional material or an official statement."
    ),
    "news_report": (
        "Written by a news outlet reporting on events, including reporting on something "
        "the company announced."
    ),
    "opinion_or_analysis": (
        "A blog post, column, review or analyst commentary that mainly gives the author's "
        "own view or recommendation."
    ),
    "social_media_post": "A short post by an individual on a social media platform or forum.",
    "other": "None of the above, such as an advertisement, a list, or a notice unrelated to business news.",
}


EVENT_TYPE_OPTIONS = {
    "earnings_or_guidance": "Financial results, revenue or profit figures, or the company's own forecast.",
    "legal_or_regulatory": "Lawsuits, fines, rulings, investigations, approvals or government rules.",
    "product_or_service": "A product or service: launches, features, reviews, pricing, promotions or customer experience.",
    "deal_or_partnership": "Acquisitions, mergers, partnerships, supply agreements or major contracts.",
    "management_or_workforce": "Executives, the board, pay, hiring, layoffs or other staffing matters.",
    "operations_or_supply": "Production, deliveries, factories, stores, recalls or supply chain.",
    "market_or_macro": "Industry-wide trends, the economy, or conditions affecting many companies.",
    "stock_or_valuation_view": "Commentary on the share price, valuation, or whether to own the stock.",
    "other": "None of the above.",
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
        "content_type": Choice(
            instructions="What kind of content is the text in `article`?",
            criteria=dict(CONTENT_TYPE_OPTIONS),
        ),
        "event_type": Choice(
            instructions="What is the main subject of the article in `article`?",
            criteria=dict(EVENT_TYPE_OPTIONS),
        ),
        "upcoming_event": Noul(
            instructions=(
                "Does the article in `article` say that a specific scheduled event involving the "
                "company named in `company` is still to come?"
            ),
            criteria={
                "true": (
                    "It names an event that has not happened yet and is planned for a stated or "
                    "approximate time, such as an earnings date, a launch, a vote or a ruling."
                ),
                "false": "It only describes things that have already happened, or gives no planned event.",
            },
        ),
        "materiality": Score(
            instructions="How significant is the event reported in `article` for the company's business?",
            criteria=MATERIALITY_LEVELS,
        ),
    }


def split_sentences(text: str) -> list[str]:
    """Split an explanation into sentences, each checked as one claim."""
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def explanation_state(explanation: str, claims: Sequence[str], evidence: Sequence[Mapping]) -> dict:
    return {
        "evidence": [
            {"id": item.get("id"), "title": item.get("title"), "summary": item.get("summary")}
            for item in evidence
        ],
        "claims": list(claims),
        "explanation": explanation,
    }


def explanation_questions(n_claims: int) -> dict:
    questions: dict = {
        f"claim_{i}": Noul(
            instructions=f"Is the statement in `claims[{i}]` supported by what is reported in `evidence`?",
            criteria={
                "true": "The evidence items state this, or it follows directly from them.",
                "false": "The evidence items do not mention this, or they contradict it.",
            },
        )
        for i in range(n_claims)
    }
    questions["personal_advice"] = Noul(
        instructions=(
            "Does the text in `explanation` directly tell the reader what to do with their own "
            "money or investments?"
        ),
        criteria={
            "true": "It instructs or urges the reader to buy, sell, hold or otherwise act.",
            "false": (
                "It only describes evidence, signals or an assessment, including a stated label "
                "such as 'Assessment: hold', without addressing the reader or telling them to act."
            ),
        },
    )
    questions["promises_outcome"] = Noul(
        instructions=(
            "Does the text in `explanation` present a future price move or financial result as "
            "certain or guaranteed?"
        ),
        criteria={
            "true": "It says a price move, gain, loss or result will happen, or guarantees it.",
            "false": "It makes no prediction, or describes any outlook as uncertain.",
        },
    )
    return questions
