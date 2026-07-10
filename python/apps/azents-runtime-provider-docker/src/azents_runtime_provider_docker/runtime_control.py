"""Adapter between shared Runtime Control contracts and Docker lifecycle."""

from collections.abc import Sequence

from azents_runtime_control.provider import (
    RuntimeDesiredState as ControlRuntimeDesiredState,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleCommand as ControlRuntimeLifecycleCommand,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as ControlRuntimeLifecycleCommandType,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleResult as ControlRuntimeLifecycleResult,
)
from azents_runtime_control.provider import (
    RuntimeProviderLifecycle,
)
from azents_runtime_control.provider import (
    RuntimeProviderObservedState as ControlRuntimeProviderObservedState,
)
from azents_runtime_control.provider import (
    RuntimeProviderReport as ControlRuntimeProviderReport,
)

from azents_runtime_provider_docker.models import (
    RuntimeContainerAuth,
    RuntimeDesiredState,
    RuntimeIdentity,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeLifecycleResult,
    RuntimeProviderReport,
)
from azents_runtime_provider_docker.provider import DockerRuntimeProvider


class DockerRuntimeControlAdapter(RuntimeProviderLifecycle):
    """Expose Docker Provider lifecycle through the shared Control contract."""

    def __init__(self, provider: DockerRuntimeProvider) -> None:
        """Initialize the adapter."""
        self._provider = provider

    async def start(
        self, command: ControlRuntimeLifecycleCommand
    ) -> ControlRuntimeLifecycleResult:
        """Start a Runtime."""
        return _result(await self._provider.start(_command(command)))

    async def stop(
        self, command: ControlRuntimeLifecycleCommand
    ) -> ControlRuntimeLifecycleResult:
        """Stop a Runtime."""
        return _result(await self._provider.stop(_command(command)))

    async def restart(
        self, command: ControlRuntimeLifecycleCommand
    ) -> ControlRuntimeLifecycleResult:
        """Restart a Runtime."""
        return _result(await self._provider.restart(_command(command)))

    async def reset(
        self, command: ControlRuntimeLifecycleCommand
    ) -> ControlRuntimeLifecycleResult:
        """Reset a Runtime."""
        return _result(await self._provider.reset(_command(command)))

    async def observe(
        self, command: ControlRuntimeLifecycleCommand
    ) -> ControlRuntimeProviderReport:
        """Observe a Runtime."""
        return _report(await self._provider.observe(_command(command)))

    async def observe_known_runtimes(
        self,
    ) -> Sequence[ControlRuntimeProviderReport]:
        """Observe Provider-owned Runtimes after process restart."""
        return tuple(
            _report(report) for report in await self._provider.observe_known_runtimes()
        )


def _command(command: ControlRuntimeLifecycleCommand) -> RuntimeLifecycleCommand:
    return RuntimeLifecycleCommand(
        command_type=RuntimeLifecycleCommandType(command.command_type.value),
        identity=RuntimeIdentity(
            runtime_id=command.identity.runtime_id,
            agent_id=command.identity.agent_id,
            workspace_id=command.identity.workspace_id,
        ),
        desired_generation=command.desired_generation,
        provider_generation=command.provider_generation,
        runner_image=command.runner_image,
        auth=RuntimeContainerAuth(
            control_endpoint=command.auth.control_endpoint,
            runner_auth_token=command.auth.runner_auth_token,
            control_token=command.auth.control_token,
        ),
        reset_final_desired_state=_desired_state(command.reset_final_desired_state),
    )


def _desired_state(
    state: ControlRuntimeDesiredState | None,
) -> RuntimeDesiredState | None:
    if state is None:
        return None
    return RuntimeDesiredState(state.value)


def _result(result: RuntimeLifecycleResult) -> ControlRuntimeLifecycleResult:
    return ControlRuntimeLifecycleResult(
        command_type=ControlRuntimeLifecycleCommandType(result.command_type.value),
        report=_report(result.report),
    )


def _report(report: RuntimeProviderReport) -> ControlRuntimeProviderReport:
    return ControlRuntimeProviderReport(
        runtime_id=report.runtime_id,
        provider_id=report.provider_id,
        provider_generation=report.provider_generation,
        observed_state=ControlRuntimeProviderObservedState(report.observed_state.value),
        observed_desired_generation=report.observed_desired_generation,
        provider_runtime_id=report.provider_runtime_id,
        workspace_path=report.workspace_path,
        reason=report.reason,
        diagnostic=dict(report.diagnostic),
        reported_at=report.reported_at,
    )
