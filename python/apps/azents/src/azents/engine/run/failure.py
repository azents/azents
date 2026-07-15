"""Failed-run error retry/finalization domain models."""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_FAILED_RUN_ATTEMPT_MESSAGE_MAX_LENGTH = 2000

FailedRunAttemptSource = Literal[
    "model",
    "engine",
    "worker",
    "command",
    "session_runner",
    "resolve",
]
FailedRunAttemptVisibility = Literal["user_visible", "internal"]
FailedRunRetryStatus = Literal["waiting"]
FailedRunRetryability = Literal[
    "unknown",
    "transient",
    "user_action_required",
    "non_retryable",
]
FailedRunFinalizationReason = Literal[
    "retry_exhausted",
    "retry_stopped_by_user",
    "non_retryable",
]


class FailedRunAttempt(BaseModel):
    """One run-stopping failed attempt before terminal finalization."""

    model_config = ConfigDict(frozen=True)

    user_message: str = Field(min_length=1, description="User-safe error message")
    internal_message: str | None = Field(
        default=None,
        description="Diagnostic summary for logs/observability only",
    )
    error_type: str = Field(min_length=1, description="Exception class or failure type")
    source: FailedRunAttemptSource = Field(description="Failure source boundary")
    visibility: FailedRunAttemptVisibility = Field(description="Message visibility")
    attempt_number: int = Field(ge=1, description="Failed attempt number")
    occurred_at: datetime.datetime = Field(description="UTC occurrence timestamp")
    retryability: FailedRunRetryability = Field(default="unknown")
    failure_code: str | None = Field(default=None)


class FailedRunAttemptSummary(BaseModel):
    """User-safe failed-run attempt summary for recovery UI."""

    model_config = ConfigDict(frozen=True)

    attempt_number: int = Field(ge=1)
    user_message: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    source: FailedRunAttemptSource
    failed_at: datetime.datetime
    backoff_seconds: int = Field(ge=0)
    next_retry_at: datetime.datetime
    retryability: FailedRunRetryability = Field(default="unknown")
    failure_code: str | None = Field(default=None)
    truncated: bool = Field(default=False)

    @classmethod
    def from_attempt(
        cls,
        attempt: FailedRunAttempt,
        *,
        backoff_seconds: int,
        next_retry_at: datetime.datetime,
    ) -> "FailedRunAttemptSummary":
        """Build a user-safe attempt summary from one failed attempt."""
        user_message = attempt.user_message
        truncated = len(user_message) > _FAILED_RUN_ATTEMPT_MESSAGE_MAX_LENGTH
        if truncated:
            user_message = user_message[:_FAILED_RUN_ATTEMPT_MESSAGE_MAX_LENGTH]
        return cls(
            attempt_number=attempt.attempt_number,
            user_message=user_message,
            error_type=attempt.error_type,
            source=attempt.source,
            failed_at=attempt.occurred_at,
            backoff_seconds=backoff_seconds,
            next_retry_at=next_retry_at,
            retryability=attempt.retryability,
            failure_code=attempt.failure_code,
            truncated=truncated,
        )


class FailedRunRetryState(BaseModel):
    """Durable retry state stored on ``agent_runs.retry_state``."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = Field(default=1, ge=1)
    status: FailedRunRetryStatus = Field(default="waiting")
    failed_attempt_count: int = Field(ge=1)
    max_retries: int = Field(ge=1)
    last_user_message: str = Field(min_length=1)
    last_error_type: str = Field(min_length=1)
    last_source: FailedRunAttemptSource
    last_failed_at: datetime.datetime
    backoff_seconds: int = Field(ge=0)
    next_retry_at: datetime.datetime
    retryability: FailedRunRetryability = Field(default="unknown")
    failure_code: str | None = Field(default=None)
    attempts: list[FailedRunAttemptSummary] = Field(default_factory=list)

    @classmethod
    def from_attempt(
        cls,
        attempt: FailedRunAttempt,
        *,
        max_retries: int,
        backoff_seconds: int,
        next_retry_at: datetime.datetime,
        previous: "FailedRunRetryState | None" = None,
    ) -> "FailedRunRetryState":
        """Build retry state from one failed attempt."""
        attempt_summary = FailedRunAttemptSummary.from_attempt(
            attempt,
            backoff_seconds=backoff_seconds,
            next_retry_at=next_retry_at,
        )
        previous_attempts = [] if previous is None else list(previous.attempts)
        attempts = [*previous_attempts, attempt_summary][-(max_retries + 1) :]
        return cls(
            failed_attempt_count=attempt.attempt_number,
            max_retries=max_retries,
            last_user_message=attempt.user_message,
            last_error_type=attempt.error_type,
            last_source=attempt.source,
            last_failed_at=attempt.occurred_at,
            backoff_seconds=backoff_seconds,
            next_retry_at=next_retry_at,
            retryability=attempt.retryability,
            failure_code=attempt.failure_code,
            attempts=attempts,
        )


class FailedRunFailureMetadata(BaseModel):
    """User-safe metadata for terminal failed-run ``system_error`` events."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["failed_run"] = "failed_run"
    finalization_reason: FailedRunFinalizationReason
    failed_attempt_count: int = Field(ge=1)
    max_retries: int = Field(ge=1)
    last_error_type: str | None = Field(default=None)
    retryability: FailedRunRetryability = Field(default="unknown")
    failure_code: str | None = Field(default=None)
    action_hint: str | None = Field(default=None)
    attempts: list[FailedRunAttemptSummary] = Field(default_factory=list)

    @classmethod
    def from_retry_state(
        cls,
        retry_state: FailedRunRetryState,
        *,
        finalization_reason: FailedRunFinalizationReason,
        action_hint: str | None = None,
    ) -> "FailedRunFailureMetadata":
        """Build terminal metadata from the latest retry state."""
        return cls(
            finalization_reason=finalization_reason,
            failed_attempt_count=retry_state.failed_attempt_count,
            max_retries=retry_state.max_retries,
            last_error_type=retry_state.last_error_type,
            retryability=retry_state.retryability,
            failure_code=retry_state.failure_code,
            action_hint=action_hint,
            attempts=list(retry_state.attempts),
        )
