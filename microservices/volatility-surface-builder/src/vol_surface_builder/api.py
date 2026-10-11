"""Standalone HTTP boundary for option-volatility surface diagnostics."""

import re
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .pipeline import UnsupportedSampleSymbol, build_snapshot

app = FastAPI(title="Volatility Surface Builder", version="0.3.0")
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


class SurfaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    mode: Literal["sample", "live"] = "sample"
    spot: float = Field(default=602.0, gt=0, allow_inf_nan=False)


def _error(status: int, code: str, message: str, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "retryable": retryable}},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "volatility-surface-builder"}


@app.post("/v0/volatility-surfaces")
def create_surface(request: SurfaceRequest):
    symbol = request.symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        return _error(400, "invalid_symbol", "symbol must be a ticker containing 1 to 5 letters")
    try:
        return build_snapshot(symbol=symbol, mode=request.mode, spot=request.spot)
    except UnsupportedSampleSymbol as exc:
        return _error(400, "unsupported_sample_symbol", str(exc))
    except (ImportError, RuntimeError, ValueError):
        if request.mode == "live":
            return _error(503, "options_provider_unavailable", "Live option data is unavailable.", True)
        raise
