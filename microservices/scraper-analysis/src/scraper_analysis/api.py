from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .agents import synthesis_agent
from .config import get_settings
from .pipeline import divergence
from .pipeline.ingest import InvalidSymbolError, ingest_symbol, validate_symbol
from .scheduler import Scheduler, build_owner_lock
from .sources.base import sanitize_error
from .storage.store import get_store

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.scheduler = None
    if settings.enable_scheduler:
        scheduler = Scheduler(
            # Scheduler normalizes, validates and de-duplicates these.
            symbols=[s for s in settings.scheduler_symbols.split(",") if s.strip()],
            interval_minutes=settings.scheduler_interval_minutes,
            offhours_factor=settings.scheduler_offhours_factor,
            tag=settings.scheduler_tag,
            # With DATABASE_URL set: a Postgres advisory lock so only one
            # process/replica can own the scheduler. None = in-process only.
            owner_lock=build_owner_lock(settings),
        )
        # start() refuses (start_error in /scheduler/status) if another
        # scheduler owns this process, a previous run is still draining, or
        # another process holds the advisory lock; it never runs two at once.
        scheduler.start()
        app.state.scheduler = scheduler
    try:
        yield
    finally:
        if app.state.scheduler is not None:
            await app.state.scheduler.stop()


app = FastAPI(title="scraper-analysis", version="0.1.0", lifespan=lifespan)


@app.get("/scheduler/status")
def scheduler_status() -> dict:
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None:
        return {"enabled": False}
    return scheduler.status()


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


@app.get("/divergence")
def get_divergence(symbol: str = Query(...)) -> dict:
    """Where independent source types disagree (price vs insiders vs Senate
    vs news). Deterministic and rule-based; thresholds are in the response.
    Only live records inside the recency window around the price signal can
    contribute to a flag; fixtures never do (see pipeline/divergence.py)."""
    try:
        validated = validate_symbol(symbol)
    except InvalidSymbolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store = get_store()
    evidence, signals = synthesis_agent.select_briefing_records(
        store.query_evidence(validated), store.query_signals(validated)
    )
    result = divergence.analyze(validated, evidence, signals)
    result["data_modes"] = sorted({e.data_mode for e in evidence} | {s.data_mode for s in signals})
    return result
