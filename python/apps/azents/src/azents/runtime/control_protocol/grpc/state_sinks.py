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
    RuntimeDesiredState,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeFailurePatch
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.runtime.control_protocol.data import RuntimeRunnerRegistration


@dataclasses.dataclass
class RuntimeProviderReportRepositorySink:
    """Persist Provider reports as authoritative Runtime metadata."""

    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    policy_repository: Annotated[
        RuntimeProviderPolicyRepository,
        Depends(RuntimeProviderPolicyRepository),
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
            if not await self.runtime_repository.provider_report_matches_binding(
                session,
                runtime_id=report.runtime_id,
                provider_logical_id=report.provider_id,
            ):
                raise ValueError(
                    "Runtime Provider report does not match the immutable "
                    "Runtime Provider binding."
                )

            if _terminal_delete_acknowledged(
                report=report,
                desired_generation=runtime.desired_generation,
            ):
                record_acknowledgement = (
                    self.runtime_repository.record_terminal_delete_acknowledgement
                )
                persisted = await record_acknowledgement(
                    session,
                    report.runtime_id,
                    provider_generation=report.provider_generation,
                    acknowledged_generation=report.observed_desired_generation,
                )
                if persisted is None:
                    return
                await self.runtime_repository.record_provider_connection_state(
                    session,
                    report.runtime_id,
                    RuntimeProviderConnectionState.CONNECTED,
                )
                return

            policy_failure = await self._record_provider_policy_evidence(
                session,
                runtime=runtime,
                report=report,
            )
            failure = policy_failure or _provider_workspace_failure(
                workspace_path=report.workspace_path,
                desired_generation=runtime.desired_generation,
            )
            persisted = await self.runtime_repository.record_provider_observed_state(
                session,
                report.runtime_id,
                _provider_observed_state(report.observed_state),
                report.provider_generation,
                report.observed_desired_generation,
                workspace_path=report.workspace_path or None,
                failure=failure,
                clear_failure=_provider_report_clears_failure(
                    report=report,
                    desired_generation=runtime.desired_generation,
                ),
            )
            if persisted is None:
                return
            await self.runtime_repository.record_provider_connection_state(
                session,
                report.runtime_id,
                RuntimeProviderConnectionState.CONNECTED,
            )

    async def _record_provider_policy_evidence(
        self,
        session: AsyncSession,
        *,
        runtime: AgentRuntime,
        report: SharedRuntimeProviderReport,
    ) -> AgentRuntimeFailurePatch | None:
        provider_id = runtime.runtime_provider_resource_id
        if provider_id is None:
            return _policy_failure(
                runtime.desired_generation,
                "RUNTIME_POLICY_PROVIDER_BINDING_MISSING",
            )
        recorded = (
            await self.policy_repository.record_provider_execution_policy_evidence(
                session,
                runtime_id=report.runtime_id,
                provider_id=provider_id,
                evidence=report.execution_policy,
                acknowledged_at=report.reported_at,
            )
        )
        if recorded is None:
            return _policy_failure(
                runtime.desired_generation,
                "RUNTIME_POLICY_PROVIDER_EVIDENCE_MISMATCH",
            )
        return None


@dataclasses.dataclass
class RuntimeRunnerStateRepositorySink:
    """Persist Runner reports without accepting Runner-owned workspace paths."""

    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    policy_repository: Annotated[
        RuntimeProviderPolicyRepository,
        Depends(RuntimeProviderPolicyRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def validate_runner_registration(
        self,
        registration: RuntimeRunnerRegistration,
    ) -> bool:
        """Validate registration evidence against the exact current target."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_id(
                session,
                registration.runtime_id,
            )
            if runtime is None or runtime.runtime_provider_resource_id is None:
                return False
            matches = (
                await self.policy_repository.execution_policy_evidence_matches_current(
                    session,
                    runtime_id=runtime.id,
                    provider_id=runtime.runtime_provider_resource_id,
                    evidence=registration.execution_policy,
                )
            )
            return matches

    async def record_runner_state(self, report: SharedRunnerStateReport) -> None:
        """Persist one Runner report, validating it against Provider metadata."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_id(
                session, report.runtime_id
            )
            if runtime is None:
                raise ValueError(f"AgentRuntime not found: {report.runtime_id}")
            if (
                runtime.desired_state is RuntimeDesiredState.STOPPED
                and report.diagnostic.get("reason") == "runner_stream_closed"
            ):
                await self.runtime_repository.record_runner_state(
                    session,
                    report.runtime_id,
                    RuntimeRunnerState.DISCONNECTED,
                    report.runner_generation,
                    failure=None,
                )
                return
            if report.execution_policy.desired_generation != runtime.desired_generation:
                return
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
            policy_failure = await self._record_runner_policy_evidence(
                session,
                runtime=runtime,
                report=report,
            )
            if policy_failure is not None:
                failure = policy_failure
            if failure is not None:
                runner_state = RuntimeRunnerState.FAILED

            await self.runtime_repository.record_runner_state(
                session,
                report.runtime_id,
                runner_state,
                report.runner_generation,
                failure=failure,
            )

    async def _record_runner_policy_evidence(
        self,
        session: AsyncSession,
        *,
        runtime: AgentRuntime,
        report: SharedRunnerStateReport,
    ) -> AgentRuntimeFailurePatch | None:
        provider_id = runtime.runtime_provider_resource_id
        if provider_id is None:
            return _policy_failure(
                runtime.desired_generation,
                "RUNTIME_POLICY_PROVIDER_BINDING_MISSING",
            )
        recorded = await self.policy_repository.record_runner_execution_policy_evidence(
            session,
            runtime_id=report.runtime_id,
            provider_id=provider_id,
            evidence=report.execution_policy,
            observed_at=report.reported_at,
        )
        if recorded is None:
            return _policy_failure(
                runtime.desired_generation,
                "RUNTIME_POLICY_RUNNER_EVIDENCE_MISMATCH",
            )
        return None


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


def _policy_failure(
    desired_generation: int,
    code: str,
) -> AgentRuntimeFailurePatch:
    return AgentRuntimeFailurePatch(
        generation=desired_generation,
        code=code,
        message="Runtime execution-policy evidence is missing or does not match.",
    )


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


def _terminal_delete_acknowledged(
    *,
    report: SharedRuntimeProviderReport,
    desired_generation: int,
) -> bool:
    return (
        report.terminal_delete_acknowledged
        and report.observed_state == SharedProviderObservedState.STOPPED
        and report.provider_runtime_id is None
        and report.observed_desired_generation == desired_generation
    )


def _provider_observed_state(
    state: SharedProviderObservedState,
) -> RuntimeProviderObservedState:
    return RuntimeProviderObservedState(state.value)


def _runner_state(report: SharedRunnerStateReport) -> RuntimeRunnerState:
    if report.diagnostic.get("reason") == "runner_stream_closed":
        return RuntimeRunnerState.DISCONNECTED
    state = report.runner_state
    if state == SharedRunnerState.BUSY:
        return RuntimeRunnerState.READY
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
        SharedRunnerState.BUSY,
        SharedRunnerState.DEGRADED,
        SharedRunnerState.FAILED,
    }:
        return None
    return AgentRuntimeFailurePatch(
        generation=desired_generation,
        code="UNSUPPORTED_RUNNER_STATE",
        message=f"Runtime Runner reported unsupported state: {state.value}",
    )
