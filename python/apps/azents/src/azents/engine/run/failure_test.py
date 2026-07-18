"""Tests for failed-run public presentation boundaries."""

import datetime

from azents.engine.run.failure import (
    FailedRunAttempt,
    FailedRunFailureMetadata,
    FailedRunProviderFailure,
    FailedRunRetryState,
)
from azents.engine.run.provider_failure import model_provider_failure


def test_provider_retry_state_hides_diagnostics_from_public_presentation() -> None:
    """Internal provider diagnostics do not cross public retry projections."""
    failure = model_provider_failure(
        operation="sampling",
        provider="openai",
        model="gpt-4o",
        integration="integration-001",
        provider_message="The request was rejected.",
        status_code=400,
        provider_code="invalid_request",
        provider_error_type="bad_request_error",
    )
    occurred_at = datetime.datetime.now(datetime.UTC)
    retry_state = FailedRunRetryState.from_attempt(
        FailedRunAttempt(
            user_message=failure.user_message,
            internal_message=failure.user_message,
            error_type=failure.__class__.__name__,
            source="model",
            visibility="user_visible",
            attempt_number=1,
            occurred_at=occurred_at,
            retryability="non_retryable",
            failure_code=failure.failure_code,
            provider_failure=FailedRunProviderFailure.from_failure(failure),
        ),
        max_retries=2,
        backoff_seconds=1,
        next_retry_at=occurred_at + datetime.timedelta(seconds=1),
    )

    assert retry_state.retryability == "non_retryable"
    assert retry_state.failure_code == "model_provider_invalid_request"
    assert retry_state.provider_failure is not None
    assert retry_state.provider_failure.status_code == 400
    assert retry_state.error_kind == "model_provider"
    assert retry_state.public_retryability == "unknown"
    assert retry_state.public_failure_code is None
    assert retry_state.public_attempts()[0].retryability == "unknown"
    assert retry_state.public_attempts()[0].failure_code is None

    metadata = FailedRunFailureMetadata.from_retry_state(
        retry_state,
        finalization_reason="retry_exhausted",
    )

    assert metadata.error_kind == "model_provider"
    assert metadata.retryability == "unknown"
    assert metadata.failure_code is None
    assert metadata.attempts[0].retryability == "unknown"
    assert metadata.attempts[0].failure_code is None


def test_runtime_retry_state_preserves_existing_public_diagnostics() -> None:
    """Runtime failures keep their existing public retry diagnostics."""
    occurred_at = datetime.datetime.now(datetime.UTC)
    retry_state = FailedRunRetryState.from_attempt(
        FailedRunAttempt(
            user_message="The model stream timed out.",
            internal_message="The model stream timed out.",
            error_type="ModelStreamTimeoutError",
            source="model",
            visibility="user_visible",
            attempt_number=1,
            occurred_at=occurred_at,
            retryability="transient",
            failure_code="model_stream_idle_timeout",
        ),
        max_retries=2,
        backoff_seconds=1,
        next_retry_at=occurred_at + datetime.timedelta(seconds=1),
    )

    assert retry_state.error_kind == "runtime"
    assert retry_state.public_retryability == "transient"
    assert retry_state.public_failure_code == "model_stream_idle_timeout"
    assert retry_state.public_attempts() == retry_state.attempts

    metadata = FailedRunFailureMetadata.from_retry_state(
        retry_state,
        finalization_reason="retry_exhausted",
    )

    assert metadata.error_kind == "runtime"
    assert metadata.retryability == "transient"
    assert metadata.failure_code == "model_stream_idle_timeout"
    assert metadata.attempts == retry_state.attempts
