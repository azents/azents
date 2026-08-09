"""Runtime Runner entrypoint configuration tests."""

import json
import logging
from collections.abc import Mapping
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from azents_runtime_runner.containment import (
    ContainmentQualificationError,
    ExecutionBackend,
    ExecutionProcess,
    ExecutionSpec,
)
from azents_runtime_runner.main import (
    RunnerLimitConfig,
    StructuredLogFormatter,
    _runtime_configuration_evidence_from_env,
    resolve_workspace_path,
    run_runtime_runner,
    runner_limit_config_from_env,
)
from azents_runtime_runner.workspace import FilesystemAccessPolicy


@pytest.mark.asyncio
async def test_runner_requires_auth_credential_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner startup requires the provider-injected credential identifier."""
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ENDPOINT", "runtime-control:8030")
    monkeypatch.setenv("AZ_RUNTIME_TRANSFER_ENDPOINT", "runtime-transfer:8031")
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ALLOW_INSECURE", "true")
    monkeypatch.setenv("AZ_RUNTIME_ID", "runtime-1")
    monkeypatch.setenv("HOME", "/runtime/home")
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
    monkeypatch.setenv("HOME", "/runtime/home")
    monkeypatch.setenv("AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID", "credential-1")
    monkeypatch.delenv("AZ_RUNTIME_RUNNER_AUTH_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="AZ_RUNTIME_RUNNER_AUTH_TOKEN"):
        await run_runtime_runner()


def test_resolve_workspace_path_prefers_explicit_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit Runner input overrides HOME."""
    monkeypatch.setenv("HOME", "/runtime/home")

    assert resolve_workspace_path("/runtime/custom/../workspace") == (
        "/runtime/workspace"
    )


def test_resolve_workspace_path_uses_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runner uses HOME when explicit input is absent."""
    monkeypatch.setenv("HOME", "/runtime/home/../workspace")

    assert resolve_workspace_path(None) == "/runtime/workspace"


@pytest.mark.parametrize("path", ["", "relative/path"])
def test_resolve_workspace_path_rejects_invalid_input(path: str) -> None:
    """Runner rejects missing and relative workspace paths."""
    with pytest.raises(SystemExit):
        resolve_workspace_path(path)


def test_resolve_workspace_path_requires_home_when_input_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner rejects startup without explicit input or HOME."""
    monkeypatch.delenv("HOME", raising=False)

    with pytest.raises(SystemExit):
        resolve_workspace_path(None)


def test_runner_reads_provider_injected_configuration_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZ_RUNTIME_CONFIGURATION_REVISION_ID", "revision-1")
    monkeypatch.setenv("AZ_RUNTIME_CONFIGURATION_DIGEST", "a" * 64)
    monkeypatch.setenv("AZ_RUNTIME_CONFIGURATION_DESIRED_GENERATION", "3")

    evidence = _runtime_configuration_evidence_from_env()

    assert evidence.revision_id == "revision-1"
    assert evidence.digest == "a" * 64
    assert evidence.desired_generation == 3


class _FakeExecutionBackend:
    def __init__(self, *, qualification_error: str | None = None) -> None:
        self.qualification_error = qualification_error
        self.qualified = 0
        self.closed = 0

    @property
    def kind(self) -> str:
        return "fake"

    @property
    def filesystem_access_policy(self) -> FilesystemAccessPolicy:
        return FilesystemAccessPolicy.unrestricted()

    def agent_environment(
        self,
        *,
        workspace_path: str,
        operation_environment: Mapping[str, str],
    ) -> Mapping[str, str]:
        del workspace_path
        return dict(operation_environment)

    async def qualify(self) -> None:
        self.qualified += 1
        if self.qualification_error is not None:
            raise ContainmentQualificationError(self.qualification_error)

    async def start(self, spec: ExecutionSpec) -> ExecutionProcess:
        del spec
        raise AssertionError("startup tests do not execute Agent processes")

    async def close(self) -> None:
        self.closed += 1


def _set_required_runner_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    workspace_path: Path,
) -> None:
    values: Mapping[str, str] = {
        "AZ_RUNTIME_CONTROL_ENDPOINT": "runtime-control:8030",
        "AZ_RUNTIME_TRANSFER_ENDPOINT": "runtime-transfer:8031",
        "AZ_RUNTIME_CONTROL_ALLOW_INSECURE": "true",
        "AZ_RUNTIME_ID": "runtime-1",
        "HOME": str(workspace_path),
        "AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID": "credential-1",
        "AZ_RUNTIME_RUNNER_AUTH_TOKEN": "runner-token",
        "AZ_RUNTIME_CONFIGURATION_REVISION_ID": "revision-1",
        "AZ_RUNTIME_CONFIGURATION_DIGEST": "a" * 64,
        "AZ_RUNTIME_CONFIGURATION_DESIRED_GENERATION": "3",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.mark.asyncio
async def test_containment_qualification_failure_prevents_control_client_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_runner_env(monkeypatch, workspace_path=tmp_path)
    backend = _FakeExecutionBackend(qualification_error="probe_failed")

    def select_backend(*, workspace_path: str) -> ExecutionBackend:
        del workspace_path
        return backend

    monkeypatch.setattr(
        "azents_runtime_runner.main.execution_backend_from_environment",
        select_backend,
    )

    def fail_control_client(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Control client must not be constructed before qualification")

    monkeypatch.setattr(
        "azents_runtime_runner.main.GrpcRunnerControlClient.from_endpoint",
        fail_control_client,
    )

    with pytest.raises(SystemExit, match="probe_failed"):
        await run_runtime_runner()

    assert backend.qualified == 1
    assert backend.closed == 1


@pytest.mark.asyncio
async def test_successful_qualification_precedes_control_client_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_runner_env(monkeypatch, workspace_path=tmp_path)
    backend = _FakeExecutionBackend()

    def select_backend(*, workspace_path: str) -> ExecutionBackend:
        del workspace_path
        return backend

    monkeypatch.setattr(
        "azents_runtime_runner.main.execution_backend_from_environment",
        select_backend,
    )

    def stop_after_qualification(*_args: object, **_kwargs: object) -> None:
        assert backend.qualified == 1
        raise RuntimeError("stop after qualification")

    monkeypatch.setattr(
        "azents_runtime_runner.main.GrpcRunnerControlClient.from_endpoint",
        stop_after_qualification,
    )

    with pytest.raises(RuntimeError, match="stop after qualification"):
        await run_runtime_runner()

    assert backend.qualified == 1
    assert backend.closed == 1


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
