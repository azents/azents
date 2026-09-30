"""Deterministic official SDK error classification and safe diagnostics."""

import anthropic
import httpx
import httpx2
import openai
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from google.genai.errors import APIError as GoogleAPIError
from pydantic_ai.exceptions import ModelHTTPError

from azents.engine.model_stream import ModelStreamCallContext
from azents.engine.provider_errors import map_model_provider_error
from azents.engine.run.provider_failure import (
    ModelProviderFailureCategory,
    UnclassifiedModelProviderError,
)


def _context() -> ModelStreamCallContext:
    return ModelStreamCallContext(
        call_kind="sampling",
        provider="synthetic",
        provider_integration_id="integration",
        model="publisher/exact/model",
        session_id="session",
        run_id="run",
        attempt_number=1,
        check_stop=None,
    )


@pytest.mark.parametrize("sdk", [openai, anthropic])
def test_sdk_authentication_preserves_scalar_evidence_and_redacts_secrets(
    sdk: object,
) -> None:
    """Provider text is retained safely without embedding SDK serialization."""
    request = httpx2.Request("POST", "https://synthetic.test/generation")
    response = httpx2.Response(401, request=request)
    body = {
        "error": {
            "message": "api_key=sk-supersecret123 invalid",
            "type": "authentication_error",
        }
    }
    exception = (
        openai.AuthenticationError(
            "Error code: 401 - " + str(body), response=response, body=body
        )
        if sdk is openai
        else anthropic.AuthenticationError(
            "Error code: 401 - " + str(body), response=response, body=body
        )
    )
    failure = map_model_provider_error(exception, call_context=_context())
    assert failure.category is ModelProviderFailureCategory.AUTHENTICATION
    assert failure.status_code == 401
    assert failure.route_model == "publisher/exact/model"
    assert "sk-supersecret123" not in str(failure)
    assert failure.provider_message == "api_key=[REDACTED] invalid"


def test_wrapped_model_http_error_keeps_original_billing_and_retry_evidence() -> None:
    """Stock model wrapping does not lose the underlying public SDK body."""
    request = httpx2.Request("POST", "https://synthetic.test/generation")
    response = httpx2.Response(429, request=request, headers={"retry-after": "2.5"})
    sdk_error = openai.RateLimitError(
        "Quota exhausted",
        response=response,
        body={"error": {"code": "insufficient_quota", "message": "Credits exhausted"}},
    )
    wrapper = ModelHTTPError(429, "publisher/exact/model")
    wrapper.__cause__ = sdk_error
    failure = map_model_provider_error(wrapper, call_context=_context())
    assert failure.category is ModelProviderFailureCategory.QUOTA_OR_BILLING
    assert failure.provider_message == "Credits exhausted"
    assert failure.retry_hint_seconds == 2.5


@pytest.mark.parametrize(
    ("exception", "category"),
    [
        (
            GoogleAPIError(
                403,
                {
                    "error": {
                        "message": "Permission denied",
                        "status": "PERMISSION_DENIED",
                    }
                },
            ),
            ModelProviderFailureCategory.PERMISSION,
        ),
        (
            ClientError(
                {
                    "Error": {
                        "Code": "ValidationException",
                        "Message": "Invalid input",
                    },
                    "ResponseMetadata": {
                        "RequestId": "synthetic",
                        "HostId": "synthetic",
                        "HTTPStatusCode": 400,
                        "HTTPHeaders": {},
                        "RetryAttempts": 0,
                    },
                },
                "ConverseStream",
            ),
            ModelProviderFailureCategory.INVALID_REQUEST,
        ),
        (
            EndpointConnectionError(endpoint_url="https://secret.invalid"),
            ModelProviderFailureCategory.TRANSPORT,
        ),
        (httpx.ReadError("wire details"), ModelProviderFailureCategory.TRANSPORT),
        (httpx2.ReadError("wire details"), ModelProviderFailureCategory.TRANSPORT),
    ],
)
def test_official_sdk_failure_taxonomy(
    exception: Exception, category: ModelProviderFailureCategory
) -> None:
    failure = map_model_provider_error(exception, call_context=_context())
    assert failure.category is category
    assert "secret.invalid" not in str(failure)
    assert "wire details" not in str(failure)


def test_unknown_provider_failure_remains_internal() -> None:
    with pytest.raises(UnclassifiedModelProviderError):
        map_model_provider_error(
            ModelHTTPError(200, "publisher/exact/model", {"unexpected": "opaque"}),
            call_context=_context(),
        )


def test_programming_failure_is_not_mapped() -> None:
    exception = TypeError("observer bug")
    with pytest.raises(TypeError) as caught:
        map_model_provider_error(exception, call_context=_context())
    assert caught.value is exception
