"""Runtime Terminal Control-intent dispatcher tests."""

from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.runner_terminal import RunnerTerminalTerminationReason
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence

from azents.runtime.control_protocol.data import (
    RuntimeProtocolCapabilities,
    RuntimeRunnerRegistration,
)
from azents.runtime.control_protocol.service import RuntimeControlProtocolService
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.terminal_coordination.data import (
    RuntimeTerminalAdmission,
    RuntimeTerminalLifecycle,
    RuntimeTerminalMutationStatus,
)
from azents.runtime.terminal_coordination.memory import (
    InMemoryRuntimeTerminalCoordinationStore,
)
from azents.runtime.terminal_dispatcher import RuntimeTerminalControlDispatcherAdapter

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_dispatcher_routes_typed_open_and_terminate_intents() -> None:
    runtime_coordination = InMemoryRuntimeCoordinationStore()
    control = RuntimeControlProtocolService(
        runtime_coordination,
        request_id_factory=iter(("open-1", "terminate-1")).__next__,
    )
    accepted = await control.register_runner(
        _registration(),
        registered_at=datetime.now(UTC),
    )
    coordination = InMemoryRuntimeTerminalCoordinationStore()
    admitted = await coordination.admit_or_get(_admission(), admitted_at=_NOW)
    assert admitted.value is not None
    dispatcher = RuntimeTerminalControlDispatcherAdapter(
        control_protocol=control,
        terminal_coordination=coordination,
        runtime_coordination=runtime_coordination,
    )

    await dispatcher.open_terminal(
        admitted.value,
        columns=120,
        rows=40,
        requested_at=_NOW,
    )
    opened = await control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=accepted.generation,
        consumer_id="runner-1",
        block_ms=1,
    )

    assert opened is not None
    assert opened.operation_type == "terminal.open.v1"
    assert opened.payload["owner_session_id"] == "session-1"
    assert opened.payload["payload"] == {
        "terminal_id": "terminal-1",
        "working_directory": "/workspace/session",
        "columns": 120,
        "rows": 40,
        "idle_deadline_at": (_NOW + timedelta(minutes=30)).isoformat(),
        "maximum_deadline_at": (_NOW + timedelta(hours=8)).isoformat(),
        "data_stream_grace_deadline_at": (_NOW + timedelta(minutes=2)).isoformat(),
        "stream_nonce": "nonce-1",
        "initial_stream_generation": 1,
    }

    await dispatcher.terminate_terminal(
        admitted.value,
        reason=RunnerTerminalTerminationReason.CALLER,
        requested_at=_NOW,
    )
    terminated = await control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=accepted.generation,
        consumer_id="runner-1",
        block_ms=1,
    )

    assert terminated is not None
    assert terminated.operation_type == "terminal.terminate.v1"
    assert terminated.payload["payload"] == {
        "terminal_id": "terminal-1",
        "reason": "caller",
    }


@pytest.mark.asyncio
async def test_dispatcher_terminates_coordination_when_runner_route_is_missing() -> (
    None
):
    runtime_coordination = InMemoryRuntimeCoordinationStore()
    control = RuntimeControlProtocolService(runtime_coordination)
    coordination = InMemoryRuntimeTerminalCoordinationStore()
    admitted = await coordination.admit_or_get(_admission(), admitted_at=_NOW)
    assert admitted.status is RuntimeTerminalMutationStatus.APPLIED
    assert admitted.value is not None
    dispatcher = RuntimeTerminalControlDispatcherAdapter(
        control_protocol=control,
        terminal_coordination=coordination,
        runtime_coordination=runtime_coordination,
    )

    await dispatcher.open_terminal(
        admitted.value,
        columns=80,
        rows=24,
        requested_at=_NOW,
    )

    record = await coordination.get_terminal("terminal-1", current_time=_NOW)
    assert record is not None
    assert record.lifecycle is RuntimeTerminalLifecycle.TERMINATING
    assert (
        record.termination_reason is RunnerTerminalTerminationReason.RUNTIME_INVALIDATED
    )


def _registration() -> RuntimeRunnerRegistration:
    return RuntimeRunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="2026-07-25",
        capabilities=RuntimeProtocolCapabilities(("file.transfer.v1", "terminal.v1")),
        health="ok",
        workspace_path="/workspace",
        metadata={},
        auth_credential_id="credential-1",
        runtime_configuration=RuntimeConfigurationEvidence(
            configuration_sequence=1,
            digest="d" * 64,
            desired_generation=2,
        ),
        connection_id="connection-1",
        owner_replica_id="control-1",
    )


def _admission() -> RuntimeTerminalAdmission:
    return RuntimeTerminalAdmission(
        terminal_id="terminal-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        authentication_session_id="auth-session-1",
        authentication_session_expires_at=_NOW + timedelta(days=1),
        runtime_id="runtime-1",
        provider_profile_id="provider-profile-1",
        provider_profile_version=1,
        workspace_profile_id="workspace-profile-1",
        workspace_profile_version=1,
        agent_policy_version="2026-09-01T12:00:00+00:00",
        desired_generation=2,
        runner_generation=1,
        working_directory="/workspace/session",
        stream_nonce="nonce-1",
        created_at=_NOW,
        idle_deadline_at=_NOW + timedelta(minutes=30),
        maximum_deadline_at=_NOW + timedelta(hours=8),
        data_stream_grace_deadline_at=_NOW + timedelta(minutes=2),
        metadata_ttl_seconds=9 * 60 * 60,
    )
