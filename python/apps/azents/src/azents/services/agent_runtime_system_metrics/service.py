"""Agent-authorized Runtime system-metrics read service."""

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Protocol, assert_never

from azcommon.result import Failure, Result, Success
from azents_runtime_control.system_metrics import (
    RUNNER_SYSTEM_METRICS_CAPABILITY,
    RunnerSystemMetricAvailability,
    RunnerSystemMetricObservation,
)
from fastapi import Depends

from azents.core.enums import RuntimeSummary, WorkspaceUserRole
from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeSystemMetricsSample,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.deps import get_runtime_coordination_store
from azents.services.agent_runtime.lifecycle_data import (
    AgentAccessDenied,
    AgentNotBelongToWorkspace,
    AgentNotFound,
    AgentRuntimeReadOutput,
)
from azents.services.agent_runtime.service import AgentRuntimeService

from .data import (
    AgentRuntimeSystemMetricsOutput,
    RuntimeSystemMetricCurrent,
    RuntimeSystemMetricsSummary,
    RuntimeSystemMetricState,
)
from .data import (
    RuntimeSystemMetricObservation as RuntimeSystemMetricObservationOutput,
)
from .data import (
    RuntimeSystemMetricsSample as RuntimeSystemMetricsSampleOutput,
)

_FRESHNESS_WINDOW = timedelta(minutes=3)


class AgentRuntimeAccessReader(Protocol):
    """Existing Agent access and Runtime lifecycle read boundary."""

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
        """Return the authorized Agent Runtime read model."""
        ...


@dataclasses.dataclass
class AgentRuntimeSystemMetricsService:
    """Read one current-generation volatile Runtime metrics overview."""

    agent_runtime_service: AgentRuntimeAccessReader
    coordination_store: RuntimeCoordinationStore
    clock: Callable[[], datetime]

    async def get(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentRuntimeSystemMetricsOutput,
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
    ]:
        """Authorize through Agent Runtime read and project volatile metrics."""
        result = await self.agent_runtime_service.get(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        match result:
            case Failure(error):
                return Failure(error)
            case Success(read):
                return Success(await self._overview(read))
            case _:
                assert_never(result)

    async def _overview(
        self,
        read: AgentRuntimeReadOutput,
    ) -> AgentRuntimeSystemMetricsOutput:
        runtime = read.runtime
        if runtime is None:
            return _empty_overview()

        current_time = self.clock()
        connection = await self.coordination_store.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=runtime.id,
        )
        connected = connection is not None
        capable = False
        generation = runtime.runner_generation
        if connection is not None:
            generation = connection.generation
            capabilities = connection.metadata.get("capabilities")
            capable = (
                isinstance(capabilities, list)
                and RUNNER_SYSTEM_METRICS_CAPABILITY in capabilities
            )

        samples: list[RuntimeSystemMetricsSample] = []
        if generation > 0 and (not connected or capable):
            samples = await self.coordination_store.read_runner_system_metrics(
                runtime_id=runtime.id,
                generation=generation,
                current_time=current_time,
            )

        stopped = (
            read.state is not None and read.state.summary is RuntimeSummary.STOPPED
        )
        latest = samples[-1] if samples else None
        cpu = _current_metric(
            latest.cpu if latest is not None else None,
            measured_at=latest.measured_at if latest is not None else None,
            current_time=current_time,
            stopped=stopped,
            connected=connected,
            capable=capable,
        )
        memory = _current_metric(
            latest.memory if latest is not None else None,
            measured_at=latest.measured_at if latest is not None else None,
            current_time=current_time,
            stopped=stopped,
            connected=connected,
            capable=capable,
        )
        disk = _current_metric(
            latest.disk if latest is not None else None,
            measured_at=latest.measured_at if latest is not None else None,
            current_time=current_time,
            stopped=stopped,
            connected=connected,
            capable=capable,
        )
        return AgentRuntimeSystemMetricsOutput(
            summary=_summary(
                cpu.state,
                memory.state,
                disk.state,
                stopped=stopped,
                connected=connected,
            ),
            scope=latest.scope if latest is not None else None,
            cpu=cpu,
            memory=memory,
            disk=disk,
            samples=[_sample_output(sample) for sample in samples],
        )


def get_agent_runtime_system_metrics_service(
    agent_runtime_service: Annotated[AgentRuntimeService, Depends()],
    coordination_store: Annotated[
        RuntimeCoordinationStore,
        Depends(get_runtime_coordination_store),
    ],
) -> AgentRuntimeSystemMetricsService:
    """Build the dedicated Runtime metrics read service."""
    return AgentRuntimeSystemMetricsService(
        agent_runtime_service=agent_runtime_service,
        coordination_store=coordination_store,
        clock=_utc_now,
    )


def _current_metric(
    observation: RunnerSystemMetricObservation | None,
    *,
    measured_at: datetime | None,
    current_time: datetime,
    stopped: bool,
    connected: bool,
    capable: bool,
) -> RuntimeSystemMetricCurrent:
    if stopped:
        state = RuntimeSystemMetricState.STOPPED
    elif not connected:
        state = RuntimeSystemMetricState.DISCONNECTED
    elif not capable:
        state = RuntimeSystemMetricState.UNSUPPORTED
    elif observation is None:
        state = RuntimeSystemMetricState.UNAVAILABLE
    elif observation.availability is RunnerSystemMetricAvailability.UNSUPPORTED:
        state = RuntimeSystemMetricState.UNSUPPORTED
    elif observation.availability is RunnerSystemMetricAvailability.UNAVAILABLE:
        state = RuntimeSystemMetricState.UNAVAILABLE
    elif measured_at is not None and current_time - measured_at <= _FRESHNESS_WINDOW:
        state = RuntimeSystemMetricState.FRESH
    else:
        state = RuntimeSystemMetricState.STALE

    used = None
    total = None
    percentage = None
    if (
        observation is not None
        and observation.availability is RunnerSystemMetricAvailability.AVAILABLE
    ):
        used = observation.used
        total = observation.total
        if used is not None and total is not None:
            percentage = round(min(max((used / total) * 100, 0.0), 100.0), 2)
    return RuntimeSystemMetricCurrent(
        state=state,
        measured_at=measured_at,
        used=used,
        total=total,
        percentage=percentage,
    )


def _summary(
    cpu: RuntimeSystemMetricState,
    memory: RuntimeSystemMetricState,
    disk: RuntimeSystemMetricState,
    *,
    stopped: bool,
    connected: bool,
) -> RuntimeSystemMetricsSummary:
    if stopped:
        return RuntimeSystemMetricsSummary.STOPPED
    if not connected:
        return RuntimeSystemMetricsSummary.DISCONNECTED
    states = (cpu, memory, disk)
    if all(state is RuntimeSystemMetricState.FRESH for state in states):
        return RuntimeSystemMetricsSummary.FRESH
    if any(state is RuntimeSystemMetricState.FRESH for state in states):
        return RuntimeSystemMetricsSummary.PARTIAL
    if any(state is RuntimeSystemMetricState.STALE for state in states):
        return RuntimeSystemMetricsSummary.STALE
    if any(state is RuntimeSystemMetricState.UNAVAILABLE for state in states):
        return RuntimeSystemMetricsSummary.UNAVAILABLE
    return RuntimeSystemMetricsSummary.UNSUPPORTED


def _sample_output(
    sample: RuntimeSystemMetricsSample,
) -> RuntimeSystemMetricsSampleOutput:
    return RuntimeSystemMetricsSampleOutput(
        measured_at=sample.measured_at,
        scope=sample.scope,
        cpu=_observation_output(sample.cpu),
        memory=_observation_output(sample.memory),
        disk=_observation_output(sample.disk),
    )


def _observation_output(
    observation: RunnerSystemMetricObservation,
) -> RuntimeSystemMetricObservationOutput:
    return RuntimeSystemMetricObservationOutput(
        availability=observation.availability,
        used=observation.used,
        total=observation.total,
    )


def _empty_overview() -> AgentRuntimeSystemMetricsOutput:
    current = RuntimeSystemMetricCurrent(
        state=RuntimeSystemMetricState.UNSUPPORTED,
        measured_at=None,
        used=None,
        total=None,
        percentage=None,
    )
    return AgentRuntimeSystemMetricsOutput(
        summary=RuntimeSystemMetricsSummary.UNSUPPORTED,
        scope=None,
        cpu=current,
        memory=current.model_copy(),
        disk=current.model_copy(),
        samples=[],
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)
