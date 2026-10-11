from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .agents import synthesis_agent
from .pipeline.ingest import InvalidSymbolError, ingest_symbol, validate_symbol
from .sources.base import sanitize_error
from .storage.store import get_store

app = FastAPI(title="scraper-analysis", version="0.1.0")


@app.post("/briefing")
def briefing(symbol: str = Query(..., description="Ticker symbol, e.g. AAPL")) -> JSONResponse:
    """Cited research briefing from the stored evidence (Strands synthesis
    agent). Costs a Bedrock call, hence POST. Never a buy/sell call."""
    try:
        validated = validate_symbol(symbol)
    except InvalidSymbolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return JSONResponse(synthesis_agent.generate_briefing(validated))
    except synthesis_agent.BriefingUnavailableError as exc:
        # Same envelope shape as docs/api-contract-v0.md errors.
        return JSONResponse(
            status_code=503,
            content={
                "error": {"code": "briefing_unavailable", "message": sanitize_error(exc), "retryable": True}
            },
        )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ingest/run", response_model=None)
def ingest_run(
    symbol: str = Query(..., description="Ticker symbol, e.g. AAPL"),
    live: bool = Query(True, description="Try live sources; false forces fixtures"),
    fallback: bool = Query(
        True,
        description="When a live source fails, substitute its labeled fixture. "
        "Pass false to refuse fixtures: failed sources are omitted and reported as 'unavailable'.",
    ),
    tag: bool = Query(True, description="Run the Strands/Bedrock tagging agent on each record"),
):
    try:
        validated = validate_symbol(symbol)
    except InvalidSymbolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = ingest_symbol(validated, allow_live=live, tag=tag, fallback=fallback)
    # Adapters already sanitize via sources.base.resolve(); repeat it at the
    # API boundary so no future source path can return raw upstream text.
    sources = [
        {**asdict(s), "error": sanitize_error(s.error) if s.error else None} for s in result.sources
    ]

    # Strict mode with nothing live: this is the contract's provider_unavailable
    # case, not an empty success.
    if live and not fallback and not result.any_live:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "provider_unavailable",
                    "message": "No live source was reachable; no evidence was collected and fixtures were refused.",
                    "retryable": True,
                    "details": {"sources": sources},
                }
            },
        )

    return {
        "symbol": validated,
        "count": len(result.evidence),
        "evidence": [e.model_dump(mode="json") for e in result.evidence],
        "signals": [s.model_dump(mode="json") for s in result.signals],
        "sources": sources,
        "warnings": [
            f"{s['name']}: live source failed, "
            + ("fixtures substituted" if s["status"] == "fallback" else "omitted (fixtures refused)")
            + f" ({s['error']})"
            for s in sources
            if s["status"] in ("fallback", "unavailable")
        ],
    }


@app.get("/evidence")
def get_evidence(symbol: str = Query(...)) -> dict:
    try:
        validated = validate_symbol(symbol)
    except InvalidSymbolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    items = get_store().query_evidence(validated)
    return {
        "symbol": validated,
        "status": "ok" if items else "insufficient_data",
        "evidence": [e.model_dump(mode="json") for e in items],
    }


@app.get("/signals")
def get_signals(symbol: str = Query(...)) -> dict:
    try:
        validated = validate_symbol(symbol)
    except InvalidSymbolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    items = get_store().query_signals(validated)
    return {
        "symbol": validated,
        "status": "ok" if items else "insufficient_data",
        "signals": [s.model_dump(mode="json") for s in items],
    }
