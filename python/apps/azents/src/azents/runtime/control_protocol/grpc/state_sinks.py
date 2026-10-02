"""Session-free report adapters for the Control gRPC bridges."""

import dataclasses
from typing import Annotated

from azents_runtime_control.provider import RuntimeProviderReport
from azents_runtime_control.runner import RunnerStateReport
from azents_runtime_control.runner import RuntimeRunnerState as SharedRunnerState
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from fastapi import Depends

from azents.core.enums import RuntimeProviderObservedState, RuntimeRunnerState
from azents.repos.runtime_report_data import ProviderReportInput, RunnerReportInput
from azents.repos.runtime_report_operations import RuntimeReportOperationRepository
from azents.runtime.control_protocol.data import RuntimeRunnerRegistration


@dataclasses.dataclass
class RuntimeProviderReportRepositorySink:
    """Translate decoded Provider facts into completed database operations."""

    repository: Annotated[
        RuntimeReportOperationRepository, Depends(RuntimeReportOperationRepository)
    ]

    async def record_provider_report(
        self,
        report: RuntimeProviderReport,
        *,
        configuration_acknowledgement_allowed: bool,
    ) -> None:
        """Complete persistence before the bridge publishes or handles completion."""
        await self.repository.record_provider_report(
            _provider_report_input(report),
            configuration_acknowledgement_allowed=configuration_acknowledgement_allowed,
        )

    async def complete_restart_handoff(self, report: RuntimeProviderReport) -> bool:
        """Keep correlated Restart rearm separate from the preceding report."""
        return await self.repository.complete_restart_handoff(
            _provider_report_input(report)
        )


@dataclasses.dataclass
class RuntimeRunnerStateRepositorySink:
    """Translate decoded Runner facts into completed database operations."""

    repository: Annotated[
        RuntimeReportOperationRepository, Depends(RuntimeReportOperationRepository)
    ]

    async def validate_runner_registration(
        self, registration: RuntimeRunnerRegistration
    ) -> bool:
        """Complete registration evidence reads before gRPC accepts the Runner."""
        return await self.repository.validate_runner_registration(
            runtime_id=registration.runtime_id,
            evidence=registration.runtime_configuration,
        )

    async def configuration_evidence_for_runner_heartbeat(
        self, *, runtime_id: str
    ) -> RuntimeConfigurationEvidence | None:
        """Complete exact evidence reads before the bridge acknowledges heartbeat."""
        return await self.repository.configuration_evidence_for_runner_heartbeat(
            runtime_id=runtime_id
        )

    async def record_runner_state(self, report: RunnerStateReport) -> None:
        """Complete state persistence before external generation projections."""
        await self.repository.record_runner_state(_runner_report_input(report))


def _provider_report_input(report: RuntimeProviderReport) -> ProviderReportInput:
    """Detach persistence facts from Provider transport/correlation machinery."""
    return ProviderReportInput(
        runtime_id=report.runtime_id,
        provider_id=report.provider_id,
        provider_generation=report.provider_generation,
        observed_state=RuntimeProviderObservedState(report.observed_state.value),
        observed_desired_generation=report.observed_desired_generation,
        provider_runtime_id=report.provider_runtime_id,
        terminal_delete_acknowledged=report.terminal_delete_acknowledged,
        runtime_configuration=report.runtime_configuration,
        reported_at=report.reported_at,
    )


def _runner_report_input(report: RunnerStateReport) -> RunnerReportInput:
    """Map BUSY and stream close without adding protocol or path authority."""
    state = report.runner_state
    supported = state in {
        SharedRunnerState.UNKNOWN,
        SharedRunnerState.STARTING,
        SharedRunnerState.READY,
        SharedRunnerState.BUSY,
        SharedRunnerState.DEGRADED,
        SharedRunnerState.FAILED,
    }
    stream_closed = report.diagnostic.get("reason") == "runner_stream_closed"
    if stream_closed:
        runner_state = RuntimeRunnerState.DISCONNECTED
    elif state is SharedRunnerState.BUSY:
        runner_state = RuntimeRunnerState.READY
    elif supported:
        runner_state = RuntimeRunnerState(state.value)
    else:
        runner_state = RuntimeRunnerState.FAILED
    return RunnerReportInput(
        runtime_id=report.runtime_id,
        runner_generation=report.runner_generation,
        runner_state=runner_state,
        runner_stream_closed=stream_closed,
        unsupported_runner_state=None if supported else state.value,
        workspace_path=report.workspace_path,
        runtime_configuration=report.runtime_configuration,
        reported_at=report.reported_at,
    )
