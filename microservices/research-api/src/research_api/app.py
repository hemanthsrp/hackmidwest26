import logging
import os
import re
import uuid
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import assessment, recommendations
from .universe import INDUSTRIES

logger = logging.getLogger(__name__)

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


def cors_origins() -> list[str]:
    """Browser origins allowed to call this API: the Next.js dev server by default,
    or the comma-separated CORS_ALLOW_ORIGINS. Never a wildcard."""
    raw = os.environ.get("CORS_ALLOW_ORIGINS", DEFAULT_CORS_ORIGINS)
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip() and origin.strip() != "*"]


app = FastAPI(title="Research API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)


class AssessmentPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon: Literal["7d", "30d", "90d"] = "30d"
    risk_profile: Literal["conservative", "balanced", "growth"] = "balanced"

from .v1 import router as v1_router
app.include_router(v1_router)

from fastapi import HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error":{"code":"request_failed","message":str(exc.detail),"retryable":exc.status_code >= 500}})

@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    return JSONResponse(status_code=503, content={"error":{"code":"storage_unavailable","message":"Account storage is unavailable.","retryable":True}})

@app.exception_handler(RuntimeError)
async def configuration_error(request: Request, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"error":{"code":"service_unavailable","message":"This service is not configured yet.","retryable":True}})


class ResearchAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    mode: Literal["sample", "live", "failure", "sample_decision"] = "sample"
    # Used by "live" and "sample_decision"; the fixed "sample" snapshot ignores them.
    query: str | None = Field(default=None, max_length=2000)
    preferences: AssessmentPreferences = Field(default_factory=AssessmentPreferences)


_SAMPLE_AS_OF = "2026-10-10T20:00:00Z"
_SAMPLE_RETRIEVED_AT = "2026-10-10T20:00:05Z"

_DECISION_ERROR_STATUS = {"invalid_symbol": 400, "provider_unavailable": 503, "stale_data": 409}


def _providers_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "provider_unavailable",
                "message": "Live research providers are not configured; no assessment was generated.",
                "retryable": True,
            },
            "request_id": "live-unavailable-001",
        },
    )


def _decide(request: ResearchAssessmentRequest, symbol: str) -> JSONResponse:
    """Run the decision maker. A live request that cannot be served is an explicit
    error; it never falls back to fixture output."""
    sample = request.mode == "sample_decision"
    maker = assessment.sample_decision_maker() if sample else assessment.get_decision_maker()
    if maker is None:
        return _providers_unavailable()

    from decision_maker import DecisionError

    try:
        response = assessment.assess(
            maker, symbol=symbol, query=request.query, preferences=request.preferences.model_dump(), sample=sample
        )
    except DecisionError as error:
        body = {"code": error.code, "message": error.message, "retryable": error.retryable}
        if error.details:
            body["details"] = error.details
        return JSONResponse(
            status_code=_DECISION_ERROR_STATUS.get(error.code, 500),
            content={"error": body, "request_id": f"req-{uuid.uuid4().hex}"},
        )
    except Exception as error:  # keep the envelope even for a bug; the text may carry provider details
        logger.error("assessment failed for %s: %s", symbol, type(error).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "internal_error", "message": "The assessment could not be completed.", "retryable": False},
                "request_id": f"req-{uuid.uuid4().hex}",
            },
        )
    return JSONResponse(content=response.model_dump(mode="json"))


@app.get("/health")
def health() -> dict[str, str]:
    """Return a dependency-free local readiness signal."""
    return {"status": "ok", "service": "research-api"}


@app.get("/v0/industries")
def list_industries() -> dict[str, object]:
    """The industries (GICS sectors) that have a recommended-stocks list."""
    return {"industries": recommendations.list_industries()}


@app.get("/v0/industries/{slug}/recommended-stocks")
def recommended_stocks(slug: str):
    """24 stocks for the industry, best heuristic score first. Reads stored evidence only."""
    if slug not in INDUSTRIES:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "unknown_industry",
                    "message": "Unknown industry. GET /v0/industries lists the valid slugs.",
                    "retryable": False,
                },
                "request_id": f"req-{uuid.uuid4().hex}",
            },
        )
    return recommendations.recommended_stocks(slug)


@app.post("/v0/research-assessments")
def create_research_assessment(
    request: ResearchAssessmentRequest,
) -> dict[str, object]:
    """Return an explicitly labeled deterministic current research snapshot."""
    symbol = request.symbol.strip().upper()
    if not re.fullmatch(r"[A-Z]{1,5}", symbol):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "invalid_symbol",
                    "message": "symbol must be an uppercase ticker containing 1 to 5 letters",
                    "retryable": False,
                },
                "request_id": "invalid-symbol-001",
            },
        )
    if request.mode == "failure":
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "simulated_provider_failure",
                    "message": "A simulated provider failure occurred; no assessment was generated.",
                    "retryable": True,
                },
                "request_id": "simulated-failure-001",
            },
        )
    if request.mode in ("live", "sample_decision"):
        return _decide(request, symbol)

    return {
        "request_id": "sample-acme-current-001",
        "symbol": symbol,
        "data_mode": "sample",
        "snapshot": {
            "kind": "current_research_snapshot",
            "as_of": _SAMPLE_AS_OF,
            "retrieved_at": _SAMPLE_RETRIEVED_AT,
        },
        "evidence": [
            {
                "id": "sample-acme-news-001",
                "symbol": symbol,
                "title": "Sample ACME research update",
                "summary": "Fixture-only evidence for a current research snapshot.",
                "source_name": "Fixture News",
                "source_url": "https://example.invalid/fixtures/acme-news-001",
                "observed_at": _SAMPLE_AS_OF,
                "retrieved_at": _SAMPLE_RETRIEVED_AT,
                "data_mode": "sample",
            }
        ],
        "signals": [
            {
                "id": "sample-acme-signal-001",
                "symbol": symbol,
                "name": "current sample market indicator",
                "value": 2.4,
                "unit": "percent",
                "as_of": _SAMPLE_AS_OF,
                "source": "Fixture Market Data",
                "data_mode": "sample",
            }
        ],
        "assessment": {
            "label": "hold",
            "explanation": "This current research snapshot has mixed fixture evidence.",
            "uncertainty": "Sample data only; this is not a prediction or investment advice.",
            "generated_at": _SAMPLE_RETRIEVED_AT,
            "data_mode": "sample",
        },
        "warnings": [],
    }
