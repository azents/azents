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
    ModelProviderFailureRetryability,
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


@pytest.mark.parametrize("provider", ["xai", "xai_oauth"])
@pytest.mark.parametrize("body_shape", ["scalar", "message", "nested"])
def test_xai_credit_exhaustion_403_is_quota(provider: str, body_shape: str) -> None:
    """The observed xAI subscription error advances the quota fallback chain."""
    message = (
        "You have run out of credits or need a Grok subscription. "
        "Add credits at https://grok.com/?_s=usage or upgrade at "
        "https://grok.com/supergrok."
    )
    body = (
        message
        if body_shape == "scalar"
        else {"message": message}
        if body_shape == "message"
        else {"error": {"message": message}}
    )
    response = httpx2.Response(
        403, request=httpx2.Request("POST", "https://synthetic.test/responses")
    )
    error = openai.PermissionDeniedError(
        "Error code: 403 - " + str(body), response=response, body=body
    )
    context = ModelStreamCallContext(
        call_kind="sampling",
        provider=provider,
        provider_integration_id="integration",
        model="grok-4.5",
        session_id="session",
        run_id="run",
        attempt_number=1,
        check_stop=None,
    )

    failure = map_model_provider_error(error, call_context=context)

    assert failure.category is ModelProviderFailureCategory.QUOTA_OR_BILLING
    assert failure.retryability is ModelProviderFailureRetryability.USER_ACTION_REQUIRED
    assert failure.status_code == 403
    assert failure.provider_message == message
    assert failure.provider_error_type == "PermissionDeniedError"
    assert failure.route_provider == provider
    assert failure.route_model == "grok-4.5"


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


@pytest.mark.parametrize("sdk", ["openai", "anthropic", "model"])
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "Argument not supported: search_context_size",
            "Argument not supported: search_context_size",
        ),
        ("Rejected api_key=sk-supersecret123", "Rejected api_key=[REDACTED]"),
        ('{"detail":"Unsupported option"}', "Unsupported option"),
        ("<html>" + "private upstream debug " * 50 + "</html>", None),
        ("x" * 8193, None),
        ('["opaque response body"]', None),
    ],
)
def test_scalar_sdk_http_error_body_preserves_only_safe_text(
    sdk: str, body: str, expected: str | None
) -> None:
    response = httpx2.Response(
        400, request=httpx2.Request("POST", "https://synthetic.invalid/responses")
    )
    serialized = f"Error code: 400 - {body}"
    error = (
        openai.BadRequestError(serialized, response=response, body=body)
        if sdk == "openai"
        else anthropic.BadRequestError(serialized, response=response, body=body)
        if sdk == "anthropic"
        else ModelHTTPError(400, "publisher/exact/model", body=body)
    )
    failure = map_model_provider_error(error, call_context=_context())
    assert failure.category is ModelProviderFailureCategory.INVALID_REQUEST
    assert failure.status_code == 400
    assert failure.provider_message == expected
    assert "sk-supersecret123" not in str(failure)
