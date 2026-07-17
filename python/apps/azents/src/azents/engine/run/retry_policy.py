"""Shared failed-run retry budget and backoff policy."""

import dataclasses
import os

_DEFAULT_FAILED_RUN_MAX_RETRIES = 10
_DEFAULT_FAILED_RUN_BASE_BACKOFF_SECONDS = 1
_DEFAULT_FAILED_RUN_BACKOFF_MULTIPLIER = 2
_DEFAULT_FAILED_RUN_MAX_BACKOFF_SECONDS = 60


@dataclasses.dataclass(frozen=True)
class FailedRunRetryPolicy:
    """Retry budget shared by Agent Runs and standalone model operations."""

    max_retries: int
    base_backoff_seconds: int
    backoff_multiplier: int
    max_backoff_seconds: int

    def __post_init__(self) -> None:
        """Validate a finite integer retry policy."""
        if self.max_retries < 0:
            raise ValueError("max_retries must be zero or greater")
        if self.base_backoff_seconds < 0:
            raise ValueError("base_backoff_seconds must be zero or greater")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be one or greater")
        if self.max_backoff_seconds < 0:
            raise ValueError("max_backoff_seconds must be zero or greater")

    def backoff_seconds(self, failed_attempt_number: int) -> int:
        """Return bounded exponential backoff after one failed attempt."""
        if failed_attempt_number < 1:
            raise ValueError("failed_attempt_number must be one or greater")
        raw = self.base_backoff_seconds * (
            self.backoff_multiplier ** (failed_attempt_number - 1)
        )
        return min(raw, self.max_backoff_seconds)

    def retry_available(self, failed_attempt_number: int) -> bool:
        """Return whether another attempt remains after this failure."""
        if failed_attempt_number < 1:
            raise ValueError("failed_attempt_number must be one or greater")
        return failed_attempt_number <= self.max_retries


def get_failed_run_retry_policy() -> FailedRunRetryPolicy:
    """Build the process retry policy from shared environment settings."""
    return FailedRunRetryPolicy(
        max_retries=_int_from_env(
            "AZ_FAILED_RUN_MAX_RETRIES",
            _DEFAULT_FAILED_RUN_MAX_RETRIES,
        ),
        base_backoff_seconds=_int_from_env(
            "AZ_FAILED_RUN_BASE_BACKOFF_SECONDS",
            _DEFAULT_FAILED_RUN_BASE_BACKOFF_SECONDS,
        ),
        backoff_multiplier=_int_from_env(
            "AZ_FAILED_RUN_BACKOFF_MULTIPLIER",
            _DEFAULT_FAILED_RUN_BACKOFF_MULTIPLIER,
        ),
        max_backoff_seconds=_int_from_env(
            "AZ_FAILED_RUN_MAX_BACKOFF_SECONDS",
            _DEFAULT_FAILED_RUN_MAX_BACKOFF_SECONDS,
        ),
    )


def _int_from_env(name: str, default: int) -> int:
    """Read one integer environment setting."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return int(raw_value)
