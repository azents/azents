"""Durable Agent Runtime state sinks for Control gRPC bridges."""

import dataclasses
from typing import Annotated

from azents_runtime_control.provider import (
    RuntimeProviderObservedState as SharedProviderObservedState,
)
from azents_runtime_control.provider import (
    RuntimeProviderReport as SharedRuntimeProviderReport,
)
from azents_runtime_control.runner import (
    RunnerStateReport as SharedRunnerStateReport,
)
from azents_runtime_control.runner import RuntimeRunnerState as SharedRunnerState
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntimeFailurePatch


@dataclasses.dataclass
class RuntimeProviderReportRepositorySink:
    """Persist Provider reports as authoritative Runtime metadata."""

    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def record_provider_report(self, report: SharedRuntimeProviderReport) -> None:
        """Persist one Provider report and its workspace metadata."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_id(
                session, report.runtime_id
            )
            if runtime is None:
                raise ValueError(f"AgentRuntime not found: {report.runtime_id}")

            failure = _provider_workspace_failure(
                workspace_path=report.workspace_path,
                desired_generation=runtime.desired_generation,
            )
            await self.runtime_repository.record_provider_observed_state(
                session,
                report.runtime_id,
                _provider_observed_state(report.observed_state),
                report.observed_desired_generation,
                workspace_path=report.workspace_path or None,
                failure=failure,
                clear_failure=_provider_report_clears_failure(
                    report=report,
                    desired_generation=runtime.desired_generation,
                ),
            )
            await self.runtime_repository.record_provider_connection_state(
                session,
                report.runtime_id,
                RuntimeProviderConnectionState.CONNECTED,
            )


@dataclasses.dataclass
class RuntimeRunnerStateRepositorySink:
    """Persist Runner reports without accepting Runner-owned workspace paths."""

    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def record_runner_state(self, report: SharedRunnerStateReport) -> None:
        """Persist one Runner report, validating it against Provider metadata."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_id(
                session, report.runtime_id
            )
            if runtime is None:
                raise ValueError(f"AgentRuntime not found: {report.runtime_id}")
            failure = _workspace_failure(
                provider_workspace_path=runtime.workspace_path,
                runner_workspace_path=report.workspace_path,
                desired_generation=runtime.desired_generation,
            )
            runner_state = _runner_state(report)
            if failure is None:
                failure = _runner_state_failure(
                    state=report.runner_state,
                    desired_generation=runtime.desired_generation,
                )
            if failure is not None:
                runner_state = RuntimeRunnerState.FAILED

            await self.runtime_repository.record_runner_state(
                session,
                report.runtime_id,
                runner_state,
                report.runner_generation,
                failure=failure,
            )


def _workspace_failure(
    *,
    provider_workspace_path: str | None,
    runner_workspace_path: str,
    desired_generation: int,
) -> AgentRuntimeFailurePatch | None:
    if provider_workspace_path is None:
        return AgentRuntimeFailurePatch(
            generation=desired_generation,
            code="PROVIDER_WORKSPACE_PATH_MISSING",
            message=(
                "Runtime Provider has not reported an Agent Workspace path. "
                "Runner operations are unavailable until Provider metadata is "
                "available."
            ),
        )
    if provider_workspace_path != runner_workspace_path:
        return AgentRuntimeFailurePatch(
            generation=desired_generation,
            code="RUNNER_WORKSPACE_PATH_MISMATCH",
            message=(
                "Runtime Runner workspace path does not match Provider metadata: "
                f"provider={provider_workspace_path}, runner={runner_workspace_path}"
            ),
        )
    return None


def _provider_workspace_failure(
    *,
    workspace_path: str,
    desired_generation: int,
) -> AgentRuntimeFailurePatch | None:
    if workspace_path:
        return None
    return AgentRuntimeFailurePatch(
        generation=desired_generation,
        code="PROVIDER_WORKSPACE_PATH_MISSING",
        message=(
            "Runtime Provider did not report an Agent Workspace path. Runtime "
            "operations are unavailable until Provider metadata is available."
        ),
    )


def _provider_report_clears_failure(
    *,
    report: SharedRuntimeProviderReport,
    desired_generation: int,
) -> bool:
    return (
        report.observed_state == SharedProviderObservedState.RUNNING
        and report.observed_desired_generation >= desired_generation
        and bool(report.workspace_path)
    )


def _provider_observed_state(
    state: SharedProviderObservedState,
) -> RuntimeProviderObservedState:
    return RuntimeProviderObservedState(state.value)


def _runner_state(report: SharedRunnerStateReport) -> RuntimeRunnerState:
    if report.diagnostic.get("reason") == "runner_stream_closed":
        return RuntimeRunnerState.DISCONNECTED
    state = report.runner_state
    if state in {
        SharedRunnerState.UNKNOWN,
        SharedRunnerState.STARTING,
        SharedRunnerState.READY,
        SharedRunnerState.DEGRADED,
        SharedRunnerState.FAILED,
    }:
        return RuntimeRunnerState(state.value)
    return RuntimeRunnerState.FAILED


def _runner_state_failure(
    *,
    state: SharedRunnerState,
    desired_generation: int,
) -> AgentRuntimeFailurePatch | None:
    if state in {
        SharedRunnerState.UNKNOWN,
        SharedRunnerState.STARTING,
        SharedRunnerState.READY,
        SharedRunnerState.DEGRADED,
        SharedRunnerState.FAILED,
    }:
        return None
    return AgentRuntimeFailurePatch(
        generation=desired_generation,
        code="UNSUPPORTED_RUNNER_STATE",
        message=f"Runtime Runner reported unsupported state: {state.value}",
    )
