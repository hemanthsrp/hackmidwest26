from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .agents import synthesis_agent
from .pipeline.ingest import InvalidSymbolError, run_ingestion, run_signal_ingestion, validate_symbol
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
            content={"error": {"code": "briefing_unavailable", "message": str(exc), "retryable": True}},
        )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ingest/run")
def ingest_run(
    symbol: str = Query(..., description="Ticker symbol, e.g. AAPL"),
    live: bool = Query(True, description="Try live sources before falling back to fixtures"),
    tag: bool = Query(True, description="Run the Strands/Bedrock tagging agent on each record"),
) -> dict:
    try:
        validated = validate_symbol(symbol)
    except InvalidSymbolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    evidence = run_ingestion(validated, allow_live=live, tag=tag)
    signals = run_signal_ingestion(validated, allow_live=live)
    return {
        "symbol": validated,
        "count": len(evidence),
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "signals": [s.model_dump(mode="json") for s in signals],
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
