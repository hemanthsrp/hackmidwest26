import pytest

from research_api.inference import (
    AkamaiInferenceClient,
    InferenceConfigurationError,
    InferenceProviderError,
    InferenceResponse,
    InferenceSettings,
    ProviderFailureClass,
    classify_provider_failure,
)


@pytest.fixture
def configured_environment() -> dict[str, str]:
    return {
        "OPENAI_BASE_URL": "https://ws.akamai-workshops.com/v1/",
        "OPENAI_API_KEY": "test-server-only-key",
        "CHAT_MODEL": "hackathon-chat",
        "EMBEDDING_MODEL": "hackathon-embedding",
    }


def test_settings_rejects_missing_server_side_configuration() -> None:
    with pytest.raises(InferenceConfigurationError) as error:
        InferenceSettings.from_environ(
            {
                "OPENAI_BASE_URL": "https://ws.akamai-workshops.com/v1",
                "CHAT_MODEL": "hackathon-chat",
            }
        )

    assert error.value.missing_names == ("EMBEDDING_MODEL", "OPENAI_API_KEY")
    assert "test-server-only-key" not in str(error.value)


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (None, ProviderFailureClass.TRANSIENT),
        (408, ProviderFailureClass.TRANSIENT),
        (429, ProviderFailureClass.TRANSIENT),
        (503, ProviderFailureClass.TRANSIENT),
        (401, ProviderFailureClass.PERMANENT),
        (422, ProviderFailureClass.PERMANENT),
    ],
)
def test_provider_failure_classification_is_bounded_and_explicit(
    status_code: int | None, expected: ProviderFailureClass
) -> None:
    assert classify_provider_failure(status_code) is expected


def test_chat_request_uses_server_side_alias_and_one_transient_retry(
    configured_environment: dict[str, str],
) -> None:
    requests: list[tuple[str, dict[str, str], dict[str, object], float]] = []
    responses = [
        InferenceResponse(status_code=503, body={"error": "temporarily unavailable"}),
        InferenceResponse(status_code=200, body={"id": "chat-1", "choices": []}),
    ]

    def transport(
        url: str, headers: dict[str, str], payload: dict[str, object], timeout: float
    ) -> InferenceResponse:
        requests.append((url, headers, payload, timeout))
        return responses.pop(0)

    client = AkamaiInferenceClient(
        settings=InferenceSettings.from_environ(configured_environment),
        transport=transport,
    )

    response = client.chat_completion(messages=[{"role": "user", "content": "hello"}])

    assert response["id"] == "chat-1"
    assert len(requests) == 2
    assert requests[0][0] == "https://ws.akamai-workshops.com/v1/chat/completions"
    assert requests[0][2]["model"] == "hackathon-chat"
    assert requests[0][1]["Authorization"] == "Bearer test-server-only-key"


def test_embedding_request_fails_without_fixture_substitution(
    configured_environment: dict[str, str],
) -> None:
    attempts = 0

    def transport(
        url: str, headers: dict[str, str], payload: dict[str, object], timeout: float
    ) -> InferenceResponse:
        nonlocal attempts
        attempts += 1
        assert url == "https://ws.akamai-workshops.com/v1/embeddings"
        assert payload["model"] == "hackathon-embedding"
        return InferenceResponse(status_code=401, body={"error": "unauthorized"})

    client = AkamaiInferenceClient(
        settings=InferenceSettings.from_environ(configured_environment),
        transport=transport,
    )

    with pytest.raises(InferenceProviderError) as error:
        client.embedding(input_text="one sentence")

    assert attempts == 1
    assert error.value.failure_class is ProviderFailureClass.PERMANENT
    assert error.value.retryable is False
