import re
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="Research API", version="0.1.0")


class ResearchAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    mode: Literal["sample", "live", "failure"] = "sample"


_SAMPLE_AS_OF = "2026-10-10T20:00:00Z"
_SAMPLE_RETRIEVED_AT = "2026-10-10T20:00:05Z"


@app.get("/health")
def health() -> dict[str, str]:
    """Return a dependency-free local readiness signal."""
    return {"status": "ok", "service": "research-api"}


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
    if request.mode == "live":
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
