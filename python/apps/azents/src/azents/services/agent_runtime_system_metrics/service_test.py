"""Agent Runtime system-metrics read service tests."""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Never

import pytest
from azcommon.result import Failure, Result, Success
from azents_runtime_control.system_metrics import (
    RUNNER_SYSTEM_METRICS_CAPABILITY,
    RunnerSystemMetricAvailability,
    RunnerSystemMetricObservation,
    RunnerSystemMetricsScope,
)

from azents.core.enums import (
    AgentRuntimeCapability,
    RuntimeDesiredState,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    RuntimeSummary,
    WorkspaceUserRole,
)
from azents.repos.agent_runtime.data import (
    AgentRuntime,
    AgentRuntimeActions,
    AgentRuntimeSummaryState,
)
from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeSystemMetricsSample,
)
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.services.agent_runtime.lifecycle_data import (
    AgentAccessDenied,
    AgentNotBelongToWorkspace,
    AgentNotFound,
    AgentRuntimePublicActions,
    AgentRuntimeReadOutput,
)

from .data import (
    AgentRuntimeSystemMetricsOutput,
    RuntimeSystemMetricsSummary,
    RuntimeSystemMetricState,
)
from .service import AgentRuntimeSystemMetricsService

_NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


@dataclasses.dataclass
class _RuntimeReader:
    """Return one fixed authorized Runtime read result."""

    result: Result[
        AgentRuntimeReadOutput,
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
    ]

    async def get(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeReadOutput,
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
    ]:
        del agent_id, workspace_id, workspace_user_id, role
        return self.result


def _available(used: int, total: int) -> RunnerSystemMetricObservation:
    return RunnerSystemMetricObservation(
        availability=RunnerSystemMetricAvailability.AVAILABLE,
        used=used,
        total=total,
    )


def _unavailable() -> RunnerSystemMetricObservation:
    return RunnerSystemMetricObservation(
        availability=RunnerSystemMetricAvailability.UNAVAILABLE,
        used=None,
        total=None,
    )


def _unsupported() -> RunnerSystemMetricObservation:
    return RunnerSystemMetricObservation(
        availability=RunnerSystemMetricAvailability.UNSUPPORTED,
        used=None,
        total=None,
    )


async def test_runtime_free_agent_is_unsupported_without_store_lookup() -> None:
    """An Agent without a managed Runtime has an explicit empty overview."""

    class _NoLookupStore(InMemoryRuntimeCoordinationStore):
        async def get_connection(
            self,
            *,
            kind: RuntimeConnectionKind,
            subject_id: str,
        ) -> Never:
            del kind, subject_id
            raise AssertionError("coordination lookup must not run")

    service = AgentRuntimeSystemMetricsService(
        agent_runtime_service=_RuntimeReader(Success(_read_output(runtime=None))),
        coordination_store=_NoLookupStore(),
        clock=lambda: _NOW,
    )

    result = await service.get(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.MEMBER,
    )

    assert isinstance(result, Success)
    assert result.value.summary is RuntimeSystemMetricsSummary.UNSUPPORTED
    assert result.value.scope is None
    assert result.value.cpu.state is RuntimeSystemMetricState.UNSUPPORTED
    assert result.value.samples == []


@pytest.mark.parametrize(
    ("observations", "age", "expected"),
    [
        (
            (_available(250, 1000), _available(1024, 4096), _available(10, 20)),
            timedelta(minutes=3),
            RuntimeSystemMetricsSummary.FRESH,
        ),
        (
            (_available(250, 1000), _unavailable(), _unsupported()),
            timedelta(minutes=1),
            RuntimeSystemMetricsSummary.PARTIAL,
        ),
        (
            (_available(250, 1000), _available(1024, 4096), _available(10, 20)),
            timedelta(minutes=3, microseconds=1),
            RuntimeSystemMetricsSummary.STALE,
        ),
        (
            (_unavailable(), _unsupported(), _unsupported()),
            timedelta(minutes=1),
            RuntimeSystemMetricsSummary.UNAVAILABLE,
        ),
        (
            (_unsupported(), _unsupported(), _unsupported()),
            timedelta(minutes=1),
            RuntimeSystemMetricsSummary.UNSUPPORTED,
        ),
    ],
)
async def test_connected_capable_summary_precedence(
    observations: tuple[
        RunnerSystemMetricObservation,
        RunnerSystemMetricObservation,
        RunnerSystemMetricObservation,
    ],
    age: timedelta,
    expected: RuntimeSystemMetricsSummary,
) -> None:
    """Connected capable metrics use the approved mixed-state precedence."""
    store = InMemoryRuntimeCoordinationStore()
    generation = await _register_capable(store)
    sample = _sample(
        sequence=1,
        measured_at=_NOW - age,
        observations=observations,
    )
    await store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=generation,
        sample=sample,
    )
    service = _service(store, _runtime(runner_generation=generation))

    result = await _get(service)

    assert result.value.summary is expected
    assert result.value.scope is RunnerSystemMetricsScope.CONTAINER
    assert result.value.samples[0].measured_at == sample.measured_at
    if expected is RuntimeSystemMetricsSummary.FRESH:
        assert result.value.cpu.percentage == 25.0


async def test_connected_capable_generation_without_sample_is_unavailable() -> None:
    """A capable current generation does not fall back to prior history."""
    store = InMemoryRuntimeCoordinationStore()
    previous_generation = await _register_capable(store, connection_id="connection-1")
    await store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=previous_generation,
        sample=_sample(
            sequence=1,
            measured_at=_NOW,
            observations=(
                _available(1, 2),
                _available(1, 2),
                _available(1, 2),
            ),
        ),
    )
    current_generation = await _register_capable(
        store,
        connection_id="connection-2",
    )
    service = _service(store, _runtime(runner_generation=current_generation))

    result = await _get(service)

    assert result.value.summary is RuntimeSystemMetricsSummary.UNAVAILABLE
    assert result.value.samples == []
    assert result.value.cpu.state is RuntimeSystemMetricState.UNAVAILABLE


async def test_connected_runner_without_capability_is_unsupported() -> None:
    """A current old Runner remains operational and reports unsupported metrics."""
    store = InMemoryRuntimeCoordinationStore()
    connection = await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-1",
        owner_replica_id="control-a",
        connected_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        ttl_seconds=3600,
        metadata={"capabilities": ["file.transfer.v1"]},
    )
    service = _service(store, _runtime(runner_generation=connection.generation))

    result = await _get(service)

    assert result.value.summary is RuntimeSystemMetricsSummary.UNSUPPORTED
    assert result.value.cpu.state is RuntimeSystemMetricState.UNSUPPORTED
    assert result.value.samples == []


async def test_stopped_and_disconnected_overlays_preserve_retained_series() -> None:
    """Lifecycle overlays replace current state without deleting trend samples."""
    stopped_store = InMemoryRuntimeCoordinationStore()
    stopped_generation = await _register_capable(stopped_store)
    stopped_sample = _sample(
        sequence=1,
        measured_at=_NOW,
        observations=(
            _available(1, 2),
            _available(1, 2),
            _available(1, 2),
        ),
    )
    await stopped_store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=stopped_generation,
        sample=stopped_sample,
    )
    stopped = await _get(
        _service(
            stopped_store,
            _runtime(runner_generation=stopped_generation),
            summary=RuntimeSummary.STOPPED,
        )
    )

    disconnected_store = InMemoryRuntimeCoordinationStore()
    await disconnected_store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=7,
        sample=stopped_sample,
    )
    disconnected = await _get(
        _service(
            disconnected_store,
            _runtime(runner_generation=7),
        )
    )

    assert stopped.value.summary is RuntimeSystemMetricsSummary.STOPPED
    assert stopped.value.cpu.state is RuntimeSystemMetricState.STOPPED
    assert len(stopped.value.samples) == 1
    assert disconnected.value.summary is RuntimeSystemMetricsSummary.DISCONNECTED
    assert disconnected.value.cpu.state is RuntimeSystemMetricState.DISCONNECTED
    assert len(disconnected.value.samples) == 1


async def test_latest_unavailable_observation_controls_current_projection() -> None:
    """Older available points remain trends but cannot replace the latest state."""
    store = InMemoryRuntimeCoordinationStore()
    generation = await _register_capable(store)
    await store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=generation,
        sample=_sample(
            sequence=1,
            measured_at=_NOW - timedelta(minutes=2),
            observations=(
                _available(1, 2),
                _available(1, 2),
                _available(1, 2),
            ),
        ),
    )
    await store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=generation,
        sample=_sample(
            sequence=2,
            measured_at=_NOW - timedelta(minutes=1),
            observations=(_unavailable(), _available(1, 2), _available(1, 2)),
        ),
    )

    result = await _get(_service(store, _runtime(runner_generation=generation)))

    assert result.value.summary is RuntimeSystemMetricsSummary.PARTIAL
    assert result.value.cpu.state is RuntimeSystemMetricState.UNAVAILABLE
    assert result.value.cpu.used is None
    assert [sample.cpu.availability for sample in result.value.samples] == [
        RunnerSystemMetricAvailability.AVAILABLE,
        RunnerSystemMetricAvailability.UNAVAILABLE,
    ]


async def test_access_failure_is_returned_before_coordination_lookup() -> None:
    """The existing Agent access result remains the endpoint authority."""

    class _NoLookupStore(InMemoryRuntimeCoordinationStore):
        async def get_connection(
            self,
            *,
            kind: RuntimeConnectionKind,
            subject_id: str,
        ) -> Never:
            del kind, subject_id
            raise AssertionError("coordination lookup must not run")

    service = AgentRuntimeSystemMetricsService(
        agent_runtime_service=_RuntimeReader(
            Failure(AgentNotFound(agent_id="agent-1"))
        ),
        coordination_store=_NoLookupStore(),
        clock=lambda: _NOW,
    )

    result = await _get(service)

    assert isinstance(result, Failure)
    assert isinstance(result.error, AgentNotFound)


async def test_store_read_failure_propagates_only_from_metrics_service() -> None:
    """A raised volatile-store read error is not converted into an empty success."""

    class _FailingReadStore(InMemoryRuntimeCoordinationStore):
        async def read_runner_system_metrics(
            self,
            *,
            runtime_id: str,
            generation: int,
            current_time: datetime,
        ) -> list[RuntimeSystemMetricsSample]:
            del runtime_id, generation, current_time
            raise RuntimeError("metrics read unavailable")

    store = _FailingReadStore()
    generation = await _register_capable(store)
    service = _service(store, _runtime(runner_generation=generation))

    with pytest.raises(RuntimeError, match="metrics read unavailable"):
        await _get(service)


def _service(
    store: InMemoryRuntimeCoordinationStore,
    runtime: AgentRuntime,
    *,
    summary: RuntimeSummary = RuntimeSummary.RUNNING,
) -> AgentRuntimeSystemMetricsService:
    return AgentRuntimeSystemMetricsService(
        agent_runtime_service=_RuntimeReader(
            Success(_read_output(runtime=runtime, summary=summary))
        ),
        coordination_store=store,
        clock=lambda: _NOW,
    )


async def _get(
    service: AgentRuntimeSystemMetricsService,
) -> Result[
    AgentRuntimeSystemMetricsOutput,
    AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
]:
    return await service.get(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.MEMBER,
    )


async def _register_capable(
    store: InMemoryRuntimeCoordinationStore,
    *,
    connection_id: str = "connection-1",
) -> int:
    connection = await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id=connection_id,
        owner_replica_id="control-a",
        connected_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        ttl_seconds=3600,
        metadata={
            "capabilities": [
                "file.transfer.v1",
                RUNNER_SYSTEM_METRICS_CAPABILITY,
            ]
        },
    )
    return connection.generation


def _read_output(
    *,
    runtime: AgentRuntime | None,
    summary: RuntimeSummary = RuntimeSummary.STOPPED,
) -> AgentRuntimeReadOutput:
    state = (
        AgentRuntimeSummaryState(
            summary=summary,
            actions=AgentRuntimeActions(
                start=False,
                stop=False,
                restart=False,
                reset=False,
                use_runner=False,
            ),
            failure=None,
        )
        if runtime is not None
        else None
    )
    return AgentRuntimeReadOutput(
        capability=(
            AgentRuntimeCapability.MANAGED
            if runtime is not None
            else AgentRuntimeCapability.NONE
        ),
        capability_version=1,
        runtime_profile_id=None,
        runtime_profile_selection_version=1,
        runtime_profile_status="not_applicable",
        runtime_profile_available=False,
        runtime_profile_availability_reason_code=None,
        removal_impact=None,
        removal=None,
        runtime=runtime,
        state=state,
        configuration=None,
        actions=AgentRuntimePublicActions(
            add=False,
            remove=False,
            start=False,
            stop=False,
            restart=False,
            reset=False,
            observe=False,
            use_runner=False,
        ),
    )


def _runtime(*, runner_generation: int) -> AgentRuntime:
    return AgentRuntime(
        id="runtime-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        runtime_provider_id="provider-1",
        runtime_provider_resource_id=None,
        provider_binding_origin=None,
        provider_binding_evidence=None,
        configuration_sequence=1,
        desired_state=RuntimeDesiredState.RUNNING,
        desired_generation=1,
        last_lifecycle_command=None,
        reset_final_desired_state=None,
        terminal_delete_requested_generation=None,
        terminal_delete_acknowledged_generation=None,
        terminal_delete_acknowledged_at=None,
        terminal_delete_acknowledgement_kind=None,
        provider_observed_state=RuntimeProviderObservedState.RUNNING,
        provider_generation=1,
        provider_observed_generation=1,
        provider_observed_at=_NOW,
        provider_observe_requested_at=None,
        last_lifecycle_dispatch_generation=1,
        provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
        runner_state=RuntimeRunnerState.READY,
        runner_generation=runner_generation,
        workspace_path="/workspace/agent",
        failure_generation=None,
        failure_code=None,
        failure_message=None,
        last_state_change_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _sample(
    *,
    sequence: int,
    measured_at: datetime,
    observations: tuple[
        RunnerSystemMetricObservation,
        RunnerSystemMetricObservation,
        RunnerSystemMetricObservation,
    ],
) -> RuntimeSystemMetricsSample:
    return RuntimeSystemMetricsSample(
        sequence=sequence,
        measured_at=measured_at,
        scope=RunnerSystemMetricsScope.CONTAINER,
        cpu=observations[0],
        memory=observations[1],
        disk=observations[2],
    )
