"""Embeddings via Akamai's hosted AI inference endpoint (the kickoff-provided
BYOI-compatible inference service, not Bedrock -- vectorization runs on
Akamai per the architecture decision). Returns None when unconfigured or on
failure so callers can skip vector storage gracefully instead of crashing
the ingestion pipeline."""

import logging

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


def get_embedding(text: str) -> list[float] | None:
    settings = get_settings()
    if not settings.akamai_inference_configured:
        return None

    try:
        resp = httpx.post(
            f"{settings.akamai_inference_base_url.rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {settings.akamai_inference_api_key}"},
            json={"model": settings.akamai_embedding_model, "input": text},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        logger.warning("embedding request failed; storing evidence without a vector", exc_info=True)
        return None
