"""Composition root for assessments: wires ``microservices/decision-maker`` to
this service's adapters and holds the hook the quant math plugs into.

Everything is built from the process environment, server-side. With no
``DATABASE_URL`` (or without the decision-maker package installed) there is no
decision maker, and the route keeps answering live requests with
``503 provider_unavailable``; nothing is substituted.

The math comes from ``microservices/volatility-surface-builder`` when
``VOL_SURFACE_URL`` points at it (``quant.py``), or from any provider passed to
``set_quant_provider``. With neither, every assessment says the options-based
math was not supplied.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from typing import Any

from .decision import JevDecisionAdapter, JevExplanationAdapter
from .inference import AkamaiInferenceClient, InferenceConfigurationError, InferenceResponse, InferenceSettings
from .quant import vol_surface_provider

logger = logging.getLogger(__name__)

# Jev's questions name the company. Same hints as scraper-analysis
# (pipeline/symbol_match.py); an unlisted symbol falls back to its ticker.
COMPANY_NAMES: dict[str, str] = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "TSLA": "Tesla",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "GOOG": "Alphabet",
    "META": "Meta",
    "NVDA": "Nvidia",
    "NFLX": "Netflix",
    "JPM": "JPMorgan",
}

# (symbol, horizon) -> decision_maker.QuantInput, or None when there is no math for the symbol.
QuantProvider = Callable[[str, str], Any]

_quant_provider: QuantProvider | None = None
_decision_maker: Any = None
_built = False
_scoring_maker: Any = None
_scoring_built = False


def trigger_ingestion(symbol: str, environ: Mapping[str, str] = os.environ) -> None:
    """Ask scraper-analysis to strictly refresh a symbol before a live read.

    The dependency stays optional for local/read-only deployments: without an
    explicit service URL this does nothing. When configured, fixtures are
    refused and any failure is surfaced rather than silently assessing stale
    records.
    """
    base_url = environ.get("SCRAPER_ANALYSIS_URL", "").strip()
    if not base_url:
        return
    import httpx
    from decision_maker import ProviderUnavailableError

    try:
        response = httpx.post(
            base_url.rstrip("/") + "/ingest/run",
            params={"symbol": symbol, "live": "true", "fallback": "false", "tag": "true", "judge": "true"},
            timeout=float(environ.get("INGEST_TIMEOUT_SECONDS", "90")),
        )
    except httpx.HTTPError as error:
        raise ProviderUnavailableError("Evidence ingestion was unavailable; no assessment was generated.", {"provider": "scraper_analysis"}) from error
    if response.status_code >= 400:
        raise ProviderUnavailableError("Evidence ingestion did not complete; no assessment was generated.", {"provider": "scraper_analysis"})


def set_quant_provider(provider: QuantProvider | None) -> None:
    """Register the math. It is called once per live assessment and should return a
    ``decision_maker.QuantInput`` whose ``vol_surface`` carries the surface statistics
    (see microservices/decision-maker/README.md)."""
    global _quant_provider
    _quant_provider = provider


def httpx_transport(url: str, headers: dict[str, str], payload: dict[str, object], timeout: float) -> InferenceResponse:
    """Real HTTP for ``AkamaiInferenceClient``. A connection failure surfaces as
    ``OSError``, which the client already classifies as transient."""
    import httpx

    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    except httpx.HTTPError as error:
        raise OSError(type(error).__name__) from None
    try:
        body = response.json()
    except ValueError:
        body = {}
    return InferenceResponse(status_code=response.status_code, body=body if isinstance(body, dict) else {})


def _jev_tool() -> Any:
    try:
        from jev_tool import default_tool
    except ImportError:
        return None
    tool = default_tool()
    return tool if tool.enabled else None


EXPLANATION_PROVIDERS = ("bedrock", "akamai")
DEFAULT_EXPLANATION_MODEL = "us.anthropic.claude-sonnet-5"


def _explanation_agent(environ: Mapping[str, str], settings: InferenceSettings | None) -> tuple[Any, str | None]:
    """Who writes the explanation: Claude on Bedrock by default, Akamai's hosted model when
    ``EXPLANATION_PROVIDER=akamai`` or when no AWS credentials are set. (agent_factory, model name)."""
    from decision_maker import bedrock_agent_factory, openai_compatible_agent_factory

    provider = environ.get("EXPLANATION_PROVIDER", "bedrock").strip().lower()
    if provider not in EXPLANATION_PROVIDERS:
        logger.warning("EXPLANATION_PROVIDER=%r is not one of %s; using bedrock", provider, EXPLANATION_PROVIDERS)
        provider = "bedrock"
    key, secret = environ.get("AWS_ACCESS_KEY_ID", "").strip(), environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    if provider == "bedrock" and key and secret:
        model = environ.get("EXPLANATION_MODEL_ID", DEFAULT_EXPLANATION_MODEL).strip() or DEFAULT_EXPLANATION_MODEL
        factory = bedrock_agent_factory(
            model_id=model,
            region=environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            access_key_id=key,
            secret_access_key=secret,
            session_token=environ.get("AWS_SESSION_TOKEN") or None,
        )
        return factory, model
    if provider == "bedrock":
        logger.warning("EXPLANATION_PROVIDER is bedrock but no AWS credentials are set; trying Akamai inference")
    if settings is not None:
        factory = openai_compatible_agent_factory(
            base_url=settings.base_url, api_key=settings.api_key, model_id=settings.chat_model
        )
        return factory, settings.chat_model
    return None, None


def build_decision_maker(environ: Mapping[str, str] = os.environ, *, scoring_only: bool = False) -> Any:
    """The live decision maker, or None when it cannot be built.

    ``scoring_only`` leaves out the model-written explanation, semantic search and the
    Jev review of that text. The label and score do not depend on them, so a scoring
    maker agrees with the full one but is cheap enough to run for a whole industry."""
    database_url = environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return None
    try:
        from decision_maker import DecisionMaker, PgEvidenceSource
    except ImportError:
        logger.warning("DATABASE_URL is set but decision-maker is not installed; live assessments stay unavailable")
        return None

    embedder = agent_factory = chat_model = None
    settings = None
    if not scoring_only:
        try:
            settings = InferenceSettings.from_environ(environ)
        except InferenceConfigurationError as error:
            logger.warning(
                "inference is not configured (%s): no semantic search or model-written explanation",
                ", ".join(error.missing_names),
            )
    if settings is not None:
        # Akamai always serves the embeddings (semantic search of the user's question).
        client = AkamaiInferenceClient(settings, httpx_transport)
        embedder = lambda text: client.embedding(text)["data"][0]["embedding"]  # noqa: E731
    if not scoring_only:
        agent_factory, chat_model = _explanation_agent(environ, settings)

    jev = _jev_tool()
    try:
        source = PgEvidenceSource(database_url, embedder=embedder)
    except ValueError as error:  # the TLS rule; the message names no credential
        logger.warning("evidence store is misconfigured: %s", error)
        return None
    return DecisionMaker(
        evidence_source=source,
        agent_factory=agent_factory,
        agent_model=chat_model,
        use_agent_tools=environ.get("DECISION_AGENT_TOOLS", "false").strip().lower() == "true",
        article_judge=JevDecisionAdapter(jev) if jev and not scoring_only else None,
        explanation_checker=JevExplanationAdapter(jev) if jev and not scoring_only else None,
        companies=COMPANY_NAMES,
        stale_after_seconds=int(environ.get("DECISION_STALE_AFTER_SECONDS", "86400")),
    )


def get_scoring_maker() -> Any:
    """Like ``get_decision_maker`` but for ranking: no model explanation. Built once."""
    global _scoring_maker, _scoring_built
    if not _scoring_built:
        _scoring_maker = build_decision_maker(scoring_only=True)
        _scoring_built = True
    return _scoring_maker


def configure_quant(environ: Mapping[str, str] = os.environ) -> None:
    """Use the volatility service for the math when ``VOL_SURFACE_URL`` names it,
    unless a provider was registered by hand."""
    url = environ.get("VOL_SURFACE_URL", "").strip()
    if url and _quant_provider is None:
        set_quant_provider(vol_surface_provider(url))


def get_decision_maker() -> Any:
    """Built once, on the first live request."""
    global _decision_maker, _built
    if not _built:
        _decision_maker = build_decision_maker()
        if _decision_maker is not None:
            configure_quant()
        _built = True
    return _decision_maker


def reset() -> None:
    """Forget the cached decision maker and the registered math (tests, config reloads)."""
    global _decision_maker, _built, _quant_provider, _scoring_maker, _scoring_built
    _decision_maker, _built, _quant_provider = None, False, None
    _scoring_maker, _scoring_built = None, False


def sample_decision_maker() -> Any:
    """Runs over the decision maker's packaged fixture. Offline: no store, model or Jev."""
    try:
        from decision_maker import DecisionMaker
    except ImportError:
        return None
    return DecisionMaker()


def assess(maker: Any, *, symbol: str, query: str | None, preferences: Mapping[str, str], sample: bool) -> Any:
    """Run one assessment. Raises ``decision_maker.DecisionError`` subclasses."""
    from decision_maker import DecisionRequest, Preferences
    from decision_maker.models import ResponseWarning

    if not sample:
        trigger_ingestion(symbol)
    request = DecisionRequest(
        symbol=symbol, query=query, preferences=Preferences(**preferences), mode="sample" if sample else "live"
    )
    quant, quant_failed = None, False
    if not sample and _quant_provider is not None:
        try:
            quant = _quant_provider(request.symbol, request.preferences.horizon)
        except Exception as error:  # the math failing must not take the assessment down
            logger.warning("quant provider failed for %s: %s", symbol, type(error).__name__)
            quant_failed = True
    response = maker.decide(request, quant)
    if quant_failed:
        response.warnings.append(
            ResponseWarning(
                code="quant_provider_failed",
                message="The options-based math failed for this request and was not used.",
                retryable=True,
            )
        )
    return response
