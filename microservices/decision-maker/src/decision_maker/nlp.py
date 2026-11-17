"""A local NLP reading of news text: a second reader next to Jev.

The approach follows the "FinBERT funnel" in flash131307/multi-agent-investment
(relevance filter, then a finance-tuned sentence classifier, then a weighted,
deterministic aggregate), adapted to the rules of this package:

- **Jev stays the primary reader.** On the project's 38-item article quiz
  (``jev-tool/evals/article_quiz.json``) FinBERT got 23 of 30 on-topic
  directions right where Jev got 30 of 30, so a reading here never changes the
  weight of a record Jev judged. For such records it is only compared and
  reported (``nlp_cross_check`` on the news leg).
- **It lets unjudged news count.** A record Jev never judged is otherwise left
  out of the news leg. With a usable reading it can vote, at a discount (see
  ``legs.NLP_STORY_WEIGHT``).
- **Relevance comes from the headline.** A classifier cannot tell whether text is
  about the company: it reads a rival's product launch as positive. On the quiz,
  every on-topic headline named the company and 7 of 8 off-topic headlines did
  not, while 6 of 8 off-topic records named it somewhere in their text. So a
  reading is only usable when the headline names the company, and only the
  headline and the sentences that name the company are classified.
- **Unknown is not neutral.** A record with no usable reading carries the reason
  (``not_about_company``, ``sensational``, ``low_confidence``, ...) and never
  votes, rather than voting 0.

With the thresholds below, the quiz gave 20 of 22 usable readings right and no
off-topic record usable. That is a 38-item sanity check, not an accuracy claim.

The classifier is injected (``TextClassifier``). ``HuggingFaceClassifier`` wraps
any Hugging Face text-classification model with positive/negative/neutral
labels, loaded lazily; ``transformers`` and ``torch`` are the optional ``nlp``
extra. Model weights carry their own licence: ``ProsusAI/finbert`` is
CC BY-NC-SA 4.0 (non-commercial).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .models import EvidenceRecord

logger = logging.getLogger(__name__)

READER_VERSION = "nlp-reader-v1"
NEWS_SOURCE_TYPES = frozenset({"general_news", "social_media"})
LABELS = ("positive", "negative", "neutral")

MIN_CONFIDENCE = 0.6
MIN_HEADLINE_WORDS = 4
MAX_SENTENCES = 6
MAX_CACHED_READINGS = 5000

THRESHOLDS = {
    "min_confidence": MIN_CONFIDENCE,
    "min_headline_words": MIN_HEADLINE_WORDS,
    "max_sentences": MAX_SENTENCES,
}

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_SHOUTING = re.compile(r"\b[A-Z]{4,}\b")
_MARKET_WIDE = re.compile(
    r"S&P\b|\bDow\b|\bNasdaq\b|\bRussell 2000\b|\bWall Street\b|(?i:\b(?:stocks|futures|markets)\b)"
)


class TextClassifier(Protocol):
    """Scores each text with a probability for each of ``LABELS``."""

    model: str

    def classify(self, texts: Sequence[str]) -> list[Mapping[str, float]]: ...


class HuggingFaceClassifier:
    """A Hugging Face text-classification pipeline, loaded on first use.

    Raises ``RuntimeError`` from ``classify`` when ``transformers`` is not
    installed or the model does not use positive/negative/neutral labels."""

    def __init__(self, model: str, *, device: str | int | None = None, batch_size: int = 16) -> None:
        self.model = model
        self._device = device
        self._batch_size = batch_size
        self._pipeline = None

    def _load(self):
        if self._pipeline is None:
            try:
                from transformers import pipeline
            except ImportError as exc:
                raise RuntimeError("transformers is not installed; install decision-maker[nlp]") from exc
            self._pipeline = pipeline(
                "text-classification", model=self.model, device=self._device, top_k=None, truncation=True
            )
        return self._pipeline

    def classify(self, texts: Sequence[str]) -> list[Mapping[str, float]]:
        if not texts:
            return []
        rows = self._load()(list(texts), batch_size=self._batch_size)
        scores = [{str(d["label"]).lower(): float(d["score"]) for d in row} for row in rows]
        if any(set(LABELS) - set(row) for row in scores):
            raise RuntimeError(f"model {self.model} does not return positive/negative/neutral labels")
        return scores


def _names_pattern(symbol: str, company: str | None) -> re.Pattern[str]:
    """The ticker, matched case-sensitively (tickers such as T, NOW or IT are also
    ordinary words), or the company name in any case. "Teslas" and "Apple's" count."""
    ticker = re.escape(symbol.strip().upper())
    alternatives = [rf"\b{ticker}\b"]
    if company and company.strip():
        alternatives.append(rf"\b(?i:{re.escape(company.strip())})(?:'s|s)?\b")
    return re.compile("|".join(alternatives))


def is_sensational(title: str, symbol: str) -> bool:
    """The headline rule ``scraper-analysis/pipeline/scoring.py`` uses for its noise
    penalty: an exclamation mark, or two or more ALL-CAPS words other than the ticker."""
    if "!" in title:
        return True
    return len([w for w in _SHOUTING.findall(title) if w != symbol.upper()]) >= 2


def target_sentences(record: EvidenceRecord, pattern: re.Pattern[str]) -> list[str]:
    """The headline, then the summary sentences that name the company."""
    sentences = [record.title.strip()]
    for sentence in _SENTENCE_END.split(record.summary or ""):
        sentence = sentence.strip()
        if sentence and pattern.search(sentence):
            sentences.append(sentence)
    return sentences[:MAX_SENTENCES]


def _others_pattern(symbol: str, company: str | None, others: Mapping[str, str] | None) -> re.Pattern[str] | None:
    """Every other known company, by ticker or name, except names this company shares
    (GOOG and GOOGL are both Alphabet)."""
    own = {symbol.strip().upper(), (company or "").strip().lower()}
    alternatives = []
    for ticker, name in (others or {}).items():
        if ticker.upper() not in own and len(ticker) > 1:
            alternatives.append(rf"\b{re.escape(ticker.upper())}\b")
        if name and name.strip().lower() not in own:
            alternatives.append(rf"\b(?i:{re.escape(name.strip())})(?:'s|s)?\b")
    return re.compile("|".join(alternatives)) if alternatives else None


def _skip_reason(record: EvidenceRecord, pattern: re.Pattern[str], others: re.Pattern[str] | None) -> str | None:
    title = record.title.strip()
    if not pattern.search(title):
        return "not_about_company"
    if len(title.split()) < MIN_HEADLINE_WORDS:
        return "headline_too_short"
    if is_sensational(title, record.symbol):
        return "sensational"
    # Live feeds file market wrap-ups and stories about other companies under every
    # symbol they mention ("Tesla board member says Nvidia should..."): a sentence
    # classifier cannot tell whose news it is, so only single-company headlines are read.
    if others is not None and others.search(title):
        return "names_other_company"
    if _MARKET_WIDE.search(title):
        return "market_wide"
    return None


def _reading(scores: list[Mapping[str, float]], model: str, sentences: int) -> dict[str, Any]:
    mean = {label: sum(float(s.get(label, 0.0)) for s in scores) / len(scores) for label in LABELS}
    direction = max(LABELS, key=lambda label: mean[label])
    confidence = mean[direction]
    reading: dict[str, Any] = {
        "engine": "nlp",
        "version": READER_VERSION,
        "model": model,
        "direction": direction,
        "confidence": round(confidence, 4),
        # -1 to 1: how far the text leans, positive minus negative probability.
        "polarity": round(mean["positive"] - mean["negative"], 4),
        "probabilities": {label: round(value, 4) for label, value in mean.items()},
        "sentences": sentences,
        "usable": confidence >= MIN_CONFIDENCE,
    }
    if not reading["usable"]:
        reading["skip_reason"] = "low_confidence"
    return reading


def read_articles(
    evidence: list[EvidenceRecord],
    classifier: TextClassifier,
    *,
    symbol: str,
    company: str | None = None,
    other_companies: Mapping[str, str] | None = None,
    cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[EvidenceRecord], dict[str, Any]]:
    """Return the records with ``details["nlp"]`` attached to news items, and what
    happened. ``other_companies`` maps other tickers to names: a headline naming one
    of them is not read. ``cache`` maps an evidence id to a reading made earlier in
    this process.

    One batched classifier call covers every record not in the cache. If it raises,
    no record gets a reading and ``stats["error"]`` says so: the assessment goes on
    without the NLP reader, exactly as if it were off."""
    cache = cache if cache is not None else {}
    pattern = _names_pattern(symbol, company)
    others = _others_pattern(symbol, company, other_companies)
    news =[e for e in evidence if e.source_type in NEWS_SOURCE_TYPES]
    stats: dict[str, Any] = {
        "model": classifier.model,
        "records": len(news),
        "from_cache": 0,
        "classified": 0,
        "usable": 0,
        "skipped": {},
        "error": None,
    }

    fresh: dict[str, dict[str, Any]] = {}
    to_classify: list[tuple[EvidenceRecord, list[str]]] = []
    for record in news:
        if record.id in cache:
            stats["from_cache"] += 1
            continue
        reason = _skip_reason(record, pattern, others)
        if reason:
            fresh[record.id] = {
                "engine": "nlp",
                "version": READER_VERSION,
                "model": classifier.model,
                "usable": False,
                "skip_reason": reason,
            }
        else:
            to_classify.append((record, target_sentences(record, pattern)))

    if to_classify:
        flat = [sentence for _, sentences in to_classify for sentence in sentences]
        try:
            scores = classifier.classify(flat)
            if len(scores) != len(flat):
                raise RuntimeError(f"classifier returned {len(scores)} results for {len(flat)} texts")
        except Exception as exc:
            logger.warning("NLP reader failed: %s", type(exc).__name__)
            stats["error"] = f"classifier failed: {type(exc).__name__}"
            return evidence, stats
        start = 0
        for record, sentences in to_classify:
            fresh[record.id] = _reading(scores[start : start + len(sentences)], classifier.model, len(sentences))
            start += len(sentences)
        stats["classified"] = len(to_classify)

    readings = {e.id: fresh.get(e.id) or cache[e.id] for e in news if e.id in fresh or e.id in cache}
    if len(cache) + len(fresh) > MAX_CACHED_READINGS:
        cache.clear()
    cache.update(fresh)

    for reading in readings.values():
        if reading.get("usable"):
            stats["usable"] += 1
        else:
            reason = reading.get("skip_reason", "unknown")
            stats["skipped"][reason] = stats["skipped"].get(reason, 0) + 1

    def with_reading(record: EvidenceRecord) -> EvidenceRecord:
        reading = readings.get(record.id)
        if reading is None:
            return record
        return record.model_copy(update={"details": {**record.details, "nlp": reading}})

    return [with_reading(e) for e in evidence], stats
