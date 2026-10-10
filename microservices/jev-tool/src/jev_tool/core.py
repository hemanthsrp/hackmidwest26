"""Python face of the shared Jev tool.

Every result carries `engine`: "jev" when the answer came from the TypeSafe API, or
"unavailable" (with `error`) when Jev is switched off or the call failed. The tool never
substitutes an answer of its own; callers decide what to do without one.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from pydantic import BaseModel
from typesafe_sdk import (
    Choice,
    Noul,
    RetryPolicy,
    Score,
    TypeSafeAPIError,
    TypeSafeClient,
    TypeSafeError,
)

from . import presets
from .env import load_env

logger = logging.getLogger("jev_tool")

Engine = Literal["jev", "unavailable"]

DEFAULT_MODEL = "jev-1.13.0"


class _Result(BaseModel):
    engine: Engine = "unavailable"
    model: str | None = None
    request_id: str | None = None
    input_tokens: int | None = None
    error: str | None = None


class CheckResult(_Result):
    """Answer to a yes/no question. `probability` is the chance the statement is true."""

    probability: float | None = None


class ClassifyResult(_Result):
    choice: str | None = None
    probabilities: dict[str, float] = {}
    confidence: float | None = None


class ScoreResult(_Result):
    """`score` is the probability-weighted position in `levels`, counted from 0."""

    score: float | None = None
    levels: list[str] = []
    probabilities: dict[str, float] = {}
    confidence: float | None = None


class EvaluateResult(_Result):
    answers: dict[str, dict[str, Any]] = {}


class ArticleJudgment(_Result):
    question_set_version: str = presets.ARTICLE_QUESTION_SET_VERSION
    evidence_id: str | None = None
    relevant: float | None = None
    direction: str | None = None
    direction_probabilities: dict[str, float] = {}
    direction_confidence: float | None = None
    content_type: str | None = None
    content_type_probabilities: dict[str, float] = {}
    content_type_confidence: float | None = None
    event_type: str | None = None
    event_type_probabilities: dict[str, float] = {}
    event_type_confidence: float | None = None
    upcoming_event: float | None = None
    materiality: float | None = None
    materiality_levels: list[str] = presets.MATERIALITY_LEVELS
    materiality_confidence: float | None = None


class ClaimCheck(BaseModel):
    text: str
    supported: float


class ExplanationCheck(_Result):
    """Probabilities, not verdicts: the caller chooses the thresholds."""

    question_set_version: str = presets.EXPLANATION_QUESTION_SET_VERSION
    claims: list[ClaimCheck] = []
    claims_truncated: bool = False
    personal_advice: float | None = None
    promises_outcome: float | None = None


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


class JevTool:
    """Thread-safe wrapper around one reused TypeSafe client."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        max_concurrency: int | None = None,
        client: Any | None = None,
    ) -> None:
        self.enabled = _env_flag("JEV_ENABLED") if enabled is None else enabled
        self.model = model or os.environ.get("JEV_MODEL") or DEFAULT_MODEL
        self.timeout = timeout if timeout is not None else float(os.environ.get("JEV_TIMEOUT_SECONDS", "5"))
        self.max_retries = (
            max_retries if max_retries is not None else int(os.environ.get("JEV_MAX_RETRIES", "2"))
        )
        self.max_concurrency = max_concurrency or int(os.environ.get("JEV_MAX_CONCURRENCY", "8"))
        self._client = client
        self._lock = threading.Lock()

    def _get_client(self) -> Any:
        with self._lock:
            if self._client is None:
                self._client = TypeSafeClient(
                    model=self.model,
                    timeout=self.timeout,
                    retry=RetryPolicy(max_retries=self.max_retries),
                )
            return self._client

    def _call(self, state: Any, questions: Mapping[str, Any]) -> tuple[Any | None, dict[str, Any]]:
        """Return (response, metadata). Response is None when Jev did not answer."""
        if not self.enabled:
            return None, {"engine": "unavailable", "error": "Jev is disabled (JEV_ENABLED is not true)."}
        started = time.perf_counter()
        try:
            response = self._get_client().system_one(state=state, questions=questions)
        except TypeSafeAPIError as exc:
            error = f"{type(exc).__name__} (HTTP {exc.status})"
            logger.warning("jev call failed: %s request_id=%s", error, exc.request_id)
            return None, {"engine": "unavailable", "error": error, "request_id": exc.request_id}
        except TypeSafeError as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("jev call failed: %s", error)
            return None, {"engine": "unavailable", "error": error}
        request_id = getattr(response, "request_id", None)
        logger.info(
            "jev call ok model=%s request_id=%s input_tokens=%s ms=%.0f",
            response.model,
            request_id,
            response.usage.input_tokens,
            (time.perf_counter() - started) * 1000,
        )
        return response, {
            "engine": "jev",
            "model": response.model,
            "request_id": request_id,
            "input_tokens": response.usage.input_tokens,
        }

    def check(
        self,
        text: str,
        statement: str,
        true_means: str | None = None,
        false_means: str | None = None,
    ) -> CheckResult:
        """Yes/no: how likely is `statement` to be true of `text`?"""
        criteria = {"true": true_means, "false": false_means} if (true_means or false_means) else None
        response, meta = self._call({"text": text}, {"q": Noul(instructions=statement, criteria=criteria)})
        if response is None:
            return CheckResult(**meta)
        return CheckResult(probability=response.nouls["q"].noul, **meta)

    def classify(self, text: str, instructions: str, options: Mapping[str, str | None]) -> ClassifyResult:
        """Pick one of `options` (name -> description or None) for `text`."""
        response, meta = self._call(
            {"text": text}, {"q": Choice(instructions=instructions, criteria=dict(options))}
        )
        if response is None:
            return ClassifyResult(**meta)
        answer = response.choices["q"]
        return ClassifyResult(
            choice=answer.choice, probabilities=answer.probabilities, confidence=answer.confidence, **meta
        )

    def score(self, text: str, instructions: str, levels: Sequence[str]) -> ScoreResult:
        """Rate `text` on `levels`, ordered from lowest to highest (2 to 10 levels)."""
        levels = list(levels)
        response, meta = self._call({"text": text}, {"q": Score(instructions=instructions, criteria=levels)})
        if response is None:
            return ScoreResult(levels=levels, **meta)
        answer = response.scores["q"]
        return ScoreResult(
            score=answer.score,
            levels=levels,
            probabilities={str(k): v for k, v in answer.probabilities.items()},
            confidence=answer.confidence,
            **meta,
        )

    def evaluate(self, state: Any, questions: Mapping[str, Any]) -> EvaluateResult:
        """Several questions about one state, in the TypeSafe API's own question shape."""
        response, meta = self._call(state, questions)
        if response is None:
            return EvaluateResult(**meta)
        return EvaluateResult(
            answers={name: answer.model_dump(mode="json") for name, answer in response.answers.items()},
            **meta,
        )

    def judge_article(self, symbol: str, company: str, title: str, summary: str) -> ArticleJudgment:
        """Relevance, direction, content type, event type, upcoming event and materiality of one item."""
        response, meta = self._call(
            presets.article_state(symbol, company, title, summary), presets.article_questions()
        )
        if response is None:
            return ArticleJudgment(**meta)
        direction = response.choices["direction"]
        content_type = response.choices["content_type"]
        event_type = response.choices["event_type"]
        materiality = response.scores["materiality"]
        return ArticleJudgment(
            relevant=response.nouls["relevant"].noul,
            direction=direction.choice,
            direction_probabilities=direction.probabilities,
            direction_confidence=direction.confidence,
            content_type=content_type.choice,
            content_type_probabilities=content_type.probabilities,
            content_type_confidence=content_type.confidence,
            event_type=event_type.choice,
            event_type_probabilities=event_type.probabilities,
            event_type_confidence=event_type.confidence,
            upcoming_event=response.nouls["upcoming_event"].noul,
            materiality=materiality.score,
            materiality_confidence=materiality.confidence,
            **meta,
        )

    def judge_evidence(self, evidence: Mapping[str, Any], company: str) -> ArticleJudgment:
        """Judge one evidence item in the v0 API contract shape (uses symbol, title, summary).

        The contract's evidence item has no company name, so the caller supplies it.
        """
        judgment = self.judge_article(
            evidence["symbol"], company, evidence["title"], evidence.get("summary") or ""
        )
        judgment.evidence_id = evidence.get("id")
        return judgment

    def judge_evidence_items(
        self, items: Sequence[Mapping[str, Any]], companies: Mapping[str, str]
    ) -> list[ArticleJudgment]:
        """Judge many contract-shaped evidence items concurrently, in order.

        `companies` maps symbol to company name.
        """
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            return list(
                pool.map(lambda e: self.judge_evidence(e, companies[e["symbol"]]), items)
            )

    def judge_articles(self, articles: Sequence[Mapping[str, str]]) -> list[ArticleJudgment]:
        """Judge many articles concurrently. Each needs symbol, company, title and summary."""
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            return list(pool.map(lambda a: self.judge_article(**a), articles))

    def check_explanation(self, explanation: str, evidence: Sequence[Mapping[str, Any]]) -> ExplanationCheck:
        """Check a written explanation against the evidence it should rest on.

        Each sentence gets `supported` (0 to 1: is it backed by `evidence`, a list of items
        with `id`, `title`, `summary`). `personal_advice` and `promises_outcome` (0 to 1) cover
        the whole text. Sentences beyond the first 12 are not checked (`claims_truncated`).
        """
        sentences = presets.split_sentences(explanation)
        claims = sentences[: presets.MAX_CLAIMS]
        truncated = len(sentences) > len(claims)
        response, meta = self._call(
            presets.explanation_state(explanation, claims, evidence),
            presets.explanation_questions(len(claims)),
        )
        if response is None:
            return ExplanationCheck(claims_truncated=truncated, **meta)
        return ExplanationCheck(
            claims=[
                ClaimCheck(text=text, supported=response.nouls[f"claim_{i}"].noul)
                for i, text in enumerate(claims)
            ],
            claims_truncated=truncated,
            personal_advice=response.nouls["personal_advice"].noul,
            promises_outcome=response.nouls["promises_outcome"].noul,
            **meta,
        )

    def close(self) -> None:
        with self._lock:
            if self._client is not None and hasattr(self._client, "close"):
                self._client.close()
            self._client = None


_default: JevTool | None = None
_default_lock = threading.Lock()


def default_tool() -> JevTool:
    """Process-wide tool configured from the environment (and jev-tool's .env, if present)."""
    global _default
    with _default_lock:
        if _default is None:
            load_env()
            _default = JevTool()
        return _default
