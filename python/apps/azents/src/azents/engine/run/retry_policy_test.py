"""Shared failed-run retry policy tests."""

import pytest

from azents.engine.run.retry_policy import (
    FailedRunRetryPolicy,
    get_failed_run_retry_policy,
)


def test_retry_policy_applies_complete_budget_and_bounded_backoff() -> None:
    """The configured retry count allows that many retries after failures."""
    policy = FailedRunRetryPolicy(
        max_retries=3,
        base_backoff_seconds=2,
        backoff_multiplier=3,
        max_backoff_seconds=10,
    )

    assert [policy.retry_available(attempt) for attempt in range(1, 5)] == [
        True,
        True,
        True,
        False,
    ]
    assert [policy.backoff_seconds(attempt) for attempt in range(1, 5)] == [
        2,
        6,
        10,
        10,
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_retries": -1}, "max_retries"),
        ({"base_backoff_seconds": -1}, "base_backoff_seconds"),
        ({"backoff_multiplier": 0}, "backoff_multiplier"),
        ({"max_backoff_seconds": -1}, "max_backoff_seconds"),
    ],
)
def test_retry_policy_rejects_invalid_values(
    kwargs: dict[str, int],
    message: str,
) -> None:
    """Invalid retry settings fail during dependency construction."""
    values = {
        "max_retries": 3,
        "base_backoff_seconds": 1,
        "backoff_multiplier": 2,
        "max_backoff_seconds": 60,
        **kwargs,
    }

    with pytest.raises(ValueError, match=message):
        FailedRunRetryPolicy(**values)


def test_retry_policy_reads_shared_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Standalone operations and the worker resolve the same environment values."""
    monkeypatch.setenv("AZ_FAILED_RUN_MAX_RETRIES", "4")
    monkeypatch.setenv("AZ_FAILED_RUN_BASE_BACKOFF_SECONDS", "3")
    monkeypatch.setenv("AZ_FAILED_RUN_BACKOFF_MULTIPLIER", "2")
    monkeypatch.setenv("AZ_FAILED_RUN_MAX_BACKOFF_SECONDS", "20")

    assert get_failed_run_retry_policy() == FailedRunRetryPolicy(
        max_retries=4,
        base_backoff_seconds=3,
        backoff_multiplier=2,
        max_backoff_seconds=20,
    )
