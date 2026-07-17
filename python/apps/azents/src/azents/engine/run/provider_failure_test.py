"""Provider-neutral model failure contract tests."""

import pytest

from azents.engine.run.provider_failure import (
    ModelProviderFailureCategory,
    ModelProviderFailureRetryability,
    classify_model_provider_failure,
    model_provider_failure,
    sanitize_provider_identifier,
    sanitize_provider_message,
)


@pytest.mark.parametrize(
    ("status_code", "code", "expected"),
    [
        (401, None, ModelProviderFailureCategory.AUTHENTICATION),
        (403, None, ModelProviderFailureCategory.PERMISSION),
        (402, None, ModelProviderFailureCategory.QUOTA_OR_BILLING),
        (429, None, ModelProviderFailureCategory.RATE_LIMIT),
        (500, None, ModelProviderFailureCategory.PROVIDER_UNAVAILABLE),
        (None, "context_length_exceeded", ModelProviderFailureCategory.CONTEXT_LIMIT),
        (None, "content_filter", ModelProviderFailureCategory.CONTENT_POLICY),
        (None, "model_not_found", ModelProviderFailureCategory.MODEL_UNAVAILABLE),
        (None, "websocket_timeout", ModelProviderFailureCategory.TRANSPORT),
        (400, "invalid_prompt", ModelProviderFailureCategory.INVALID_REQUEST),
        (None, "new_provider_code", ModelProviderFailureCategory.UNKNOWN),
    ],
)
def test_classifies_provider_neutral_categories(
    status_code: int | None,
    code: str | None,
    expected: ModelProviderFailureCategory,
) -> None:
    """Provider identifiers map into the closed neutral taxonomy."""
    assert (
        classify_model_provider_failure(
            status_code=status_code,
            provider_code=code,
            provider_error_type=None,
        )
        == expected
    )


def test_sanitizes_provider_message_and_redacts_credentials() -> None:
    """Only bounded scalar provider text crosses the adapter boundary."""
    message = sanitize_provider_message(
        "Denied. Authorization: Bearer secret-value "
        "api\x00_key=sk-abcdefghijk credential=opaque-secret"
    )

    assert message is not None
    assert "secret-value" not in message
    assert "sk-abcdefghijk" not in message
    assert "opaque-secret" not in message
    assert message.count("[REDACTED]") >= 2


def test_rejects_large_body_shaped_message() -> None:
    """An arbitrary raw JSON body is not treated as a scalar explanation."""
    assert sanitize_provider_message("{" + "x" * 300 + "}") is None


@pytest.mark.parametrize(
    "message",
    [
        "input: user-secret-text",
        "prompt = user-secret-text",
        'request: {"api_key":"secret"}',
        "content: sensitive user message",
    ],
)
def test_rejects_echoed_request_input(message: str) -> None:
    """Provider text must not retain echoed model request fields."""
    assert sanitize_provider_message(message) is None


@pytest.mark.parametrize(
    "identifier",
    [
        "a" * 97,
        "a" * 32,
        "sk-abcdefghijklmnopqrstuvwxyz123456",
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
    ],
)
def test_rejects_unsafe_provider_identifiers(identifier: str) -> None:
    """Provider code and type fields reject truncation and credential shapes."""
    assert sanitize_provider_identifier(identifier) is None


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
    )

    assert first.category == ModelProviderFailureCategory.PROVIDER_UNAVAILABLE
    assert first.retryability == ModelProviderFailureRetryability.TRANSIENT
    assert first.user_message == (
        "Model provider error: Request 1234 failed at https://example.test/a"
    )
    assert first.fingerprint == second.fingerprint


def test_unknown_failure_uses_bounded_fallback() -> None:
    """Missing provider text remains attributed without inventing diagnostics."""
    failure = model_provider_failure(
        operation="compaction",
        provider="custom",
        model="model",
        integration=None,
        provider_message=None,
        status_code=None,
        provider_code="new_code",
        provider_error_type=None,
    )

    assert failure.category == ModelProviderFailureCategory.UNKNOWN
    assert failure.retryability == ModelProviderFailureRetryability.UNKNOWN
    assert failure.user_message == (
        "Model provider error: The model provider could not process the request."
    )
