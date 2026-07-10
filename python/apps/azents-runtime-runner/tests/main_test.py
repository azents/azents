"""Runtime Runner entrypoint configuration tests."""

import pytest
from pytest import MonkeyPatch

from azents_runtime_runner.main import (
    RunnerLimitConfig,
    run_runtime_runner,
    runner_limit_config_from_env,
)


@pytest.mark.asyncio
async def test_runner_requires_auth_credential_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner startup requires the provider-injected credential identifier."""
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ENDPOINT", "runtime-control:8030")
    monkeypatch.setenv("AZ_RUNTIME_ID", "runtime-1")
    monkeypatch.setenv("AZ_AGENT_WORKSPACE_PATH", "/workspace/agent")
    monkeypatch.delenv("AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID", raising=False)

    with pytest.raises(SystemExit, match="AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"):
        await run_runtime_runner()


_LIMIT_ENV_NAMES = (
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS_PER_SESSION",
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_SYSTEM_OPERATIONS",
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS",
    "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS_PER_OWNER",
    "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS",
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_CONTROL_OPERATIONS",
)


def _clear_limit_env(monkeypatch: MonkeyPatch) -> None:
    for name in _LIMIT_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_runner_limit_config_from_env_defaults(monkeypatch: MonkeyPatch) -> None:
    """Use the approved defaults when limit variables are absent."""
    _clear_limit_env(monkeypatch)

    assert runner_limit_config_from_env() == RunnerLimitConfig(
        max_concurrent_operations_per_session=10,
        max_concurrent_system_operations=10,
        max_concurrent_operations=50,
        max_pending_operations_per_owner=100,
        max_pending_operations=1_000,
        max_concurrent_control_operations=4,
    )


def test_runner_limit_config_from_env_reads_overrides(monkeypatch: MonkeyPatch) -> None:
    """Parse explicit positive integer overrides."""
    values = ("3", "4", "12", "20", "80", "2")
    for name, value in zip(_LIMIT_ENV_NAMES, values, strict=True):
        monkeypatch.setenv(name, value)

    assert runner_limit_config_from_env() == RunnerLimitConfig(
        max_concurrent_operations_per_session=3,
        max_concurrent_system_operations=4,
        max_concurrent_operations=12,
        max_pending_operations_per_owner=20,
        max_pending_operations=80,
        max_concurrent_control_operations=2,
    )


@pytest.mark.parametrize("value", ["0", "-1", "invalid", "1.5"])
def test_runner_limit_config_from_env_rejects_non_positive_integer(
    monkeypatch: MonkeyPatch,
    value: str,
) -> None:
    """Reject invalid execution limit values."""
    _clear_limit_env(monkeypatch)
    monkeypatch.setenv(
        "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS_PER_SESSION",
        value,
    )

    with pytest.raises(
        SystemExit,
        match=(
            "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS_PER_SESSION must be a "
            "positive integer"
        ),
    ):
        runner_limit_config_from_env()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        (
            "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS_PER_SESSION",
            "51",
            "must not exceed AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS",
        ),
        (
            "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_SYSTEM_OPERATIONS",
            "51",
            "must not exceed AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS",
        ),
        (
            "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS_PER_OWNER",
            "9",
            "must not be smaller than an owner concurrency limit",
        ),
        (
            "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS",
            "49",
            "must not be smaller than AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS",
        ),
    ],
)
def test_runner_limit_config_from_env_rejects_invalid_relationships(
    monkeypatch: MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    """Reject limit combinations that cannot enforce the configured bounds."""
    _clear_limit_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit, match=message):
        runner_limit_config_from_env()


def test_runner_limit_config_from_env_rejects_owner_pending_above_runtime_pending(
    monkeypatch: MonkeyPatch,
) -> None:
    """Keep an owner pending bound within the Runtime pending bound."""
    _clear_limit_env(monkeypatch)
    monkeypatch.setenv("AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS_PER_OWNER", "101")
    monkeypatch.setenv("AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS", "100")

    with pytest.raises(
        SystemExit,
        match="must not exceed AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS",
    ):
        runner_limit_config_from_env()
