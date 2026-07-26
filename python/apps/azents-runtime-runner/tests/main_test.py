"""Runtime Runner entrypoint configuration tests."""

# pyright: reportPrivateUsage=false

import json
import logging
from pathlib import Path

import pytest
from pytest import MonkeyPatch

import azents_runtime_runner.main as runner_main
from azents_runtime_runner.main import (
    RunnerLimitConfig,
    StructuredLogFormatter,
    _execution_policy_evidence_from_env,
    _protected_staging_directory_from_env,
    run_runtime_runner,
    runner_limit_config_from_env,
)


@pytest.mark.asyncio
async def test_runner_requires_auth_credential_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner startup requires the provider-injected credential identifier."""
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ENDPOINT", "runtime-control:8030")
    monkeypatch.setenv("AZ_RUNTIME_TRANSFER_ENDPOINT", "runtime-transfer:8031")
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ALLOW_INSECURE", "true")
    monkeypatch.setenv("AZ_RUNTIME_ID", "runtime-1")
    monkeypatch.setenv("AZ_AGENT_WORKSPACE_PATH", "/workspace/agent")
    monkeypatch.delenv("AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID", raising=False)

    with pytest.raises(SystemExit, match="AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"):
        await run_runtime_runner()


@pytest.mark.asyncio
async def test_runner_requires_auth_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner startup requires the provider-injected signed credential."""
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ENDPOINT", "runtime-control:8030")
    monkeypatch.setenv("AZ_RUNTIME_TRANSFER_ENDPOINT", "runtime-transfer:8031")
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ALLOW_INSECURE", "true")
    monkeypatch.setenv("AZ_RUNTIME_ID", "runtime-1")
    monkeypatch.setenv("AZ_AGENT_WORKSPACE_PATH", "/workspace/agent")
    monkeypatch.setenv("AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID", "credential-1")
    monkeypatch.delenv("AZ_RUNTIME_RUNNER_AUTH_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="AZ_RUNTIME_RUNNER_AUTH_TOKEN"):
        await run_runtime_runner()


def test_runner_reads_provider_injected_policy_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZ_RUNTIME_EXECUTION_POLICY_SNAPSHOT_ID", "snapshot-1")
    monkeypatch.setenv("AZ_RUNTIME_EXECUTION_POLICY_DIGEST", "a" * 64)
    monkeypatch.setenv("AZ_RUNTIME_EXECUTION_POLICY_DESIRED_GENERATION", "3")
    monkeypatch.setenv(
        "AZ_RUNTIME_EXECUTION_POLICY_MODULE_VERSIONS",
        json.dumps({"docker": 1, "runtime.resources": 1}),
    )
    monkeypatch.setenv(
        "AZ_RUNTIME_EXECUTION_POLICY_SOURCE_VERSIONS",
        json.dumps({"profile": 2, "workspace": 3, "agent": 4}),
    )

    evidence = _execution_policy_evidence_from_env()

    assert evidence is not None
    assert evidence.snapshot_id == "snapshot-1"
    assert evidence.desired_generation == 3
    assert evidence.source_versions["agent"] == 4


@pytest.mark.asyncio
async def test_runner_requires_explicit_transfer_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner startup rejects a deployment without transfer endpoint wiring."""
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ENDPOINT", "runtime-control:8030")
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ALLOW_INSECURE", "true")
    monkeypatch.delenv("AZ_RUNTIME_TRANSFER_ENDPOINT", raising=False)

    with pytest.raises(SystemExit, match="AZ_RUNTIME_TRANSFER_ENDPOINT"):
        await run_runtime_runner()


def test_protected_staging_requires_provider_created_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    staging = tmp_path / "missing-staging"
    monkeypatch.setenv("AZ_RUNTIME_TRANSFER_STAGING_DIRECTORY", str(staging))
    monkeypatch.setattr(runner_main.os, "geteuid", lambda: 0)

    with pytest.raises(SystemExit, match="AZ_RUNTIME_TRANSFER_STAGING_DIRECTORY"):
        _protected_staging_directory_from_env()

    assert not staging.exists()


def test_protected_staging_rejects_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    staging = tmp_path / "staging"
    staging.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("AZ_RUNTIME_TRANSFER_STAGING_DIRECTORY", str(staging))
    monkeypatch.setattr(runner_main.os, "geteuid", lambda: 0)

    with pytest.raises(SystemExit, match="AZ_RUNTIME_TRANSFER_STAGING_DIRECTORY"):
        _protected_staging_directory_from_env()


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


def test_structured_log_formatter_keeps_runner_diagnostics() -> None:
    record = logging.LogRecord(
        name="azents_runtime_control.runner",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Runtime Runner operation scheduled",
        args=(),
        exc_info=None,
    )
    record.__dict__.update(
        {
            "owner_session_id": "session-1",
            "runtime_active_operations": 2,
            "queue_wait_ms": 12.5,
        }
    )

    payload = json.loads(StructuredLogFormatter().format(record))

    assert payload["message"] == "Runtime Runner operation scheduled"
    assert payload["owner_session_id"] == "session-1"
    assert payload["runtime_active_operations"] == 2
    assert payload["queue_wait_ms"] == 12.5


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
