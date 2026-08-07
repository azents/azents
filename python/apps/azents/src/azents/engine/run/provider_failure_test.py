"""Provider-neutral model failure contract tests."""

import pytest

from azents.engine.run.errors import ModelCallError
from azents.engine.run.provider_failure import (
    ModelProviderFailureCategory,
    ModelProviderFailureRetryability,
    UnclassifiedModelProviderError,
    classify_model_provider_failure,
    extract_provider_http_status_code,
    extract_provider_message_text,
    model_provider_error_log_fields,
    model_provider_failure,
    sanitize_provider_error_param,
    sanitize_provider_message,
)


@pytest.mark.parametrize(
    ("status_code", "code", "error_type", "expected"),
    [
        (401, None, None, ModelProviderFailureCategory.AUTHENTICATION),
        (403, None, None, ModelProviderFailureCategory.PERMISSION),
        (402, None, None, ModelProviderFailureCategory.QUOTA_OR_BILLING),
        (429, None, None, ModelProviderFailureCategory.RATE_LIMIT),
        (500, None, None, ModelProviderFailureCategory.PROVIDER_UNAVAILABLE),
        (
            None,
            "context_length_exceeded",
            None,
            ModelProviderFailureCategory.CONTEXT_LIMIT,
        ),
        (None, "content_filter", None, ModelProviderFailureCategory.CONTENT_POLICY),
        (None, "model_not_found", None, ModelProviderFailureCategory.MODEL_UNAVAILABLE),
        (None, "websocket_timeout", None, ModelProviderFailureCategory.TRANSPORT),
        (400, "invalid_prompt", None, ModelProviderFailureCategory.INVALID_REQUEST),
        (None, "new_provider_code", None, ModelProviderFailureCategory.UNKNOWN),
        # ChatGPT OAuth subscription exhaustion uses usage_limit_reached, often on 429.
        (
            429,
            None,
            "usage_limit_reached",
            ModelProviderFailureCategory.QUOTA_OR_BILLING,
        ),
        (
            None,
            None,
            "usage_limit_reached",
            ModelProviderFailureCategory.QUOTA_OR_BILLING,
        ),
        (
            None,
            "usage_limit_reached",
            None,
            ModelProviderFailureCategory.QUOTA_OR_BILLING,
        ),
        (
            None,
            "insufficient_quota",
            None,
            ModelProviderFailureCategory.QUOTA_OR_BILLING,
        ),
        (None, "plan_limit", None, ModelProviderFailureCategory.QUOTA_OR_BILLING),
    ],
)
def test_classifies_provider_neutral_categories(
    status_code: int | None,
    code: str | None,
    error_type: str | None,
    expected: ModelProviderFailureCategory,
) -> None:
    """Provider identifiers map into the closed neutral taxonomy."""
    assert (
        classify_model_provider_failure(
            status_code=status_code,
            provider_code=code,
            provider_error_type=error_type,
        )
        == expected
    )


def test_usage_limit_reached_is_user_visible_quota_failure() -> None:
    """Subscription usage limits stay classified instead of becoming internal errors."""
    failure = model_provider_failure(
        operation="sampling",
        provider="chatgpt_oauth",
        model="gpt-5.6-terra",
        integration="019eeab845007cd5b94ba341c3a4728e",
        provider_message="The usage limit has been reached",
        status_code=None,
        provider_code=None,
        provider_error_type="usage_limit_reached",
        provider_error_param=None,
    )

    assert failure.category is ModelProviderFailureCategory.QUOTA_OR_BILLING
    assert failure.retryability is ModelProviderFailureRetryability.USER_ACTION_REQUIRED
    assert failure.user_message == (
        "Model provider error: The usage limit has been reached"
    )
    assert isinstance(failure, ModelCallError)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (429, 429),
        ("429", 429),
        ({"status_code": 429}, 429),
        ({"status": "failed"}, None),
        ({"error": {"status_code": 503}}, 503),
        ({"response": {"error": {"http_status": 401}}}, 401),
        ({"status": 99}, None),
        (True, None),
    ],
)
def test_extracts_provider_http_status_code(
    payload: object,
    expected: int | None,
) -> None:
    """Only concrete HTTP status codes are preserved from terminal payloads."""
    assert extract_provider_http_status_code(payload) == expected


def test_sanitizes_provider_message_and_redacts_credentials() -> None:
    """Only bounded scalar provider text crosses the adapter boundary."""
    message = sanitize_provider_message(
        "Denied. Authorization: Bearer secret-value api_key=sk-abcdefghijk"
    )

    assert message is not None
    assert "secret-value" not in message
    assert "sk-abcdefghijk" not in message
    assert message.count("[REDACTED]") >= 1


def test_rejects_large_body_shaped_message() -> None:
    """An arbitrary raw JSON body is not treated as a scalar explanation."""
    assert sanitize_provider_message("{" + "x" * 300 + "}") is None


def test_rejects_oversized_scalar_message() -> None:
    """Oversized probable body dumps are rejected instead of truncated."""
    assert sanitize_provider_message("x" * ((8 * 1024) + 1)) is None


def test_sanitizes_provider_error_parameter_path() -> None:
    """Provider parameter paths retain only bounded structural characters."""
    assert (
        sanitize_provider_error_param("input[0].tools[1].function.arguments")
        == "input[0].tools[1].function.arguments"
    )
    assert sanitize_provider_error_param("input value=secret") is None


def test_extracts_scalar_message_from_json_error_object() -> None:
    """JSON provider objects contribute only their scalar message field."""
    assert (
        extract_provider_message_text(
            '{"error":{"message":"Request rejected","code":"invalid_request"}}'
        )
        == "Request rejected"
    )
    assert (
        extract_provider_message_text('{"detail":"Instructions are required"}')
        == "Instructions are required"
    )


def test_rejects_sdk_serialized_error_message() -> None:
    """SDK status wrappers never cross the provider failure boundary."""
    assert (
        extract_provider_message_text(
            "Error code: 429 - {'error': {'message': 'Request rejected'}}"
        )
        is None
    )


def test_builds_safe_failure_and_stable_fingerprint() -> None:
    """Equivalent provider messages with changing identifiers group together."""
    first = model_provider_failure(
        operation="sampling",
        provider="openai",
        model="gpt-5.6",
        integration="chatgpt_oauth",
        provider_message="Request 1234 failed at https://example.test/a",
        status_code=500,
        provider_code="server_error",
        provider_error_type="api_error",
        provider_error_param=None,
    )
    second = model_provider_failure(
        operation="sampling",
        provider="openai",
        model="gpt-5.6",
        integration="chatgpt_oauth",
        provider_message="Request 9876 failed at https://example.test/b",
        status_code=500,
        provider_code="server_error",
        provider_error_type="api_error",
        provider_error_param=None,
    )

    assert first.category == ModelProviderFailureCategory.PROVIDER_UNAVAILABLE
    assert first.retryability == ModelProviderFailureRetryability.TRANSIENT
    assert first.user_message == (
        "Model provider error: Request 1234 failed at https://example.test/a"
    )
    assert first.fingerprint == second.fingerprint


def test_unknown_failure_raises_internal_error_with_bounded_diagnostics() -> None:
    """Unclassified outcomes bypass provider recovery and remain internal errors."""
    with pytest.raises(
        UnclassifiedModelProviderError,
        match=(
            "^Unclassified model provider failure: operation=compaction, "
            "provider=custom, model=model, provider_code=new_code$"
        ),
    ) as raised:
        model_provider_failure(
            operation="compaction",
            provider="custom",
            model="model",
            integration=None,
            provider_message=None,
            status_code=None,
            provider_code="new_code",
            provider_error_type=None,
            provider_error_param=None,
        )

    assert raised.value.provider_code == "new_code"
    assert raised.value.provider_message is None
    assert not isinstance(raised.value, ModelCallError)


def test_unknown_failure_redacts_internal_diagnostics() -> None:
    """Internal error diagnostics remain bounded and credential-safe."""
    with pytest.raises(UnclassifiedModelProviderError) as raised:
        model_provider_failure(
            operation="sampling",
            provider="custom",
            model="model",
            integration=None,
            provider_message="Rejected api_key=sk-abcdefghijk",
            status_code=None,
            provider_code="future_failure",
            provider_error_type="future_error",
            provider_error_param=None,
        )

    assert "sk-abcdefghijk" not in str(raised.value)
    assert "provider_message=Rejected api_key=[REDACTED]" in str(raised.value)


def test_provider_error_log_fields_cover_unclassified_safe_diagnostics() -> None:
    """Every provider error exposes the same safe structured logging contract."""
    with pytest.raises(UnclassifiedModelProviderError) as raised:
        model_provider_failure(
            operation="sampling",
            provider="custom",
            model="model",
            integration="integration-001",
            provider_message="Rejected api_key=sk-abcdefghijk",
            status_code=None,
            provider_code="future_failure",
            provider_error_type="future_error",
            provider_error_param=None,
        )

    fields = model_provider_error_log_fields(raised.value)

    assert fields == {
        "provider_failure_operation": "sampling",
        "provider_failure_provider": "custom",
        "provider_failure_integration": "integration-001",
        "provider_failure_model": "model",
        "provider_failure_status_code": None,
        "provider_failure_code": "future_failure",
        "provider_failure_error_type": "future_error",
        "provider_failure_error_param": None,
        "provider_failure_message": "Rejected api_key=[REDACTED]",
        "provider_failure_fingerprint": raised.value.fingerprint,
        "provider_failure_category": "unknown",
        "provider_failure_retryability": "unknown",
    }
