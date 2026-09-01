"""Coordination-backed Runtime Runner Terminal broker tests."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.runner_terminal import (
    RunnerTerminalExit,
    RunnerTerminalIdentity,
    RunnerTerminalInputAcknowledgement,
    RunnerTerminalInputFrame,
    RunnerTerminalOutputAcknowledgement,
    RunnerTerminalOutputFrame,
    RunnerTerminalStreamRegistration,
    RunnerTerminalTerminate,
    RunnerTerminalTerminationReason,
)

from azents.runtime.control_protocol.grpc.runner_terminal_broker import (
    _TERMINAL_OUTPUT_RATE_BYTES_PER_SECOND,
    CoordinatedRuntimeRunnerTerminalBroker,
    _OutputRateLimiter,
)
from azents.runtime.control_protocol.grpc.runner_terminal_server import (
    RuntimeRunnerTerminalAdmissionError,
    RuntimeRunnerTerminalAuthority,
)
from azents.runtime.terminal_coordination.data import (
    RuntimeTerminalAdmission,
    RuntimeTerminalInputBatch,
    RuntimeTerminalLifecycle,
    RuntimeTerminalMutationResult,
    RuntimeTerminalMutationStatus,
    RuntimeTerminalRecord,
)
from azents.runtime.terminal_coordination.memory import (
    InMemoryRuntimeTerminalCoordinationStore,
)

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


class _TerminatingReadGuardStore(InMemoryRuntimeTerminalCoordinationStore):
    def __init__(self) -> None:
        super().__init__()
        self.terminating = False
        self.waiting_after_termination = asyncio.Event()

    async def read_inputs(
        self,
        terminal_id: str,
        *,
        runner_stream_generation: int,
        after_sequence: int,
        maximum_bytes: int,
        current_time: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalInputBatch]:
        if self.terminating:
            raise AssertionError("terminating stream must not read more input")
        return await super().read_inputs(
            terminal_id,
            runner_stream_generation=runner_stream_generation,
            after_sequence=after_sequence,
            maximum_bytes=maximum_bytes,
            current_time=current_time,
        )

    async def wait_for_change(
        self,
        terminal_id: str,
        *,
        after_revision: int,
        timeout_seconds: float,
    ) -> RuntimeTerminalRecord | None:
        if self.terminating:
            self.waiting_after_termination.set()
        return await super().wait_for_change(
            terminal_id,
            after_revision=after_revision,
            timeout_seconds=timeout_seconds,
        )


@pytest.mark.asyncio
async def test_broker_bridges_coordinated_input_output_and_detach() -> None:
    store = InMemoryRuntimeTerminalCoordinationStore()
    admitted = await store.admit_or_get(_admission(), admitted_at=_NOW)
    assert admitted.status is RuntimeTerminalMutationStatus.APPLIED
    attachment = await store.attach_browser(
        "terminal-1",
        user_id="user-1",
        attached_at=_NOW,
        lease_seconds=45,
    )
    assert attachment.value is not None
    await store.enqueue_input(
        "terminal-1",
        attachment_generation=attachment.value.generation,
        sequence=1,
        data=b"pwd\n",
        accepted_at=_NOW,
    )
    broker = CoordinatedRuntimeRunnerTerminalBroker(
        store=store,
        clock=lambda: _NOW,
        monotonic_clock=lambda: 0.0,
    )
    stream = await broker.connect(
        _registration(),
        authority=_authority(),
        connected_at=_NOW,
    )
    controls = stream.control_frames()

    input_frame = await anext(controls)
    assert input_frame == RunnerTerminalInputFrame(sequence=1, data=b"pwd\n")

    await stream.receive(RunnerTerminalInputAcknowledgement(sequence=1))
    await stream.receive(RunnerTerminalOutputFrame(sequence=1, data=b"output"))
    output_ack = await anext(controls)

    assert output_ack == RunnerTerminalOutputAcknowledgement(sequence=1)
    record = await store.get_terminal("terminal-1", current_time=_NOW)
    assert record is not None
    assert record.pending_inputs == ()
    assert record.highest_input_acknowledged_sequence == 1
    assert record.highest_output_sequence == 1

    await stream.close()
    detached = await store.get_terminal("terminal-1", current_time=_NOW)
    assert detached is not None
    assert detached.runner_stream is None
    assert detached.runner_stream_grace_expires_at == _NOW + timedelta(minutes=2)


@pytest.mark.asyncio
async def test_terminating_stream_waits_for_runner_exit_without_reading_input() -> None:
    store = _TerminatingReadGuardStore()
    await store.admit_or_get(_admission(), admitted_at=_NOW)
    broker = CoordinatedRuntimeRunnerTerminalBroker(
        store=store,
        clock=lambda: _NOW,
        monotonic_clock=lambda: 0.0,
    )
    stream = await broker.connect(
        _registration(),
        authority=_authority(),
        connected_at=_NOW,
    )
    controls = stream.control_frames()
    terminated = await store.request_termination(
        "terminal-1",
        reason=RunnerTerminalTerminationReason.CALLER,
        requested_at=_NOW,
    )
    assert terminated.status is RuntimeTerminalMutationStatus.APPLIED
    store.terminating = True

    control = await anext(controls)
    assert control == RunnerTerminalTerminate(
        reason=RunnerTerminalTerminationReason.CALLER
    )
    waiting = asyncio.ensure_future(anext(controls))
    await asyncio.wait_for(store.waiting_after_termination.wait(), timeout=1)

    await stream.receive(
        RunnerTerminalExit(
            reason=RunnerTerminalTerminationReason.CALLER,
            exit_code=None,
        )
    )
    with pytest.raises(StopAsyncIteration):
        await waiting
    final = await store.get_terminal("terminal-1", current_time=_NOW)
    assert final is not None
    assert final.lifecycle is RuntimeTerminalLifecycle.EXITED


@pytest.mark.asyncio
async def test_broker_rejects_stale_runtime_authority() -> None:
    store = InMemoryRuntimeTerminalCoordinationStore()
    await store.admit_or_get(_admission(), admitted_at=_NOW)
    broker = CoordinatedRuntimeRunnerTerminalBroker(
        store=store,
        clock=lambda: _NOW,
        monotonic_clock=lambda: 0.0,
    )

    with pytest.raises(RuntimeRunnerTerminalAdmissionError):
        await broker.connect(
            _registration(runner_generation=4),
            authority=_authority(),
            connected_at=_NOW,
        )

    record = await store.get_terminal("terminal-1", current_time=_NOW)
    assert record is not None
    assert record.lifecycle is RuntimeTerminalLifecycle.OPENING
    assert record.runner_stream is None


@pytest.mark.asyncio
async def test_output_rate_limiter_waits_for_terminal_bucket_refill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Output beyond the per-Terminal burst waits for monotonic token refill."""
    monotonic = 0.0
    delays: list[float] = []

    async def advance(delay: float) -> None:
        nonlocal monotonic
        delays.append(delay)
        monotonic += delay

    monkeypatch.setattr(
        "azents.runtime.control_protocol.grpc.runner_terminal_broker.asyncio.sleep",
        advance,
    )
    limiter = _OutputRateLimiter(lambda: monotonic)
    await limiter.throttle(
        terminal_id="terminal-1",
        runtime_id="runtime-1",
        amount=_TERMINAL_OUTPUT_RATE_BYTES_PER_SECOND,
    )
    await limiter.throttle(
        terminal_id="terminal-1",
        runtime_id="runtime-1",
        amount=1,
    )

    assert delays == [1 / _TERMINAL_OUTPUT_RATE_BYTES_PER_SECOND]


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
        runner_generation=3,
        working_directory="/workspace/session",
        stream_nonce="nonce-1",
        created_at=_NOW,
        idle_deadline_at=_NOW + timedelta(minutes=30),
        maximum_deadline_at=_NOW + timedelta(hours=8),
        data_stream_grace_deadline_at=_NOW + timedelta(minutes=2),
        metadata_ttl_seconds=9 * 60 * 60,
    )


def _registration(*, runner_generation: int = 3) -> RunnerTerminalStreamRegistration:
    return RunnerTerminalStreamRegistration(
        identity=RunnerTerminalIdentity(
            terminal_id="terminal-1",
            runtime_id="runtime-1",
            runner_generation=runner_generation,
        ),
        stream_generation=1,
        stream_nonce="nonce-1",
        last_control_acknowledged_output_sequence=0,
        highest_completely_applied_input_sequence=0,
        partial_input_sequence=None,
        partial_input_bytes_written=None,
    )


def _authority() -> RuntimeRunnerTerminalAuthority:
    return RuntimeRunnerTerminalAuthority(
        credential_id="credential-1",
        runtime_id="runtime-1",
        desired_generation=2,
        runner_generation=3,
    )
