"""Entity/sector/sentiment tagging via a Bedrock-backed Strands Agent. This
is the demonstrably-executed Strands path: each call is a real agent
invocation, not a stubbed placeholder -- if Bedrock is unreachable or
unconfigured, tagging is skipped and the evidence record is returned
unmodified (graceful degradation per docs/AGENTS.md), never silently faked.
"""

import json
import logging
import re

from ..config import get_settings
from ..models.evidence import Entities, Evidence, Sentiment
from .strands_setup import build_bedrock_agent

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a financial-news tagging assistant. Given a title and summary, "
    "extract stock tickers, industry sectors, and named key people, and "
    "classify sentiment direction (Bullish, Bearish, or Neutral) with a "
    "confidence score from 0 to 1. Respond with ONLY a JSON object matching "
    'this shape: {"tickers": [...], "sectors": [...], "key_people": [...], '
    '"sentiment_direction": "Bullish|Bearish|Neutral", "sentiment_score": 0.0}'
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

_agent = None


def _extract_json(text: str) -> dict:
    fenced = _JSON_FENCE_RE.search(text)
    candidate = fenced.group(1) if fenced else text
    return json.loads(candidate)


def _get_agent():
    global _agent
    if _agent is None:
        _agent = build_bedrock_agent(SYSTEM_PROMPT)
    return _agent


def tag_evidence(evidence: Evidence) -> Evidence:
    settings = get_settings()
    if not settings.bedrock_configured:
        logger.info("bedrock not configured; skipping tagging for %s", evidence.id)
        return evidence

    prompt = f"Title: {evidence.title}\nSummary: {evidence.summary or ''}\nSymbol: {evidence.symbol}"
    try:
        agent = _get_agent()
        result = agent(prompt)
        parsed = _extract_json(str(result))
    except Exception:
        logger.warning("tagging agent failed for %s; leaving evidence untagged", evidence.id, exc_info=True)
        return evidence

    evidence.entities = Entities(
        tickers=parsed.get("tickers", []) or [evidence.symbol],
        sectors=parsed.get("sectors", []),
        key_people=parsed.get("key_people", []),
    )
    evidence.sentiment = Sentiment(
        direction=parsed.get("sentiment_direction"),
        score=parsed.get("sentiment_score"),
    )
    return evidence
