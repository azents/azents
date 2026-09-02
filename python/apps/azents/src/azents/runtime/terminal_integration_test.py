"""Runtime Terminal invalidation adapter tests."""

from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.runner_terminal import (
    RunnerTerminalIdentity,
    RunnerTerminalStreamRegistration,
    RunnerTerminalTerminationReason,
)

from azents.runtime.terminal_coordination.data import (
    RuntimeTerminalAdmission,
    RuntimeTerminalLifecycle,
    RuntimeTerminalRecord,
)
from azents.runtime.terminal_coordination.memory import (
    InMemoryRuntimeTerminalCoordinationStore,
)
from azents.runtime.terminal_integration import (
    CompositeRuntimeRunnerGenerationObserver,
    CoordinatedRuntimeTerminalInvalidationPublisher,
    RuntimeTerminalPolicyInvalidationPublisher,
    RuntimeTerminalRunnerGenerationObserver,
)
from azents.services.terminal_policy.invalidation import (
    TerminalPolicySourceInvalidation,
    TerminalPolicySourceScope,
)

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


class _Dispatcher:
    def __init__(self) -> None:
        self.terminated: list[tuple[str, RunnerTerminalTerminationReason]] = []

    async def open_terminal(
        self,
        record: RuntimeTerminalRecord,
        *,
        columns: int,
        rows: int,
        requested_at: datetime,
    ) -> None:
        del record, columns, rows, requested_at

    async def terminate_terminal(
        self,
        record: RuntimeTerminalRecord,
        *,
        reason: RunnerTerminalTerminationReason,
        requested_at: datetime,
    ) -> None:
        assert requested_at == _NOW
        self.terminated.append((record.admission.terminal_id, reason))


@pytest.mark.asyncio
async def test_runner_replacement_invalidates_runtime_terminals() -> None:
    store = InMemoryRuntimeTerminalCoordinationStore()
    await store.admit_or_get(_admission(), admitted_at=_NOW)
    await store.register_runner_stream(
        RunnerTerminalStreamRegistration(
            identity=RunnerTerminalIdentity(
                terminal_id="terminal-1",
                runtime_id="runtime-1",
                runner_generation=1,
            ),
            stream_generation=1,
            stream_nonce="nonce-1",
            last_control_acknowledged_output_sequence=0,
            highest_completely_applied_input_sequence=0,
            partial_input_sequence=None,
            partial_input_bytes_written=None,
        ),
        desired_generation=1,
        connected_at=_NOW,
        lease_seconds=45,
    )
    observer = RuntimeTerminalRunnerGenerationObserver(
        store=store,
        clock=lambda: _NOW,
    )

    await observer.on_runner_replaced(
        runtime_id="runtime-1",
        previous_generation=2,
        generation=3,
    )

    record = await store.get_terminal("terminal-1", current_time=_NOW)
    assert record is not None
    assert record.lifecycle is RuntimeTerminalLifecycle.EXITED
    assert record.termination_reason is RunnerTerminalTerminationReason.RUNNER_REPLACED


@pytest.mark.asyncio
async def test_policy_source_update_invalidates_indexed_terminals() -> None:
    store = InMemoryRuntimeTerminalCoordinationStore()
    await store.admit_or_get(_admission(), admitted_at=_NOW)
    publisher = RuntimeTerminalPolicyInvalidationPublisher(
        store=store,
        dispatcher=_Dispatcher(),
        clock=lambda: _NOW,
    )

    await publisher.publish_terminal_policy_invalidation(
        TerminalPolicySourceInvalidation(
            scope=TerminalPolicySourceScope.AGENT,
            source_id="agent-1",
            source_version="2",
        )
    )

    record = await store.get_terminal("terminal-1", current_time=_NOW)
    assert record is not None
    assert record.lifecycle is RuntimeTerminalLifecycle.EXITED
    assert record.termination_reason is RunnerTerminalTerminationReason.POLICY_REVOKED


@pytest.mark.asyncio
async def test_runtime_lifecycle_change_invalidates_runtime_terminals() -> None:
    """A committed Runtime lifecycle change terminates indexed Terminals."""
    store = InMemoryRuntimeTerminalCoordinationStore()
    await store.admit_or_get(_admission(), admitted_at=_NOW)
    publisher = CoordinatedRuntimeTerminalInvalidationPublisher(
        store=store,
        dispatcher=_Dispatcher(),
        clock=lambda: _NOW,
    )

    await publisher.publish_runtime_terminal_invalidation("runtime-1")

    record = await store.get_terminal("terminal-1", current_time=_NOW)
    assert record is not None
    assert record.lifecycle is RuntimeTerminalLifecycle.EXITED
    assert (
        record.termination_reason is RunnerTerminalTerminationReason.RUNTIME_INVALIDATED
    )


@pytest.mark.asyncio
async def test_authentication_session_revocation_invalidates_exact_terminals() -> None:
    store = InMemoryRuntimeTerminalCoordinationStore()
    await store.admit_or_get(_admission(), admitted_at=_NOW)
    dispatcher = _Dispatcher()
    publisher = CoordinatedRuntimeTerminalInvalidationPublisher(
        store=store,
        dispatcher=dispatcher,
        clock=lambda: _NOW,
    )

    await publisher.publish_authentication_session_terminal_invalidation(
        "auth-session-1"
    )

    record = await store.get_terminal("terminal-1", current_time=_NOW)
    assert record is not None
    assert record.lifecycle is RuntimeTerminalLifecycle.EXITED
    assert record.termination_reason is RunnerTerminalTerminationReason.ACCESS_REVOKED
    assert dispatcher.terminated == [
        ("terminal-1", RunnerTerminalTerminationReason.ACCESS_REVOKED)
    ]


@pytest.mark.asyncio
async def test_composite_runner_observer_notifies_after_peer_failure() -> None:
    calls: list[str] = []

    class FailingObserver:
        async def on_runner_replaced(
            self,
            *,
            runtime_id: str,
            previous_generation: int,
            generation: int,
        ) -> None:
            del runtime_id, previous_generation, generation
            calls.append("failing")
            raise RuntimeError("failed")

        async def on_runner_revoked(
            self,
            *,
            runtime_id: str,
            generation: int,
        ) -> None:
            del runtime_id, generation
            raise RuntimeError("failed")

    class RecordingObserver:
        async def on_runner_replaced(
            self,
            *,
            runtime_id: str,
            previous_generation: int,
            generation: int,
        ) -> None:
            del runtime_id, previous_generation, generation
            calls.append("recording")

        async def on_runner_revoked(
            self,
            *,
            runtime_id: str,
            generation: int,
        ) -> None:
            del runtime_id, generation
            calls.append("revoked")

    observer = CompositeRuntimeRunnerGenerationObserver(
        FailingObserver(),
        RecordingObserver(),
    )

    await observer.on_runner_replaced(
        runtime_id="runtime-1",
        previous_generation=1,
        generation=2,
    )

    assert calls == ["failing", "recording"]


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
        desired_generation=1,
        runner_generation=1,
        working_directory="/workspace/session",
        stream_nonce="nonce-1",
        created_at=_NOW,
        idle_deadline_at=_NOW + timedelta(minutes=30),
        maximum_deadline_at=_NOW + timedelta(hours=8),
        data_stream_grace_deadline_at=_NOW + timedelta(minutes=2),
        metadata_ttl_seconds=9 * 60 * 60,
    )
