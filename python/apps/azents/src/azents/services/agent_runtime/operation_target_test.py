"""Agent Runtime explicit-operation target resolver tests."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.core.runtime_profile import RuntimeConfigurationResolutionStatus
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import RuntimeConfigurationRevision
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationAuthority
from azents.services.runtime_profile_resolution.data import (
    RuntimeProfileResolutionResult,
)
from azents.services.runtime_storage_error import RuntimeStorageError

from .service import AgentRuntimeService

_DIGEST = "a" * 64


def _runtime(
    *,
    desired_state: RuntimeDesiredState = RuntimeDesiredState.RUNNING,
    desired_generation: int = 2,
    provider_observed_state: RuntimeProviderObservedState = (
        RuntimeProviderObservedState.RUNNING
    ),
    provider_observed_generation: int | None = None,
    provider_connection_state: RuntimeProviderConnectionState = (
        RuntimeProviderConnectionState.CONNECTED
    ),
    runner_state: RuntimeRunnerState = RuntimeRunnerState.READY,
    runner_generation: int = 3,
    workspace_path: str | None = "/workspace/agent",
    failure_generation: int | None = None,
    failure_code: str | None = None,
    failure_message: str | None = None,
) -> AgentRuntime:
    """Build one Runtime observation for resolver tests."""
    now = datetime.now(UTC)
    return AgentRuntime(
        id="runtime-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        terminal_delete_acknowledgement_kind=None,
        desired_state=desired_state,
        desired_generation=desired_generation,
        provider_observed_state=provider_observed_state,
        provider_observed_generation=(
            desired_generation
            if provider_observed_generation is None
            else provider_observed_generation
        ),
        provider_connection_state=provider_connection_state,
        runner_state=runner_state,
        runner_generation=runner_generation,
        workspace_path=workspace_path,
        failure_generation=failure_generation,
        failure_code=failure_code,
        failure_message=failure_message,
        created_at=now,
        updated_at=now,
    )


def _revision(
    *,
    revision_id: str = "revision-2",
    desired_generation: int = 2,
    qualified: bool = True,
) -> RuntimeConfigurationRevision:
    """Build one desired configuration revision with optional physical evidence."""
    now = datetime.now(UTC)
    return RuntimeConfigurationRevision(
        id=revision_id,
        runtime_id="runtime-1",
        provider_id="provider-1",
        provider_capability_revision_id="capability-1",
        infrastructure_profile_id="profile-1",
        infrastructure_profile_version=2,
        workspace_runtime_profile_id="workspace-profile-1",
        workspace_runtime_profile_version=1,
        agent_selection_version=1,
        resolution_status=RuntimeConfigurationResolutionStatus.READY,
        reason_code=None,
        required_capabilities=(),
        missing_capabilities=(),
        resolved_configuration={},
        source_trace={},
        digest=_DIGEST,
        target_desired_generation=desired_generation,
        provider_reported_digest=_DIGEST if qualified else None,
        runner_reported_digest=_DIGEST if qualified else None,
        provider_acknowledged_at=now if qualified else None,
        runtime_observed_at=now if qualified else None,
        created_at=now,
    )


def _resolution(
    *,
    runtime: AgentRuntime | None = None,
    revision: RuntimeConfigurationRevision | None = None,
    applied: bool = True,
) -> RuntimeProfileResolutionResult:
    """Combine one Runtime and desired/applied revision snapshot."""
    runtime = runtime or _runtime()
    revision = revision or _revision(desired_generation=runtime.desired_generation)
    return RuntimeProfileResolutionResult(
        runtime=runtime,
        desired_revision=revision,
        applied_revision=revision if applied else None,
        runtime_created=False,
    )


class _OperationTargetService(AgentRuntimeService):
    """Supply ordered resolution snapshots without repository dependencies."""

    def __init__(self, resolutions: list[RuntimeProfileResolutionResult]) -> None:
        self.resolutions = resolutions
        self.resolution_index = 0
        self.ensure_runtime_calls = 0
        self.ensure_started_calls = 0
        self.capability_versions = [4]
        self.capability_check_index = 0
        self.capability_available = True

    async def _ensure_runtime_for_agent(
        self,
        agent_id: str,
    ) -> RuntimeProfileResolutionResult:
        """Return the next configured resolution and retain the final snapshot."""
        del agent_id
        self.ensure_runtime_calls += 1
        index = min(self.resolution_index, len(self.resolutions) - 1)
        resolution = self.resolutions[index]
        if self.resolution_index < len(self.resolutions) - 1:
            self.resolution_index += 1
        return resolution

    async def ensure_started_for_agent(self, agent_id: str) -> AgentRuntime:
        """Record the lifecycle request without performing repository writes."""
        del agent_id
        self.ensure_started_calls += 1
        index = min(self.resolution_index, len(self.resolutions) - 1)
        return self.resolutions[index].runtime

    async def _require_runtime_operation_capability(
        self,
        agent_id: str,
        *,
        expected_version: int | None = None,
    ) -> int:
        """Return ordered Agent capability versions for resolver tests."""
        del agent_id
        if not self.capability_available:
            raise RuntimeStorageError("Agent Runtime capability is unavailable.")
        index = min(
            self.capability_check_index,
            len(self.capability_versions) - 1,
        )
        version = self.capability_versions[index]
        if self.capability_check_index < len(self.capability_versions) - 1:
            self.capability_check_index += 1
        if expected_version is not None and version != expected_version:
            raise RuntimeStorageError(
                "Agent Runtime capability changed during the operation."
            )
        return version


async def test_resolve_operation_target_returns_exact_qualified_evidence() -> None:
    """Complete matching evidence returns one immutable operation target."""
    service = _OperationTargetService([_resolution()])

    target = await service.resolve_operation_target("agent-1")

    assert target.id == "runtime-1"
    assert target.runtime_capability_version == 4
    assert target.desired_generation == 2
    assert target.runner_generation == 3
    assert target.configuration_revision_id == "revision-2"
    assert target.workspace_path == "/workspace/agent"


async def test_resolve_operation_target_rejects_before_runtime_resolution() -> None:
    """Runtime-free admission cannot ensure, start, or inspect a Runtime."""
    service = _OperationTargetService([_resolution()])
    service.capability_available = False

    with pytest.raises(RuntimeStorageError, match="capability is unavailable"):
        await service.resolve_operation_target("agent-1")

    assert service.ensure_runtime_calls == 0
    assert service.ensure_started_calls == 0


async def test_resolve_operation_target_waits_for_same_revision_runner() -> None:
    """A slow Runner can qualify without changing the selected target identity."""
    starting = _resolution(
        runtime=_runtime(
            runner_state=RuntimeRunnerState.STARTING,
            runner_generation=1,
            workspace_path=None,
        )
    )
    ready = _resolution()
    service = _OperationTargetService([starting, ready])

    target = await service.resolve_operation_target(
        "agent-1",
        wait_timeout_seconds=1.0,
        poll_interval_seconds=0.0,
    )

    assert target.runner_generation == 3


async def test_resolve_operation_target_requests_start_before_fencing() -> None:
    """A stopped Runtime is started before the resolver fixes target identity."""
    stopped_runtime = _runtime(
        desired_state=RuntimeDesiredState.STOPPED,
        desired_generation=1,
        provider_observed_state=RuntimeProviderObservedState.STOPPED,
        provider_observed_generation=1,
        runner_state=RuntimeRunnerState.DISCONNECTED,
        runner_generation=1,
        workspace_path=None,
    )
    stopped_revision = _revision(
        revision_id="revision-1",
        desired_generation=1,
        qualified=False,
    )
    service = _OperationTargetService(
        [
            _resolution(
                runtime=stopped_runtime,
                revision=stopped_revision,
                applied=False,
            ),
            _resolution(),
        ]
    )

    target = await service.resolve_operation_target("agent-1")

    assert service.ensure_started_calls == 1
    assert target.desired_generation == 2
    assert target.configuration_revision_id == "revision-2"


async def test_resolve_operation_target_can_skip_start_for_nonblocking_call() -> None:
    """A nonblocking caller cannot mutate a stopped Runtime lifecycle."""
    stopped_runtime = _runtime(
        desired_state=RuntimeDesiredState.STOPPED,
        provider_observed_state=RuntimeProviderObservedState.STOPPED,
        runner_state=RuntimeRunnerState.DISCONNECTED,
        workspace_path=None,
    )
    service = _OperationTargetService(
        [_resolution(runtime=stopped_runtime, applied=False)]
    )

    with pytest.raises(RuntimeStorageError, match="Runtime is not running"):
        await service.resolve_operation_target(
            "agent-1",
            wait_timeout_seconds=0.0,
            start_if_stopped=False,
        )

    assert service.ensure_started_calls == 0


async def test_resolve_operation_target_rejects_prompt_authority_change() -> None:
    """An operation cannot retarget after the prompt-selected Profile changes."""
    changed = _resolution(
        revision=_revision(
            revision_id="revision-3",
            desired_generation=3,
        ),
        runtime=_runtime(desired_generation=3),
    )
    service = _OperationTargetService([changed])

    with pytest.raises(RuntimeStorageError, match="operation context"):
        await service.resolve_operation_target(
            "agent-1",
            expected_authority=RuntimeOperationAuthority(
                configuration_revision_id="revision-2",
                configuration_digest=_DIGEST,
                desired_generation=2,
            ),
        )


async def test_resolve_operation_target_rejects_superseded_revision() -> None:
    """An external generation change cannot retarget an operation already waiting."""
    starting = _resolution(
        runtime=_runtime(
            runner_state=RuntimeRunnerState.STARTING,
            runner_generation=1,
            workspace_path=None,
        )
    )
    superseded_runtime = _runtime(desired_generation=3)
    superseded_revision = _revision(
        revision_id="revision-3",
        desired_generation=3,
    )
    service = _OperationTargetService(
        [
            starting,
            _resolution(
                runtime=superseded_runtime,
                revision=superseded_revision,
            ),
        ]
    )

    with pytest.raises(RuntimeStorageError, match="configuration changed"):
        await service.resolve_operation_target(
            "agent-1",
            wait_timeout_seconds=1.0,
            poll_interval_seconds=0.0,
        )


async def test_resolve_operation_target_rejects_current_generation_failure() -> None:
    """Current lifecycle failure terminates the explicit wait immediately."""
    failed_runtime = _runtime(
        failure_generation=2,
        failure_code="CONTAINMENT_UNAVAILABLE",
        failure_message="Containment backend is unavailable.",
    )
    service = _OperationTargetService([_resolution(runtime=failed_runtime)])

    with pytest.raises(RuntimeStorageError, match="Containment backend"):
        await service.resolve_operation_target("agent-1")


async def test_resolve_operation_target_waits_for_provider_reconnection() -> None:
    """A transient Provider gap can recover without changing target identity."""
    disconnected = _runtime(
        provider_connection_state=RuntimeProviderConnectionState.DISCONNECTED
    )
    service = _OperationTargetService(
        [
            _resolution(runtime=disconnected),
            _resolution(),
        ]
    )

    target = await service.resolve_operation_target(
        "agent-1",
        wait_timeout_seconds=1.0,
        poll_interval_seconds=0.0,
    )

    assert target.desired_generation == 2
    assert target.configuration_revision_id == "revision-2"


async def test_resolve_operation_target_reports_provider_timeout() -> None:
    """A Provider that stays disconnected fails after the bounded wait."""
    disconnected = _runtime(
        provider_connection_state=RuntimeProviderConnectionState.DISCONNECTED
    )
    service = _OperationTargetService([_resolution(runtime=disconnected)])

    with pytest.raises(RuntimeStorageError, match="Provider is disconnected"):
        await service.resolve_operation_target(
            "agent-1",
            wait_timeout_seconds=0.0,
            poll_interval_seconds=0.0,
        )


@pytest.mark.parametrize(
    "runtime",
    [
        _runtime(provider_connection_state=RuntimeProviderConnectionState.DISCONNECTED),
        _runtime(
            failure_generation=2,
            failure_code="CONTAINMENT_UNAVAILABLE",
        ),
    ],
)
def test_qualified_operation_target_rejects_nonoperational_authority(
    runtime: AgentRuntime,
) -> None:
    """Shared qualification keeps API availability aligned with resolver gates."""
    assert (
        AgentRuntimeService._qualified_operation_target(
            _resolution(runtime=runtime),
            runtime_capability_version=4,
        )
        is None
    )


async def test_resolve_operation_target_rejects_capability_change_before_return() -> (
    None
):
    """A capability version change fences a target before Runner dispatch."""
    service = _OperationTargetService([_resolution()])
    service.capability_versions = [4, 4, 5]

    with pytest.raises(RuntimeStorageError, match="capability changed"):
        await service.resolve_operation_target("agent-1")


async def test_resolve_operation_target_times_out_without_runner_readiness() -> None:
    """An unqualified Runner returns the bounded caller-facing timeout result."""
    unavailable = _resolution(
        runtime=_runtime(
            runner_state=RuntimeRunnerState.STARTING,
            runner_generation=1,
            workspace_path=None,
        )
    )
    service = _OperationTargetService([unavailable])

    with pytest.raises(RuntimeStorageError, match="runner is not ready"):
        await service.resolve_operation_target(
            "agent-1",
            wait_timeout_seconds=0.0,
            poll_interval_seconds=0.0,
        )


async def test_resolve_operation_target_caps_poll_sleep_at_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The polling interval cannot extend the caller's configured wait deadline."""
    unavailable = _resolution(
        runtime=_runtime(
            runner_state=RuntimeRunnerState.STARTING,
            runner_generation=1,
            workspace_path=None,
        )
    )
    service = _OperationTargetService([unavailable])
    monotonic_values = iter((100.0, 100.25, 100.5))
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(
        "azents.services.agent_runtime.service.time",
        SimpleNamespace(monotonic=lambda: next(monotonic_values)),
    )
    monkeypatch.setattr(
        "azents.services.agent_runtime.service.asyncio",
        SimpleNamespace(sleep=fake_sleep),
    )

    with pytest.raises(RuntimeStorageError, match="runner is not ready"):
        await service.resolve_operation_target(
            "agent-1",
            wait_timeout_seconds=0.5,
            poll_interval_seconds=10.0,
        )

    assert sleep_calls == [0.25]


async def test_resolve_operation_target_wait_is_cancellable() -> None:
    """Cancellation propagates rather than becoming an operation failure."""
    unavailable = _resolution(
        runtime=_runtime(
            runner_state=RuntimeRunnerState.STARTING,
            runner_generation=1,
            workspace_path=None,
        )
    )
    service = _OperationTargetService([unavailable])
    task = asyncio.create_task(
        service.resolve_operation_target(
            "agent-1",
            wait_timeout_seconds=60.0,
            poll_interval_seconds=60.0,
        )
    )
    await asyncio.sleep(0)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
