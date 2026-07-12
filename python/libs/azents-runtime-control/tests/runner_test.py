"""Runner run loop contract tests."""

import asyncio
import dataclasses
import json
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TypedDict

import pytest

from azents_runtime_control.runner import (
    RunnerControlClient,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RunnerRegistration,
    RunnerRegistrationAccepted,
    RunnerRunLoop,
    RunnerStateReport,
    RuntimeRunnerEventType,
    RuntimeRunnerOperations,
    RuntimeRunnerState,
)


class FakeRunnerControlClient(RunnerControlClient):
    """In-memory Control client for Runner loop tests."""

    def __init__(self) -> None:
        self.operations: list[RunnerOperationEnvelope] = []
        self.claimed_request_ids: list[str] = []
        self.heartbeats: list[tuple[str, int]] = []
        self.reports: list[RunnerStateReport] = []
        self.events: list[RunnerOperationEvent] = []
        self.canceled_request_ids: set[str] = set()
        self.operation_handler: (
            Callable[[RunnerOperationEnvelope], Awaitable[None]] | None
        ) = None

    def set_operation_handler(
        self,
        handler: Callable[[RunnerOperationEnvelope], Awaitable[None]],
    ) -> None:
        """Record the direct operation handler."""
        self.operation_handler = handler

    async def register_runner(
        self,
        registration: RunnerRegistration,
        *,
        connection_id: str,
        registered_at: datetime,
    ) -> RunnerRegistrationAccepted:
        """Return an accepted registration."""
        del registered_at
        return RunnerRegistrationAccepted(
            runtime_id=registration.runtime_id,
            runner_id=registration.runner_id,
            connection_id=connection_id,
            generation=7,
            heartbeat_interval_seconds=20,
        )

    async def heartbeat_runner(
        self,
        *,
        runtime_id: str,
        generation: int,
        heartbeat_at: datetime,
    ) -> bool:
        """Record a heartbeat."""
        del heartbeat_at
        self.heartbeats.append((runtime_id, generation))
        return True

    async def report_runner_state(self, report: RunnerStateReport) -> None:
        """Record one Runner state report."""
        self.reports.append(report)

    async def claim_next_runner_operation(
        self,
        *,
        runtime_id: str,
        generation: int,
        consumer_id: str,
        block_ms: int,
    ) -> RunnerOperationEnvelope | None:
        """Return the next queued operation."""
        del runtime_id, generation, consumer_id, block_ms
        if not self.operations:
            return None
        operation = self.operations.pop(0)
        self.claimed_request_ids.append(operation.request_id)
        return operation

    async def start_runner_operation(
        self,
        operation: RunnerOperationEnvelope,
    ) -> bool:
        """Allow execution unless the test canceled the operation."""
        return operation.request_id not in self.canceled_request_ids

    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        """Record one Runner event."""
        self.events.append(event)


@dataclasses.dataclass
class BlockingOperations(RuntimeRunnerOperations):
    """Hold operations until their release signal is set."""

    started: list[str] = dataclasses.field(default_factory=list)
    finished: list[str] = dataclasses.field(default_factory=list)
    _release_events: dict[str, asyncio.Event] = dataclasses.field(default_factory=dict)

    async def handle(self, operation: RunnerOperationEnvelope) -> None:
        """Record start and wait for release."""
        self.started.append(operation.request_id)
        event = self._release_events.setdefault(operation.request_id, asyncio.Event())
        await event.wait()
        self.finished.append(operation.request_id)

    def release(self, request_id: str) -> None:
        """Release one operation."""
        self._release_events.setdefault(request_id, asyncio.Event()).set()


@pytest.mark.asyncio
async def test_run_once_schedules_different_sessions_concurrently() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    client.operations.extend(
        (_operation("req-a", owner="session-a"), _operation("req-b", owner="session-b"))
    )
    loop = _loop(client, operations, max_concurrent_operations=2)
    await loop.start()

    await _run(loop, 2)
    await _wait_for(lambda: operations.started == ["req-a", "req-b"])

    operations.release("req-a")
    operations.release("req-b")
    await _wait_for(lambda: len(operations.finished) == 2)
    await loop.run_once(block_ms=0)


@pytest.mark.asyncio
async def test_default_limits_allow_five_sessions_to_fill_runtime_capacity() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    client.operations.extend(
        _operation(f"{owner}-{index}", owner=owner)
        for owner in (f"session-{index}" for index in range(1, 6))
        for index in range(1, 11)
    )
    loop = _loop(client, operations)
    await loop.start()

    await _run(loop, 50)
    await _wait_for(lambda: len(operations.started) == 50)

    active_by_owner = Counter(
        request_id.rsplit("-", 1)[0] for request_id in operations.started
    )
    assert active_by_owner == {f"session-{index}": 10 for index in range(1, 6)}
    assert client.reports[-1].diagnostic["runtime_active_operations"] == "50"
    await _cancel_loop_work(loop)


@pytest.mark.asyncio
async def test_session_limit_does_not_block_another_session() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    client.operations.extend(
        (
            _operation("a-1", owner="session-a"),
            _operation("a-2", owner="session-a"),
            _operation("a-3", owner="session-a"),
            _operation("b-1", owner="session-b"),
        )
    )
    loop = _loop(
        client,
        operations,
        max_concurrent_operations_per_session=1,
        max_concurrent_operations=2,
    )
    await loop.start()

    await _run(loop, 4)
    await _wait_for(lambda: operations.started == ["a-1", "b-1"])

    operations.release("a-1")
    await _wait_for(lambda: "a-1" in operations.finished)
    await loop.run_once(block_ms=0)
    await _wait_for(lambda: operations.started == ["a-1", "b-1", "a-2"])
    operations.release("a-2")
    operations.release("a-3")
    operations.release("b-1")
    await _cancel_loop_work(loop)


@pytest.mark.asyncio
async def test_owner_queue_preserves_fifo_order() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    client.operations.extend(
        _operation(f"req-{index}", owner="session-a") for index in range(1, 4)
    )
    loop = _loop(
        client,
        operations,
        max_concurrent_operations_per_session=1,
        max_concurrent_operations=2,
    )
    await loop.start()

    await _run(loop, 3)
    await _wait_for(lambda: operations.started == ["req-1"])
    for request_id in ("req-1", "req-2", "req-3"):
        operations.release(request_id)
        await _wait_for(lambda request_id=request_id: request_id in operations.finished)
        await loop.run_once(block_ms=0)

    assert operations.started == ["req-1", "req-2", "req-3"]


@pytest.mark.asyncio
async def test_owner_backlogs_are_scheduled_round_robin() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    loop = _loop(
        client,
        operations,
        max_concurrent_operations_per_session=1,
        max_concurrent_operations=1,
    )
    await loop.start()
    assert client.operation_handler is not None
    for request_id, owner in (
        ("a-1", "session-a"),
        ("a-2", "session-a"),
        ("b-1", "session-b"),
        ("b-2", "session-b"),
    ):
        await client.operation_handler(_operation(request_id, owner=owner))

    for request_id in ("a-1", "b-1", "a-2", "b-2"):
        await loop.run_once(block_ms=0)
        await _wait_for(
            lambda request_id=request_id: (
                bool(operations.started) and operations.started[-1] == request_id
            )
        )
        operations.release(request_id)
        await _wait_for(lambda request_id=request_id: request_id in operations.finished)

    assert operations.started == ["a-1", "b-1", "a-2", "b-2"]
    await loop.run_once(block_ms=0)


@pytest.mark.asyncio
async def test_system_operations_use_independent_limit() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    client.operations.extend(
        (
            _operation("system-1", owner=None),
            _operation("system-2", owner=None),
            _operation("session-1", owner="session-a"),
        )
    )
    loop = _loop(
        client,
        operations,
        max_concurrent_system_operations=1,
        max_concurrent_operations_per_session=1,
        max_concurrent_operations=2,
    )
    await loop.start()

    await _run(loop, 3)
    await _wait_for(lambda: operations.started == ["system-1", "session-1"])
    await _cancel_loop_work(loop)


@pytest.mark.asyncio
async def test_rejects_operation_when_owner_pending_queue_is_full() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    client.operations.extend(
        _operation(f"req-{index}", owner="session-a") for index in range(1, 4)
    )
    loop = _loop(
        client,
        operations,
        max_concurrent_operations_per_session=1,
        max_concurrent_operations=1,
        max_pending_operations_per_owner=1,
        max_pending_operations=2,
    )
    await loop.start()

    await _run(loop, 3)

    assert len(client.events) == 1
    assert client.events[0].request_id == "req-3"
    assert client.events[0].event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert client.events[0].payload["error_code"] == "operation_queue_full"
    assert client.reports[-1].diagnostic["queue_rejection_count"] == "1"
    await _cancel_loop_work(loop)


@pytest.mark.asyncio
async def test_rejects_operation_when_runtime_pending_queue_is_full() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    loop = _loop(
        client,
        operations,
        max_concurrent_operations=1,
        max_pending_operations_per_owner=2,
        max_pending_operations=2,
    )
    await loop.start()
    assert client.operation_handler is not None

    await client.operation_handler(_operation("a-1", owner="session-a"))
    await client.operation_handler(_operation("b-1", owner="session-b"))
    await client.operation_handler(_operation("c-1", owner="session-c"))

    assert client.events[-1].request_id == "c-1"
    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert client.events[-1].payload["error_code"] == "operation_queue_full"
    diagnostic = client.reports[-1].diagnostic
    assert diagnostic["runtime_pending_operations"] == "2"
    assert diagnostic["queue_rejection_count"] == "1"


@pytest.mark.asyncio
async def test_expired_pending_operation_is_not_executed() -> None:
    now = datetime(2026, 5, 25, tzinfo=UTC)
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    client.operations.extend(
        (
            _operation("active", owner="session-a"),
            _operation(
                "expired",
                owner="session-a",
                deadline_at=now - timedelta(seconds=1),
            ),
        )
    )
    loop = _loop(
        client,
        operations,
        clock=lambda: now,
        max_concurrent_operations_per_session=1,
        max_concurrent_operations=1,
    )
    await loop.start()

    await _run(loop, 2)
    operations.release("active")
    await _wait_for(lambda: "active" in operations.finished)
    await loop.run_once(block_ms=0)

    assert operations.started == ["active"]
    assert client.events[0].request_id == "expired"
    assert client.events[0].payload["error_code"] == "operation_timeout"
    assert client.reports[-1].diagnostic["pre_execution_timeout_count"] == "1"


@pytest.mark.asyncio
async def test_state_reports_expose_per_owner_and_runtime_counts() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    loop = _loop(
        client,
        operations,
        max_concurrent_operations=2,
        max_pending_operations_per_owner=2,
        max_pending_operations=2,
    )
    await loop.start()
    assert client.operation_handler is not None

    await client.operation_handler(_operation("session", owner="session-a"))
    await client.operation_handler(_operation("system", owner=None))
    await client.operation_handler(_operation("rejected", owner="session-b"))

    pending = client.reports[-1]
    assert pending.runner_state == RuntimeRunnerState.BUSY
    assert pending.diagnostic["runtime_pending_operations"] == "2"
    session_pending = pending.diagnostic["session_pending_operations"]
    assert isinstance(session_pending, str)
    assert json.loads(session_pending) == {"session-a": 1}
    assert pending.diagnostic["system_pending_operations"] == "1"

    await _run(loop, 2)
    await _wait_for(lambda: len(operations.started) == 2)

    active = client.reports[-1]
    assert active.active_operation_ids == (
        "operation:session",
        "operation:system",
    )
    assert active.diagnostic["runtime_active_operations"] == "2"
    session_active = active.diagnostic["session_active_operations"]
    assert isinstance(session_active, str)
    assert json.loads(session_active) == {"session-a": 1}
    assert active.diagnostic["system_active_operations"] == "1"
    await _cancel_loop_work(loop)


@pytest.mark.asyncio
async def test_canceled_pending_operation_is_not_executed() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    client.operations.extend(
        (
            _operation("active", owner="session-a"),
            _operation("canceled", owner="session-a"),
        )
    )
    loop = _loop(
        client,
        operations,
        max_concurrent_operations_per_session=1,
        max_concurrent_operations=1,
    )
    await loop.start()

    await _run(loop, 2)
    await _wait_for(lambda: operations.started == ["active"])
    client.canceled_request_ids.add("canceled")
    operations.release("active")
    await _wait_for(lambda: operations.finished == ["active"])
    await loop.run_once(block_ms=0)

    assert operations.started == ["active"]


@pytest.mark.asyncio
async def test_run_loop_shutdown_discards_pending_generation_work() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    loop = _loop(client, operations, max_concurrent_operations=1)
    await loop.start()
    assert client.operation_handler is not None
    await client.operation_handler(_operation("active", owner="session-a"))
    await client.operation_handler(_operation("stale-pending", owner="session-a"))
    await loop.run_once(block_ms=0)
    await _wait_for(lambda: operations.started == ["active"])

    task = asyncio.create_task(loop.run_forever(block_ms=0))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await loop.run_once(block_ms=0)
    assert operations.started == ["active"]


@pytest.mark.asyncio
async def test_control_operation_runs_while_ordinary_capacity_is_full() -> None:
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    client.operations.extend(
        (
            _operation("ordinary", owner="session-a"),
            _operation(
                "terminate",
                owner="session-a",
                operation_type="process.terminate_session",
            ),
        )
    )
    loop = _loop(
        client,
        operations,
        max_concurrent_operations_per_session=1,
        max_concurrent_operations=1,
        max_concurrent_control_operations=1,
    )
    await loop.start()

    await _run(loop, 2)
    await _wait_for(lambda: operations.started == ["ordinary", "terminate"])
    await _cancel_loop_work(loop)


class _RunnerLimitOverrides(TypedDict, total=False):
    max_concurrent_operations: int
    max_concurrent_operations_per_session: int
    max_pending_operations_per_owner: int


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_concurrent_operations": 0}, "max_concurrent_operations"),
        (
            {
                "max_concurrent_operations_per_session": 2,
                "max_concurrent_operations": 1,
            },
            "max_concurrent_operations_per_session",
        ),
        (
            {
                "max_pending_operations_per_owner": 1,
                "max_concurrent_operations_per_session": 2,
            },
            "max_pending_operations_per_owner",
        ),
    ],
)
def test_rejects_invalid_limits(
    kwargs: _RunnerLimitOverrides,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _loop(FakeRunnerControlClient(), BlockingOperations(), **kwargs)


def _loop(
    client: FakeRunnerControlClient,
    operations: RuntimeRunnerOperations,
    *,
    clock: Callable[[], datetime] | None = None,
    max_concurrent_operations_per_session: int | None = None,
    max_concurrent_system_operations: int | None = None,
    max_concurrent_operations: int = 50,
    max_pending_operations_per_owner: int = 100,
    max_pending_operations: int = 1000,
    max_concurrent_control_operations: int = 4,
) -> RunnerRunLoop:
    return RunnerRunLoop(
        client=client,
        operations=operations,
        registration=_registration(),
        connection_id="connection-1",
        consumer_id="consumer-1",
        clock=clock or (lambda: datetime(2026, 5, 25, tzinfo=UTC)),
        monotonic=lambda: 100.0,
        max_concurrent_operations_per_session=(
            max_concurrent_operations_per_session
            if max_concurrent_operations_per_session is not None
            else min(10, max_concurrent_operations)
        ),
        max_concurrent_system_operations=(
            max_concurrent_system_operations
            if max_concurrent_system_operations is not None
            else min(10, max_concurrent_operations)
        ),
        max_concurrent_operations=max_concurrent_operations,
        max_pending_operations_per_owner=max_pending_operations_per_owner,
        max_pending_operations=max_pending_operations,
        max_concurrent_control_operations=max_concurrent_control_operations,
    )


def _registration() -> RunnerRegistration:
    metadata: Mapping[str, str] = {"workspace_path_source": "provider"}
    capabilities: Sequence[str] = ("bash", "file.read")
    return RunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="agent-runtime-runner.v1",
        capabilities=capabilities,
        health="ok",
        workspace_path="/workspace/agent",
        metadata=metadata,
        auth_credential_id="credential-1",
    )


def _operation(
    request_id: str,
    *,
    owner: str | None,
    operation_type: str = "bash",
    deadline_at: datetime | None = None,
) -> RunnerOperationEnvelope:
    payload: Mapping[str, str] = {"command": "sleep 60"}
    return RunnerOperationEnvelope(
        request_id=request_id,
        runtime_id="runtime-1",
        runner_generation=7,
        operation_type=operation_type,
        payload=payload,
        reply_stream_id="runner:runtime-1:generation:7:replies",
        body_stream_id=None,
        body_chunks=(),
        deadline_at=deadline_at,
        owner_session_id=owner,
    )


async def _run(loop: RunnerRunLoop, count: int) -> None:
    for _ in range(count):
        await loop.run_once(block_ms=0)
        await asyncio.sleep(0)


async def _cancel_loop_work(loop: RunnerRunLoop) -> None:
    task = asyncio.create_task(loop.run_forever(block_ms=0))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def _wait_for(predicate: Callable[[], bool]) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met")
