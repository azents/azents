"""Provider run loop contract tests."""

import dataclasses
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import pytest

from azents_runtime_control.provider import (
    ProviderCommandCompletion,
    ProviderCommandEnvelope,
    ProviderConnectionRejected,
    ProviderControlClient,
    ProviderRegistration,
    ProviderRegistrationAccepted,
    ProviderRunLoop,
    RuntimeContainerAuth,
    RuntimeDesiredState,
    RuntimeIdentity,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeLifecycleResult,
    RuntimeProviderLifecycle,
    RuntimeProviderObservedState,
    RuntimeProviderReport,
)


class FakeControlClient(ProviderControlClient):
    """In-memory Control client for run loop tests."""

    def __init__(self) -> None:
        self.registrations: list[ProviderRegistration] = []
        self.heartbeats: list[tuple[str, int]] = []
        self.reports: list[RuntimeProviderReport] = []
        self.commands: list[ProviderCommandEnvelope] = []
        self.completions: list[ProviderCommandCompletion] = []
        self.heartbeat_ok = True

    async def register_provider(
        self,
        registration: ProviderRegistration,
        *,
        connection_id: str,
        registered_at: datetime,
    ) -> ProviderRegistrationAccepted:
        """Register a fake Provider connection."""
        self.registrations.append(registration)
        return ProviderRegistrationAccepted(
            provider_id=registration.provider_id,
            connection_id=connection_id,
            generation=11,
            heartbeat_interval_seconds=20,
        )

    async def heartbeat_provider(
        self,
        *,
        provider_id: str,
        generation: int,
        heartbeat_at: datetime,
    ) -> bool:
        """Record a heartbeat."""
        self.heartbeats.append((provider_id, generation))
        return self.heartbeat_ok

    async def report_provider_state(self, report: RuntimeProviderReport) -> None:
        """Record Provider observed state."""
        self.reports.append(report)

    async def claim_next_provider_command(
        self,
        *,
        provider_id: str,
        generation: int,
        consumer_id: str,
        block_ms: int,
    ) -> ProviderCommandEnvelope | None:
        """Pop the next queued command."""
        if not self.commands:
            return None
        return self.commands.pop(0)

    async def complete_provider_command(
        self,
        completion: ProviderCommandCompletion,
    ) -> None:
        """Record command completion."""
        self.completions.append(completion)


@dataclasses.dataclass
class FakeLifecycle(RuntimeProviderLifecycle):
    """Lifecycle fake that records dispatched commands."""

    known_reports: Sequence[RuntimeProviderReport] = ()
    fail_with: Exception | None = None
    fail_on_observe_known: Exception | None = None
    commands: list[RuntimeLifecycleCommand] = dataclasses.field(default_factory=list)

    async def start(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Start a Runtime."""
        return await self._result(command)

    async def stop(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Stop a Runtime."""
        return await self._result(command)

    async def restart(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Restart a Runtime."""
        return await self._result(command)

    async def reset(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Reset a Runtime."""
        return await self._result(command)

    async def observe(self, command: RuntimeLifecycleCommand) -> RuntimeProviderReport:
        """Observe a Runtime."""
        result = await self._result(command)
        return result.report

    async def observe_known_runtimes(self) -> Sequence[RuntimeProviderReport]:
        """Return known fake Runtime reports."""
        if self.fail_on_observe_known is not None:
            raise self.fail_on_observe_known
        return self.known_reports

    async def _result(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        if self.fail_with is not None:
            raise self.fail_with
        self.commands.append(command)
        return RuntimeLifecycleResult(
            command_type=command.command_type,
            report=_report(command),
        )


@pytest.mark.asyncio
async def test_start_registers_heartbeats_and_reports_known_runtimes() -> None:
    client = FakeControlClient()
    known = dataclasses.replace(
        _report(_command(RuntimeLifecycleCommandType.OBSERVE)),
        provider_generation=7,
    )
    lifecycle = FakeLifecycle(known_reports=(known,))
    loop = _loop(client, lifecycle)

    accepted = await loop.start()

    assert accepted.generation == 11
    assert client.registrations[0].provider_id == "provider-1"
    assert client.reports == [dataclasses.replace(known, provider_generation=11)]
    assert client.heartbeats == [("provider-1", 11)]


@pytest.mark.asyncio
async def test_start_heartbeats_before_observing_known_runtimes() -> None:
    """Provider registration TTL is refreshed before backend resynchronization."""
    client = FakeControlClient()
    lifecycle = FakeLifecycle(fail_on_observe_known=RuntimeError("backend scan failed"))
    loop = _loop(client, lifecycle)

    with pytest.raises(RuntimeError, match="backend scan failed"):
        await loop.start()

    assert client.heartbeats == [("provider-1", 11)]


@pytest.mark.asyncio
async def test_report_provider_state_uses_current_connection_generation() -> None:
    """Backend resource labels cannot fence reports after Provider reconnect."""
    client = FakeControlClient()
    loop = _loop(client, FakeLifecycle())
    await loop.start()
    stale_report = dataclasses.replace(
        _report(_command(RuntimeLifecycleCommandType.OBSERVE)),
        provider_generation=7,
    )

    current_report = await loop.report_provider_state(stale_report)

    assert current_report.provider_generation == 11
    assert client.reports == [current_report]


@pytest.mark.asyncio
async def test_process_next_command_dispatches_and_completes_success() -> None:
    client = FakeControlClient()
    lifecycle = FakeLifecycle()
    command = dataclasses.replace(
        _command(RuntimeLifecycleCommandType.START),
        provider_generation=7,
    )
    client.commands.append(ProviderCommandEnvelope(request_id="req-1", command=command))
    loop = _loop(client, lifecycle)
    await loop.start()

    completion = await loop.process_next_command(block_ms=0)

    assert completion is not None
    assert completion.success
    assert completion.report is not None
    assert completion.report.provider_generation == 11
    assert completion.report.workspace_path == "/workspace/agent"
    assert lifecycle.commands == [command]
    assert client.completions == [completion]
    assert client.reports[-1].observed_state is RuntimeProviderObservedState.RUNNING


@pytest.mark.asyncio
async def test_process_next_command_completes_failures_explicitly() -> None:
    client = FakeControlClient()
    lifecycle = FakeLifecycle(fail_with=ValueError("workspace path unavailable"))
    client.commands.append(
        ProviderCommandEnvelope(
            request_id="req-1",
            command=_command(RuntimeLifecycleCommandType.START),
        )
    )
    loop = _loop(client, lifecycle)
    await loop.start()

    completion = await loop.process_next_command(block_ms=0)

    assert completion is not None
    assert not completion.success
    assert completion.report is None
    assert completion.error_code == "ValueError"
    assert completion.error_message == "workspace path unavailable"
    assert client.completions == [completion]


@pytest.mark.asyncio
async def test_process_next_command_expires_stale_deadline_without_dispatch() -> None:
    client = FakeControlClient()
    lifecycle = FakeLifecycle()
    command = _command(RuntimeLifecycleCommandType.START)
    client.commands.append(
        ProviderCommandEnvelope(
            request_id="req-1",
            command=command,
            deadline_at=datetime(2026, 5, 24, tzinfo=UTC),
        )
    )
    loop = _loop(client, lifecycle)
    await loop.start()

    completion = await loop.process_next_command(block_ms=0)

    assert completion is not None
    assert not completion.success
    assert completion.error_code == "ProviderCommandExpired"
    assert lifecycle.commands == []
    assert client.completions == [completion]


@pytest.mark.asyncio
async def test_heartbeat_rejection_is_not_silently_recovered() -> None:
    client = FakeControlClient()
    client.heartbeat_ok = False
    loop = _loop(client, FakeLifecycle())

    with pytest.raises(ProviderConnectionRejected):
        await loop.start()


def _loop(
    client: FakeControlClient,
    lifecycle: RuntimeProviderLifecycle,
) -> ProviderRunLoop:
    return ProviderRunLoop(
        client=client,
        lifecycle=lifecycle,
        registration=ProviderRegistration(
            provider_id="provider-1",
            provider_type="docker",
            scope="system",
            workspace_id=None,
            protocol_version="agent-runtime-provider.v1",
            capabilities=("lifecycle", "observe"),
            config_schema_version="v1",
            metadata={"workspace_path_source": "provider"},
            auth_credential_id="credential-1",
        ),
        connection_id="connection-1",
        consumer_id="consumer-1",
        clock=lambda: datetime(2026, 5, 25, tzinfo=UTC),
        monotonic=lambda: 100.0,
    )


def _command(command_type: RuntimeLifecycleCommandType) -> RuntimeLifecycleCommand:
    return RuntimeLifecycleCommand(
        command_type=command_type,
        identity=RuntimeIdentity(
            runtime_id="runtime-1",
            agent_id="agent-1",
            workspace_id="workspace-1",
        ),
        desired_generation=3,
        provider_generation=11,
        runner_image="runner:latest",
        auth=RuntimeContainerAuth(
            control_endpoint="runtime-control:8020",
            runner_auth_token="runner-token",
            control_token="control-token",
        ),
        reset_final_desired_state=RuntimeDesiredState.RUNNING,
    )


def _report(command: RuntimeLifecycleCommand) -> RuntimeProviderReport:
    diagnostic: Mapping[str, str] = {}
    return RuntimeProviderReport(
        runtime_id=command.identity.runtime_id,
        provider_id="provider-1",
        provider_generation=command.provider_generation,
        observed_state=RuntimeProviderObservedState.RUNNING,
        observed_desired_generation=command.desired_generation,
        provider_runtime_id="runtime-provider-id",
        workspace_path="/workspace/agent",
        reason=f"{command.command_type.value}_ok",
        diagnostic=diagnostic,
        reported_at=datetime(2026, 5, 25, tzinfo=UTC),
    )
