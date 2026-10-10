"""Applies the README's credibility formula (pipeline/credibility.py) to a
batch of evidence.

What each term really is -- these are heuristics, not validated measures:
- S_domain: a hand-set authority prior per outlet (table below). Unknown
  outlets get a neutral 0.5; social posts get 0.3.
- S_author: no per-author track record exists in the data we collect, so
  this is a constant neutral 0.5. It is documented as a placeholder rather
  than pretending to measure something.
- S_consensus: corroboration across *independent* sources in the same
  batch, via title-token overlap (Jaccard). Only items in the batch being
  scored can corroborate each other -- stored history is not consulted.
- P_noise: a small penalty for sensational titles (exclamation marks,
  repeated ALL-CAPS words other than the ticker).

Official filings (SEC, Senate eFD) are left untouched: their credibility is
definitional (verified_filing=True, score 1.0), not estimated.
"""

import re

from ..models.evidence import Evidence
from .credibility import credibility_score

SOURCE_AUTHORITY: dict[str, float] = {
    "cnbc": 0.85,
    "marketwatch": 0.8,
    "yahoo finance": 0.75,
    "seeking alpha": 0.6,
}
DEFAULT_NEWS_AUTHORITY = 0.5
SOCIAL_AUTHORITY = 0.3
NEUTRAL_AUTHOR_SCORE = 0.5

CONSENSUS_JACCARD_THRESHOLD = 0.4
CORROBORATING_SOURCES_FOR_FULL_CONSENSUS = 2
SENSATIONAL_PENALTY = 0.1

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "at", "by",
    "with", "as", "is", "are", "after", "from", "its", "this", "that", "new",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def domain_authority(evidence: Evidence) -> float:
    if evidence.source_type == "social_media":
        return SOCIAL_AUTHORITY
    return SOURCE_AUTHORITY.get(evidence.source_name.lower(), DEFAULT_NEWS_AUTHORITY)


def noise_penalty(evidence: Evidence) -> float:
    title = evidence.title
    if "!" in title:
        return SENSATIONAL_PENALTY
    shouting = [
        w for w in re.findall(r"\b[A-Z]{4,}\b", title) if w != evidence.symbol.upper()
    ]
    return SENSATIONAL_PENALTY if len(shouting) >= 2 else 0.0


def consensus_scores(items: list[Evidence]) -> list[float]:
    token_sets = [_tokens(f"{e.title} {e.summary or ''}") for e in items]
    scores = []
    for i, item in enumerate(items):
        corroborating = {
            items[j].source_name
            for j in range(len(items))
            if j != i
            and items[j].source_name != item.source_name
            and _jaccard(token_sets[i], token_sets[j]) >= CONSENSUS_JACCARD_THRESHOLD
        }
        scores.append(min(1.0, len(corroborating) / CORROBORATING_SOURCES_FOR_FULL_CONSENSUS))
    return scores


def apply_credibility(items: list[Evidence]) -> None:
    consensus = consensus_scores(items)
    for item, s_consensus in zip(items, consensus):
        if item.credibility.verified_filing:
            continue
        s_domain = domain_authority(item)
        item.credibility.source_reliability_weight = s_domain
        item.credibility.overall_score = round(
            credibility_score(
                domain_score=s_domain,
                author_score=NEUTRAL_AUTHOR_SCORE,
                consensus_score=s_consensus,
                noise_penalty=noise_penalty(item),
            ),
            4,
        )
