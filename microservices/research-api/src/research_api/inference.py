"""Server-side-only seam for the verified Akamai OpenAI-compatible service.

This module intentionally has no default HTTP transport. Callers must inject one,
which keeps local tests offline and prevents accidental live calls before Gate 0.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderFailureClass(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"


class InferenceConfigurationError(ValueError):
    """Raised when required server-side configuration is absent."""

    def __init__(self, missing_names: tuple[str, ...]) -> None:
        self.missing_names = missing_names
        super().__init__(f"Missing inference configuration: {', '.join(missing_names)}")


class InferenceProviderError(RuntimeError):
    """A safe provider failure that intentionally excludes raw response bodies."""

    def __init__(self, status_code: int | None, failure_class: ProviderFailureClass) -> None:
        self.status_code = status_code
        self.failure_class = failure_class
        self.retryable = failure_class is ProviderFailureClass.TRANSIENT
        status = "connection" if status_code is None else f"HTTP {status_code}"
        super().__init__(f"Inference provider failed with {status} ({failure_class.value})")


@dataclass(frozen=True)
class InferenceSettings:
    base_url: str
    api_key: str = field(repr=False)
    chat_model: str
    embedding_model: str

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "InferenceSettings":
        required_names = (
            "OPENAI_BASE_URL",
            "OPENAI_API_KEY",
            "CHAT_MODEL",
            "EMBEDDING_MODEL",
        )
        missing_names = tuple(name for name in required_names if not environ.get(name, "").strip())
        if missing_names:
            raise InferenceConfigurationError(tuple(sorted(missing_names)))

        return cls(
            base_url=environ["OPENAI_BASE_URL"].rstrip("/"),
            api_key=environ["OPENAI_API_KEY"],
            chat_model=environ["CHAT_MODEL"],
            embedding_model=environ["EMBEDDING_MODEL"],
        )


@dataclass(frozen=True)
class InferenceResponse:
    status_code: int
    body: Mapping[str, Any]


Transport = Callable[[str, dict[str, str], dict[str, object], float], InferenceResponse]


def classify_provider_failure(status_code: int | None) -> ProviderFailureClass:
    """Classify only safely retryable transport and server failures as transient."""
    if status_code is None or status_code in {408, 429} or status_code >= 500:
        return ProviderFailureClass.TRANSIENT
    return ProviderFailureClass.PERMANENT


class AkamaiInferenceClient:
    """Small OpenAI-compatible client with a single bounded retry for transient errors."""

    _MAX_ATTEMPTS = 2
    _TIMEOUT_SECONDS = 30.0

    def __init__(self, settings: InferenceSettings, transport: Transport) -> None:
        self._settings = settings
        self._transport = transport

    def chat_completion(self, messages: list[dict[str, str]]) -> Mapping[str, Any]:
        return self._post(
            "/chat/completions",
            {"model": self._settings.chat_model, "messages": messages},
        )

    def embedding(self, input_text: str) -> Mapping[str, Any]:
        return self._post(
            "/embeddings",
            {"model": self._settings.embedding_model, "input": input_text},
        )

    def _post(self, path: str, payload: dict[str, object]) -> Mapping[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
        }
        response: InferenceResponse | None = None

        for attempt in range(self._MAX_ATTEMPTS):
            try:
                response = self._transport(
                    f"{self._settings.base_url}{path}", headers, payload, self._TIMEOUT_SECONDS
                )
            except OSError:
                response = None

            if response is not None and 200 <= response.status_code < 300:
                return response.body

            status_code = None if response is None else response.status_code
            failure_class = classify_provider_failure(status_code)
            if failure_class is ProviderFailureClass.PERMANENT or attempt == self._MAX_ATTEMPTS - 1:
                raise InferenceProviderError(status_code, failure_class)

        raise AssertionError("unreachable bounded retry state")
