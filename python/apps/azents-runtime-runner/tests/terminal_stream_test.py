"""Runner Terminal Control-intent and data-stream integration tests."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from azents_runtime_control.runner_terminal import (
    RunnerTerminalControlFrame,
    RunnerTerminalEventFrame,
    RunnerTerminalExit,
    RunnerTerminalIdentity,
    RunnerTerminalInputAcknowledgement,
    RunnerTerminalInputFrame,
    RunnerTerminalOpenIntent,
    RunnerTerminalStreamAccepted,
    RunnerTerminalStreamRegistration,
    RunnerTerminalTerminateIntent,
    RunnerTerminalTerminationReason,
)

import azents_runtime_runner.terminal_stream as terminal_stream_module
from azents_runtime_runner.terminal import (
    RunnerTerminalRegistry,
    TerminalExit,
    TerminalLimits,
    TerminalSpec,
)
from azents_runtime_runner.terminal_stream import RunnerTerminalStreamManager

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


class _Process:
    def __init__(self, *, terminate_gate: asyncio.Event | None = None) -> None:
        self.returncode: int | None = None
        self.writes: list[tuple[bytes, int]] = []
        self.resizes: list[tuple[int, int]] = []
        self.closed = False
        self.closed_event = asyncio.Event()
        self.exit_event = asyncio.Event()
        self.terminate_gate = terminate_gate
        self.terminate_started = asyncio.Event()

    async def read(
        self,
        maximum_bytes: int,
        *,
        active: Callable[[], bool],
    ) -> bytes:
        del maximum_bytes
        assert active()
        await asyncio.Future()
        raise AssertionError("unreachable")

    async def write(
        self,
        data: bytes,
        *,
        offset: int,
        active: Callable[[], bool],
    ) -> int:
        assert active()
        self.writes.append((data, offset))
        return len(data) - offset

    async def resize(
        self,
        *,
        columns: int,
        rows: int,
        active: Callable[[], bool],
    ) -> None:
        assert active()
        self.resizes.append((columns, rows))

    async def wait(self) -> int:
        await self.exit_event.wait()
        assert self.returncode is not None
        return self.returncode

    async def terminate_session(
        self,
        *,
        terminate_timeout_seconds: float,
        kill_timeout_seconds: float,
    ) -> TerminalExit:
        del terminate_timeout_seconds, kill_timeout_seconds
        self.terminate_started.set()
        if self.terminate_gate is not None:
            await self.terminate_gate.wait()
        if self.returncode is not None:
            return TerminalExit(
                returncode=self.returncode,
                already_exited=True,
                escalated=False,
                timed_out=False,
            )
        self.returncode = -15
        self.exit_event.set()
        return TerminalExit(
            returncode=-15,
            already_exited=False,
            escalated=False,
            timed_out=False,
        )

    async def close(self) -> None:
        self.closed = True
        self.closed_event.set()

    def exit(self, returncode: int) -> None:
        self.returncode = returncode
        self.exit_event.set()


class _Backend:
    def __init__(
        self,
        process: _Process,
        *,
        open_gate: asyncio.Event | None = None,
    ) -> None:
        self.process = process
        self.specs: list[TerminalSpec] = []
        self.open_gate = open_gate
        self.open_started = asyncio.Event()

    async def open(self, spec: TerminalSpec) -> _Process:
        self.specs.append(spec)
        self.open_started.set()
        if self.open_gate is not None:
            await self.open_gate.wait()
        return self.process


class _Client:
    def __init__(self) -> None:
        self.handler: Callable[[RunnerTerminalControlFrame], Awaitable[None]] | None = (
            None
        )
        self.registration: RunnerTerminalStreamRegistration | None = None
        self.sent: list[RunnerTerminalEventFrame] = []
        self.sent_event = asyncio.Event()
        self.started = asyncio.Event()
        self.closed = asyncio.Event()

    def set_control_handler(
        self,
        handler: Callable[[RunnerTerminalControlFrame], Awaitable[None]],
    ) -> None:
        self.handler = handler

    async def start(
        self,
        registration: RunnerTerminalStreamRegistration,
    ) -> RunnerTerminalStreamAccepted:
        self.registration = registration
        self.started.set()
        return RunnerTerminalStreamAccepted(
            stream_generation=registration.stream_generation,
            resume_from_output_sequence=1,
            next_input_sequence=1,
        )

    async def send(self, frame: RunnerTerminalEventFrame) -> None:
        self.sent.append(frame)
        self.sent_event.set()

    async def finish(self, frame: RunnerTerminalEventFrame) -> None:
        self.sent.append(frame)
        self.sent_event.set()

    async def close(self) -> None:
        self.closed.set()

    async def control(self, frame: RunnerTerminalControlFrame) -> None:
        assert self.handler is not None
        await self.handler(frame)


class _HangingClient(_Client):
    async def start(
        self,
        registration: RunnerTerminalStreamRegistration,
    ) -> RunnerTerminalStreamAccepted:
        self.registration = registration
        self.started.set()
        await asyncio.Future()
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_open_intent_allocates_pty_and_bridges_input_ack() -> None:
    process = _Process()
    backend = _Backend(process)
    clients: list[_Client] = []
    client_created = asyncio.Event()

    def client_factory() -> _Client:
        client = _Client()
        clients.append(client)
        client_created.set()
        return client

    manager, registry = _manager(
        backend=backend,
        client_factory=client_factory,
    )

    await manager.handle_open(_open_intent())
    await asyncio.wait_for(client_created.wait(), timeout=1)
    client = clients[0]
    await asyncio.wait_for(client.started.wait(), timeout=1)
    await client.control(RunnerTerminalInputFrame(sequence=1, data=b"pwd\n"))

    assert backend.specs[0].working_directory == Path("/workspace/session")
    assert client.registration is not None
    assert client.registration.identity.runner_generation == 3
    assert client.registration.partial_input_sequence is None
    assert process.writes == [(b"pwd\n", 0)]
    assert client.sent == [RunnerTerminalInputAcknowledgement(sequence=1)]

    await manager.handle_terminate(
        RunnerTerminalTerminateIntent(
            identity=_identity(),
            reason=RunnerTerminalTerminationReason.CALLER,
        )
    )
    await asyncio.wait_for(client.closed.wait(), timeout=1)
    assert await registry.get(terminal_id="terminal-1") is None
    assert process.closed is True


@pytest.mark.asyncio
async def test_open_intent_returns_before_slow_pty_allocation() -> None:
    open_gate = asyncio.Event()
    backend = _Backend(_Process(), open_gate=open_gate)
    client_created = asyncio.Event()

    def client_factory() -> _Client:
        client_created.set()
        return _Client()

    manager, _registry = _manager(
        backend=backend,
        client_factory=client_factory,
    )

    await asyncio.wait_for(manager.handle_open(_open_intent()), timeout=0.1)
    await asyncio.wait_for(backend.open_started.wait(), timeout=1)
    assert client_created.is_set() is False

    open_gate.set()
    await asyncio.wait_for(client_created.wait(), timeout=1)
    await manager.close()


@pytest.mark.asyncio
async def test_open_intent_rejects_stale_runner_generation_before_pty() -> None:
    backend = _Backend(_Process())
    manager, _registry = _manager(
        backend=backend,
        client_factory=_Client,
        accepted_generation=lambda: 4,
    )

    await manager.handle_open(_open_intent())

    assert backend.specs == []


@pytest.mark.asyncio
async def test_runtime_invalidation_detaches_before_cleanup_finishes() -> None:
    terminate_gate = asyncio.Event()
    process = _Process(terminate_gate=terminate_gate)
    backend = _Backend(process)
    clients: list[_Client] = []
    client_created = asyncio.Event()

    def client_factory() -> _Client:
        client = _Client()
        clients.append(client)
        client_created.set()
        return client

    manager, registry = _manager(
        backend=backend,
        client_factory=client_factory,
    )
    await manager.handle_open(_open_intent())
    await asyncio.wait_for(client_created.wait(), timeout=1)
    await asyncio.wait_for(clients[0].started.wait(), timeout=1)

    cleanup = await manager.invalidate_runtime()
    await asyncio.wait_for(process.terminate_started.wait(), timeout=1)

    assert len(cleanup) == 1
    assert cleanup[0].done() is False
    assert await registry.get(terminal_id="terminal-1") is None
    assert clients[0].closed.is_set() is True

    terminate_gate.set()
    await asyncio.gather(*cleanup)
    assert process.closed is True


@pytest.mark.asyncio
async def test_terminate_intent_returns_before_pty_cleanup_finishes() -> None:
    terminate_gate = asyncio.Event()
    process = _Process(terminate_gate=terminate_gate)
    backend = _Backend(process)
    clients: list[_Client] = []
    client_created = asyncio.Event()

    def client_factory() -> _Client:
        client = _Client()
        clients.append(client)
        client_created.set()
        return client

    manager, registry = _manager(
        backend=backend,
        client_factory=client_factory,
    )
    await manager.handle_open(_open_intent())
    await asyncio.wait_for(client_created.wait(), timeout=1)
    await asyncio.wait_for(clients[0].started.wait(), timeout=1)

    await asyncio.wait_for(
        manager.handle_terminate(
            RunnerTerminalTerminateIntent(
                identity=_identity(),
                reason=RunnerTerminalTerminationReason.CALLER,
            )
        ),
        timeout=0.1,
    )
    await asyncio.wait_for(process.terminate_started.wait(), timeout=1)

    assert process.closed is False
    assert await registry.get(terminal_id="terminal-1") is None

    terminate_gate.set()
    await asyncio.wait_for(clients[0].closed.wait(), timeout=1)
    await asyncio.wait_for(process.closed_event.wait(), timeout=1)


@pytest.mark.asyncio
async def test_missing_heartbeat_ack_reconnects_with_next_stream_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(terminal_stream_module, "_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(
        terminal_stream_module,
        "_HEARTBEAT_ACK_TIMEOUT_SECONDS",
        0.03,
    )
    monkeypatch.setattr(terminal_stream_module, "_RECONNECT_DELAY_SECONDS", 0.001)
    backend = _Backend(_Process())
    clients: list[_Client] = []
    reconnected = asyncio.Event()

    def client_factory() -> _Client:
        client = _Client()
        clients.append(client)
        if len(clients) >= 2:
            reconnected.set()
        return client

    manager, _registry = _manager(
        backend=backend,
        client_factory=client_factory,
    )
    await manager.handle_open(_open_intent())

    await asyncio.wait_for(reconnected.wait(), timeout=1)
    await asyncio.wait_for(clients[1].started.wait(), timeout=1)

    assert clients[0].registration is not None
    assert clients[0].registration.stream_generation == 1
    assert clients[1].registration is not None
    assert clients[1].registration.stream_generation == 2
    await manager.close()


@pytest.mark.asyncio
async def test_hanging_final_attempt_cannot_exceed_overall_stream_grace() -> None:
    process = _Process()
    client = _HangingClient()
    manager, _registry = _manager(
        backend=_Backend(process),
        client_factory=lambda: client,
        stream_grace_seconds=0.03,
        clock=time.monotonic,
    )

    await manager.handle_open(_open_intent())
    await asyncio.wait_for(client.started.wait(), timeout=1)
    await asyncio.wait_for(process.closed_event.wait(), timeout=0.2)

    assert client.closed.is_set() is True


@pytest.mark.asyncio
async def test_natural_shell_exit_reports_process_exit_reason() -> None:
    process = _Process()
    backend = _Backend(process)
    clients: list[_Client] = []
    client_created = asyncio.Event()

    def client_factory() -> _Client:
        client = _Client()
        clients.append(client)
        client_created.set()
        return client

    manager, _registry = _manager(
        backend=backend,
        client_factory=client_factory,
    )
    await manager.handle_open(_open_intent())
    await asyncio.wait_for(client_created.wait(), timeout=1)
    await asyncio.wait_for(clients[0].started.wait(), timeout=1)

    process.exit(7)
    await asyncio.wait_for(clients[0].sent_event.wait(), timeout=1)

    assert clients[0].sent == [
        RunnerTerminalExit(
            reason=RunnerTerminalTerminationReason.PROCESS_EXIT,
            exit_code=7,
        )
    ]
    await asyncio.wait_for(clients[0].closed.wait(), timeout=1)


def _manager(
    *,
    backend: _Backend,
    client_factory: Callable[[], _Client],
    accepted_generation: Callable[[], int | None] = lambda: 3,
    stream_grace_seconds: float = 120,
    clock: Callable[[], float] = lambda: 0.0,
) -> tuple[RunnerTerminalStreamManager, RunnerTerminalRegistry]:
    registry = RunnerTerminalRegistry(
        backend=backend,
        limits=TerminalLimits(
            max_active_per_session=1,
            max_active_per_runtime=16,
            idle_timeout_seconds=1800,
            maximum_lifetime_seconds=28800,
            stream_grace_seconds=stream_grace_seconds,
            stream_attempt_timeout_seconds=30,
            maximum_chunk_bytes=16 * 1024,
            maximum_unacknowledged_output_bytes=256 * 1024,
        ),
        clock=clock,
        utc_clock=lambda: _NOW,
    )
    return (
        RunnerTerminalStreamManager(
            registry=registry,
            runtime_id="runtime-1",
            workspace_root=Path("/workspace"),
            environment={},
            accepted_generation=accepted_generation,
            client_factory=client_factory,
        ),
        registry,
    )


def _open_intent() -> RunnerTerminalOpenIntent:
    return RunnerTerminalOpenIntent(
        identity=_identity(),
        owner_session_id="session-1",
        working_directory="/workspace/session",
        columns=120,
        rows=40,
        idle_deadline_at=_NOW + timedelta(minutes=30),
        maximum_deadline_at=_NOW + timedelta(hours=8),
        data_stream_grace_deadline_at=_NOW + timedelta(minutes=2),
        stream_nonce="nonce-1",
        initial_stream_generation=1,
    )


def _identity() -> RunnerTerminalIdentity:
    return RunnerTerminalIdentity(
        terminal_id="terminal-1",
        runtime_id="runtime-1",
        runner_generation=3,
    )
