"""Durable Agent Runtime state sinks for Control gRPC bridges."""

import dataclasses
import posixpath
from pathlib import PurePosixPath
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
from azents_runtime_control.runtime_configuration import (
    RuntimeConfigurationEvidence,
)
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
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.runtime.control_protocol.data import RuntimeRunnerRegistration


@dataclasses.dataclass
class RuntimeProviderReportRepositorySink:
    """Persist Provider lifecycle and configuration reports."""

    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository,
        Depends(RuntimeProfileRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def record_provider_report(self, report: SharedRuntimeProviderReport) -> None:
        """Persist one Provider report."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_id(
                session, report.runtime_id
            )
            if runtime is None:
                # Providers can retain a stale observation after terminal Runtime
                # finalization. The Provider stream is shared, so an orphan report
                # must not interrupt reports and commands for active Runtimes.
                return
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

            configuration_failure = await self._record_provider_configuration_evidence(
                session,
                runtime=runtime,
                report=report,
            )
            persisted = await self.runtime_repository.record_provider_observed_state(
                session,
                report.runtime_id,
                _provider_observed_state(report.observed_state),
                report.provider_generation,
                report.observed_desired_generation,
                failure=configuration_failure,
                clear_failure=_provider_report_clears_failure(
                    report=report,
                    desired_generation=runtime.desired_generation,
                    failure_code=runtime.failure_code,
                ),
            )
            if persisted is None:
                return
            await self.runtime_repository.record_provider_connection_state(
                session,
                report.runtime_id,
                RuntimeProviderConnectionState.CONNECTED,
            )

    async def _record_provider_configuration_evidence(
        self,
        session: AsyncSession,
        *,
        runtime: AgentRuntime,
        report: SharedRuntimeProviderReport,
    ) -> AgentRuntimeFailurePatch | None:
        if report.observed_state is not SharedProviderObservedState.RUNNING:
            return None
        provider_id = runtime.runtime_provider_resource_id
        if provider_id is None:
            return _configuration_failure(
                runtime.desired_generation,
                "RUNTIME_CONFIGURATION_PROVIDER_BINDING_MISSING",
            )
        recorded = await self.profile_repository.record_provider_configuration_evidence(
            session,
            runtime_id=report.runtime_id,
            provider_id=provider_id,
            evidence=report.runtime_configuration,
            acknowledged_at=report.reported_at,
        )
        if recorded is None:
            if await self.profile_repository.configuration_evidence_matches_applied(
                session,
                runtime_id=runtime.id,
                provider_id=provider_id,
                evidence=report.runtime_configuration,
            ):
                return None
            return _configuration_failure(
                runtime.desired_generation,
                "RUNTIME_CONFIGURATION_PROVIDER_EVIDENCE_MISMATCH",
            )
        return None


@dataclasses.dataclass
class RuntimeRunnerStateRepositorySink:
    """Persist Runner state and authoritative Agent Workspace paths."""

    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository,
        Depends(RuntimeProfileRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def validate_runner_registration(
        self,
        registration: RuntimeRunnerRegistration,
    ) -> bool:
        """Validate registration evidence against the current transport target."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_id(
                session,
                registration.runtime_id,
            )
            if runtime is None or runtime.runtime_provider_resource_id is None:
                return False
            matches_current = (
                await self.profile_repository.configuration_evidence_matches_current(
                    session,
                    runtime_id=runtime.id,
                    provider_id=runtime.runtime_provider_resource_id,
                    evidence=registration.runtime_configuration,
                )
            )
            if matches_current:
                return True
            return await self._runner_evidence_matches_applied(
                session,
                runtime=runtime,
                evidence=registration.runtime_configuration,
            )

    async def configuration_evidence_for_runner_heartbeat(
        self,
        *,
        runtime_id: str,
    ) -> RuntimeConfigurationEvidence | None:
        """Return pending exact evidence after Provider acknowledgement."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_id(session, runtime_id)
            if runtime is None or runtime.runtime_provider_resource_id is None:
                return None
            revision_id = runtime.desired_runtime_configuration_revision_id
            if (
                revision_id is None
                or revision_id == runtime.applied_runtime_configuration_revision_id
            ):
                return None
            revision = await self.profile_repository.get_configuration_revision(
                session,
                revision_id=revision_id,
            )
            if revision is None:
                return None
            evidence = RuntimeConfigurationEvidence(
                revision_id=revision.id,
                digest=revision.digest,
                desired_generation=revision.target_desired_generation,
            )
            if not (
                await self.profile_repository.configuration_evidence_matches_current(
                    session,
                    runtime_id=runtime.id,
                    provider_id=runtime.runtime_provider_resource_id,
                    evidence=evidence,
                )
            ):
                return None
            if (
                revision.provider_acknowledged_at is None
                or revision.provider_reported_digest != revision.digest
                or revision.runner_reported_digest == revision.digest
            ):
                return None
            return evidence

    async def record_runner_state(self, report: SharedRunnerStateReport) -> None:
        """Persist one Runner report and validate its workspace path."""
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
                    expected_desired_generation=(
                        report.runtime_configuration.desired_generation
                    ),
                    workspace_path=None,
                    failure=None,
                )
                return
            if (
                report.runtime_configuration.desired_generation
                != runtime.desired_generation
            ):
                return
            try:
                workspace_path = _normalize_runner_workspace_path(report.workspace_path)
                failure = None
            except ValueError as exc:
                workspace_path = None
                failure = AgentRuntimeFailurePatch(
                    generation=runtime.desired_generation,
                    code=(
                        "RUNNER_WORKSPACE_PATH_MISSING"
                        if not report.workspace_path.strip()
                        else "RUNNER_WORKSPACE_PATH_INVALID"
                    ),
                    message=str(exc),
                )
            runner_state = _runner_state(report)
            if failure is None:
                failure = _runner_state_failure(
                    state=report.runner_state,
                    desired_generation=runtime.desired_generation,
                )
            configuration_failure = await self._record_runner_configuration_evidence(
                session,
                runtime=runtime,
                report=report,
            )
            if failure is None and configuration_failure is not None:
                failure = configuration_failure
            if failure is not None:
                runner_state = RuntimeRunnerState.FAILED

            persisted = await self.runtime_repository.record_runner_state(
                session,
                report.runtime_id,
                runner_state,
                report.runner_generation,
                expected_desired_generation=(
                    report.runtime_configuration.desired_generation
                ),
                workspace_path=workspace_path,
                failure=failure,
            )
            if (
                persisted is not None
                and failure is None
                and _runner_report_clears_failure(runtime.failure_code)
            ):
                await self.runtime_repository.clear_current_generation_failure(
                    session,
                    report.runtime_id,
                )

    async def _record_runner_configuration_evidence(
        self,
        session: AsyncSession,
        *,
        runtime: AgentRuntime,
        report: SharedRunnerStateReport,
    ) -> AgentRuntimeFailurePatch | None:
        provider_id = runtime.runtime_provider_resource_id
        if provider_id is None:
            return _configuration_failure(
                runtime.desired_generation,
                "RUNTIME_CONFIGURATION_PROVIDER_BINDING_MISSING",
            )
        recorded = await self.profile_repository.record_runner_configuration_evidence(
            session,
            runtime_id=report.runtime_id,
            provider_id=provider_id,
            evidence=report.runtime_configuration,
            observed_at=report.reported_at,
        )
        if recorded is None:
            if await self._runner_evidence_matches_applied(
                session,
                runtime=runtime,
                evidence=report.runtime_configuration,
            ):
                return None
            return _configuration_failure(
                runtime.desired_generation,
                "RUNTIME_CONFIGURATION_RUNNER_EVIDENCE_MISMATCH",
            )
        return None

    async def _runner_evidence_matches_applied(
        self,
        session: AsyncSession,
        *,
        runtime: AgentRuntime,
        evidence: RuntimeConfigurationEvidence,
    ) -> bool:
        provider_id = runtime.runtime_provider_resource_id
        applied_revision_id = runtime.applied_runtime_configuration_revision_id
        if provider_id is None or applied_revision_id is None:
            return False
        return await self.profile_repository.configuration_evidence_matches_applied(
            session,
            runtime_id=runtime.id,
            provider_id=provider_id,
            evidence=evidence,
        )


def _normalize_runner_workspace_path(workspace_path: str) -> str:
    """Normalize one Runner-reported Agent Workspace path."""
    if not workspace_path.strip():
        raise ValueError("Runtime Runner did not report an Agent Workspace path.")
    normalized = PurePosixPath(posixpath.normpath(workspace_path.strip()))
    if not normalized.is_absolute():
        raise ValueError("Runtime Runner Agent Workspace path must be absolute.")
    return normalized.as_posix()


def _configuration_failure(
    desired_generation: int,
    code: str,
) -> AgentRuntimeFailurePatch:
    return AgentRuntimeFailurePatch(
        generation=desired_generation,
        code=code,
        message="Runtime configuration evidence is missing or does not match.",
    )


def _provider_report_clears_failure(
    *,
    report: SharedRuntimeProviderReport,
    desired_generation: int,
    failure_code: str | None,
) -> bool:
    return (
        report.observed_state == SharedProviderObservedState.RUNNING
        and report.observed_desired_generation >= desired_generation
        and (
            failure_code is None
            or failure_code == "START_TIMEOUT"
            or failure_code.startswith("PROVIDER_")
            or failure_code.startswith("RUNTIME_CONFIGURATION_PROVIDER_")
        )
    )


def _runner_report_clears_failure(failure_code: str | None) -> bool:
    return (
        failure_code is None
        or failure_code.startswith("RUNNER_")
        or failure_code.startswith("RUNTIME_CONFIGURATION_RUNNER_")
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
