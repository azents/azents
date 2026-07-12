"""Agent Runtime Runner Control gRPC server tests."""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# protobuf generated modules expose dynamic message attributes.

import asyncio
import dataclasses
import inspect
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import grpc
import pytest
from azents_runtime_control.proto import runtime_runner_control_pb2
from azents_runtime_control.runner import RunnerStateReport
from azents_runtime_control.runner import RuntimeRunnerState as SharedRunnerState
from google.protobuf import timestamp_pb2

from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProtocolRouteUnavailable,
    RuntimeRunnerOperation,
)
from azents.runtime.control_protocol.grpc.runner_server import (
    RuntimeRunnerControlGrpcServicer,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import (
    RuntimeCoordinationTarget,
    RuntimeOperationStatus,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
    RuntimeRequestEnvelope,
)
from azents.runtime.coordination.memory import (
    InMemoryRuntimeCoordinationStore,
)


@dataclasses.dataclass
class FakeStateSink:
    """Collect Runner state reports delivered by the gRPC bridge."""

    reports: list[RunnerStateReport] = dataclasses.field(default_factory=list)

    async def record_runner_state(self, report: RunnerStateReport) -> None:
        """Record one Runner state report."""
        self.reports.append(report)


class QueueIterator:
    """Async iterator backed by a queue."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[runtime_runner_control_pb2.RunnerMessage | None] = (
            asyncio.Queue()
        )

    async def put(
        self,
        message: runtime_runner_control_pb2.RunnerMessage | None,
    ) -> None:
        """Append an inbound message."""
        await self._queue.put(message)

    def __aiter__(self) -> "QueueIterator":
        """Return self."""
        return self

    async def __anext__(self) -> runtime_runner_control_pb2.RunnerMessage:
        """Return the next queued message."""
        message = await self._queue.get()
        if message is None:
            raise StopAsyncIteration
        return message


class FakeGrpcContext:
    """Minimal gRPC context for tests."""

    def __init__(
        self,
        metadata: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self._metadata = metadata

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        """Return fake request metadata."""
        return self._metadata

    async def abort(
        self,
        code: grpc.StatusCode,
        details: str,
    ) -> NoReturn:
        """Raise a RuntimeError instead of aborting a real RPC."""
        raise RuntimeError(f"{code.name}: {details}")


class CountingRelayControlProtocol:
    """Return queued envelopes while recording durable claims."""

    def __init__(self, envelopes: list[RuntimeRequestEnvelope]) -> None:
        self.envelopes = envelopes
        self.claim_count = 0

    async def claim_next_runner_request(
        self,
        *,
        runtime_id: str,
        generation: int,
        consumer_id: str,
        block_ms: int,
    ) -> RuntimeRequestEnvelope | None:
        """Return one envelope for each claim."""
        del runtime_id, generation, consumer_id, block_ms
        self.claim_count += 1
        if not self.envelopes:
            await asyncio.sleep(3600)
            return None
        return self.envelopes.pop(0)


@pytest.mark.asyncio
async def test_runner_grpc_registers_and_acks_heartbeat() -> None:
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeStateSink()
    servicer = _servicer(RuntimeControlProtocolService(store), store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="heartbeat-1",
            generation=1,
            heartbeat=runtime_runner_control_pb2.RunnerHeartbeat(
                monotonic_sequence=7,
            ),
        )
    )
    await inbound.put(None)

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    heartbeat_ack = await anext(stream)
    await stream.aclose()

    assert accepted.register_accepted.runtime_id == "runtime-1"
    assert accepted.register_accepted.generation == 1
    assert heartbeat_ack.heartbeat_ack.monotonic_sequence == 7
    assert sink.reports[-1].runner_state is SharedRunnerState.UNKNOWN
    assert sink.reports[-1].diagnostic["reason"] == "runner_stream_closed"


@pytest.mark.asyncio
async def test_runner_grpc_revoke_current_connection_on_close() -> None:
    """Closing the current Runner stream removes it from operation routing."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    await stream.aclose()

    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="process.start",
            owner_session_id="session-1",
            payload={"command": "echo ok"},
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=datetime.now(UTC),
    )

    assert isinstance(result, RuntimeProtocolRouteUnavailable)
    assert sink.reports[-1].diagnostic["reason"] == "runner_stream_closed"


@pytest.mark.asyncio
async def test_runner_grpc_ignores_stale_stream_close_after_reconnect() -> None:
    """Old Runner stream closure must not overwrite newer generation state."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    old_inbound = QueueIterator()
    await old_inbound.put(_register_message("connection-1"))
    old_stream = servicer.ConnectRunner(old_inbound, FakeGrpcContext())
    old_accepted = await anext(old_stream)
    new_inbound = QueueIterator()
    await new_inbound.put(_register_message("connection-2"))
    new_stream = servicer.ConnectRunner(new_inbound, FakeGrpcContext())
    new_accepted = await anext(new_stream)

    await old_stream.aclose()

    assert old_accepted.register_accepted.generation == 1
    assert new_accepted.register_accepted.generation == 2
    assert sink.reports == []

    await new_stream.aclose()
    assert sink.reports[-1].runner_generation == 2
    assert sink.reports[-1].diagnostic["connection_id"] == "connection-2"


@pytest.mark.asyncio
async def test_runner_grpc_rejects_stream_generation_mismatch() -> None:
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeStateSink()
    servicer = _servicer(RuntimeControlProtocolService(store), store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="state-1",
            generation=2,
            state_report=_state_report_message(),
        )
    )

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    error = await anext(stream)
    await stream.aclose()

    assert accepted.register_accepted.generation == 1
    assert error.error.code == "STALE_RUNNER_GENERATION"
    assert all(
        report.runner_state is not SharedRunnerState.READY for report in sink.reports
    )


@pytest.mark.asyncio
async def test_runner_grpc_rejects_state_report_after_newer_registration() -> None:
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    old_inbound = QueueIterator()
    await old_inbound.put(_register_message("connection-1"))
    old_stream = servicer.ConnectRunner(old_inbound, FakeGrpcContext())
    old_accepted = await anext(old_stream)
    new_inbound = QueueIterator()
    await new_inbound.put(_register_message("connection-2"))
    new_stream = servicer.ConnectRunner(new_inbound, FakeGrpcContext())
    new_accepted = await anext(new_stream)
    await old_inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="state-1",
            generation=old_accepted.register_accepted.generation,
            state_report=_state_report_message(),
        )
    )

    error = await anext(old_stream)
    await old_stream.aclose()
    await new_stream.aclose()

    assert old_accepted.register_accepted.generation == 1
    assert new_accepted.register_accepted.generation == 2
    assert error.error.code == "STALE_RUNNER_GENERATION"
    assert all(
        report.runner_state is not SharedRunnerState.READY for report in sink.reports
    )


@pytest.mark.asyncio
async def test_runner_grpc_rejects_state_report_generation_mismatch() -> None:
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeStateSink()
    servicer = _servicer(RuntimeControlProtocolService(store), store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())
    state_report = _state_report_message()
    state_report.runner_generation = 2
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="state-1",
            generation=1,
            state_report=state_report,
        )
    )

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    error = await anext(stream)
    await stream.aclose()

    assert accepted.register_accepted.generation == 1
    assert error.error.code == "STALE_RUNNER_GENERATION"
    assert all(
        report.runner_state is not SharedRunnerState.READY for report in sink.reports
    )


@pytest.mark.asyncio
async def test_runner_grpc_relays_operations_and_appends_events() -> None:
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="process.start",
            owner_session_id="session-1",
            payload={
                "command": "python -m http.server",
                "workdir": "/workspace/agent",
                "yield_time_ms": 1000,
                "max_output_bytes": 4096,
                "env": {"PYTHONUNBUFFERED": "1"},
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )

    command = await anext(stream)
    assert isinstance(result, RuntimeDispatchResult)
    assert command.operation_request.runtime_id == "runtime-1"
    assert command.operation_request.operation_type == "process.start"
    assert command.operation_request.owner_session_id == "session-1"
    assert command.operation_request.HasField("owner_session_id")
    assert command.operation_request.WhichOneof("payload") == "process_start"
    assert command.operation_request.process_start.command == "python -m http.server"
    assert command.operation_request.process_start.workdir == "/workspace/agent"
    assert command.operation_request.process_start.yield_time_ms == 1000
    assert command.operation_request.process_start.max_output_bytes == 4096
    assert command.operation_request.process_start.env == {"PYTHONUNBUFFERED": "1"}

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="start:req-1",
            generation=accepted.register_accepted.generation,
            operation_start=runtime_runner_control_pb2.RunnerOperationStart(
                runtime_id="runtime-1",
                operation_id="operation:req-1",
            ),
        )
    )
    start_ack = await anext(stream)
    assert start_ack.operation_start_ack.allowed

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="req-1",
            generation=accepted.register_accepted.generation,
            operation_event=runtime_runner_control_pb2.RunnerOperationEvent(
                runtime_id="runtime-1",
                operation_id="operation:req-1",
                generation=accepted.register_accepted.generation,
                event_type="process_output",
                created_at=_timestamp(_now()),
                final=False,
                process_output=runtime_runner_control_pb2.RunnerProcessOutputPayload(
                    process_id="proc_123",
                    stream="stdout",
                    chunk_id=1,
                    text="Serving HTTP",
                    truncated=False,
                    omitted_bytes=0,
                ),
            ),
        )
    )
    await asyncio.sleep(0)
    replies = await service.read_replies(
        reply_stream_id=result.reply_stream_id,
        after_cursor=None,
        limit=10,
    )

    assert replies[0].event.event_type is RuntimeReplyEventType.PROCESS_OUTPUT
    assert replies[0].event.payload["process_id"] == "proc_123"
    assert replies[0].event.payload["text"] == "Serving HTTP"
    await stream.aclose()


@pytest.mark.asyncio
async def test_runner_grpc_expires_operation_before_relay() -> None:
    """Expired Runner operations are finalized and acked without relaying."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="process.start",
            owner_session_id="session-1",
            payload={
                "command": "python -m http.server",
                "workdir": "/workspace/agent",
                "yield_time_ms": 1000,
                "max_output_bytes": 4096,
            },
            deadline_at=_now() - timedelta(seconds=1),
            body_stream_id=None,
        ),
        created_at=_now() - timedelta(seconds=2),
    )

    assert isinstance(result, RuntimeDispatchResult)
    replies = []
    for _ in range(10):
        replies = await service.read_replies(
            reply_stream_id=result.reply_stream_id,
            after_cursor=None,
            limit=10,
        )
        if replies:
            break
        await asyncio.sleep(0.01)

    assert len(replies) == 1
    assert replies[0].event.event_type is RuntimeReplyEventType.FINAL_ERROR
    assert replies[0].event.payload["error_code"] == "RUNNER_OPERATION_EXPIRED"
    assert (
        await service.claim_next_runner_request(
            runtime_id="runtime-1",
            generation=accepted.register_accepted.generation,
            consumer_id="runner-b",
            block_ms=0,
        )
        is None
    )
    await stream.aclose()


@pytest.mark.asyncio
async def test_runner_grpc_rejects_start_for_canceled_operation() -> None:
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="file.stat",
            owner_session_id="session-1",
            payload={"path": "/workspace/agent"},
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )
    await anext(stream)
    await store.update_operation_status(
        result.operation_id,
        status=RuntimeOperationStatus.FINAL,
        updated_at=_now(),
        final_event_cursor="1-0",
    )

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="start:req-1",
            generation=accepted.register_accepted.generation,
            operation_start=runtime_runner_control_pb2.RunnerOperationStart(
                runtime_id="runtime-1",
                operation_id=result.operation_id,
            ),
        )
    )

    start_ack = await anext(stream)
    assert not start_ack.operation_start_ack.allowed
    await stream.aclose()


@pytest.mark.asyncio
async def test_runner_operation_relay_backpressures_durable_claims() -> None:
    envelopes = [
        RuntimeRequestEnvelope(
            request_id=f"req-{index}",
            runtime_id="runtime-1",
            target=RuntimeCoordinationTarget.RUNNER,
            generation=1,
            operation_type="file.stat",
            payload={"payload": {"path": "/workspace/agent"}},
            reply_stream_id="reply-1",
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        )
        for index in range(3)
    ]
    control = CountingRelayControlProtocol(envelopes)
    store = InMemoryRuntimeCoordinationStore()
    servicer = RuntimeRunnerControlGrpcServicer(
        control_protocol=control,
        coordination_store=store,
        state_sink=FakeStateSink(),
        owner_replica_id="control-a",
        consumer_id="runner-consumer-a",
        operation_block_ms=1,
        control_auth_token=None,
    )
    outbound: asyncio.Queue[runtime_runner_control_pb2.RunnerControlMessage] = (
        asyncio.Queue(maxsize=1)
    )

    task = asyncio.create_task(
        servicer._relay_runner_operations(  # pyright: ignore[reportPrivateUsage]  # Exercise relay backpressure directly.
            outbound,
            runtime_id="runtime-1",
            generation=1,
        )
    )
    for _ in range(100):
        if control.claim_count >= 2:
            break
        await asyncio.sleep(0.01)

    assert outbound.qsize() == 1
    assert control.claim_count == 2
    assert len(control.envelopes) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_runner_grpc_relays_git_operation_payload() -> None:
    """The gRPC bridge maps Git operation payloads to protobuf oneofs."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-git")
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="create_git_worktree",
            owner_session_id=None,
            payload={
                "source_project_path": "/workspace/agent/repo",
                "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
                "branch_name": "azents/session",
                "starting_ref": "main",
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )

    command = await anext(stream)
    assert command.operation_request.operation_type == "create_git_worktree"
    assert not command.operation_request.HasField("owner_session_id")
    assert command.operation_request.WhichOneof("payload") == "git_create_worktree"
    assert command.operation_request.git_create_worktree.source_project_path == (
        "/workspace/agent/repo"
    )
    assert command.operation_request.git_create_worktree.branch_name == "azents/session"
    await stream.aclose()


@pytest.mark.asyncio
async def test_runner_grpc_rejects_missing_control_token() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(
        RuntimeControlProtocolService(store),
        store,
        FakeStateSink(),
        control_auth_token="control-token",
    )
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())

    with pytest.raises(RuntimeError, match="UNAUTHENTICATED"):
        await anext(stream)


@pytest.mark.asyncio
async def test_runner_grpc_rejects_wrong_control_token() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(
        RuntimeControlProtocolService(store),
        store,
        FakeStateSink(),
        control_auth_token="control-token",
    )
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(
        inbound,
        FakeGrpcContext((("authorization", "Bearer wrong"),)),
    )

    with pytest.raises(RuntimeError, match="UNAUTHENTICATED"):
        await anext(stream)


@pytest.mark.asyncio
async def test_runner_grpc_accepts_bearer_control_token() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(
        RuntimeControlProtocolService(store),
        store,
        FakeStateSink(),
        control_auth_token="control-token",
    )
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(
        inbound,
        FakeGrpcContext((("authorization", "Bearer control-token"),)),
    )
    accepted = await anext(stream)
    await stream.aclose()

    assert accepted.register_accepted.runtime_id == "runtime-1"


@pytest.mark.asyncio
async def test_runner_grpc_start_claim_is_atomic() -> None:
    """Start authorization claims ACTIVE operations so cancel can win before start."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="file.stat",
            owner_session_id="session-1",
            payload={"path": "/workspace/agent"},
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )
    await anext(stream)

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="start:req-1",
            generation=accepted.register_accepted.generation,
            operation_start=runtime_runner_control_pb2.RunnerOperationStart(
                runtime_id="runtime-1",
                operation_id=result.operation_id,
            ),
        )
    )
    start_ack = await anext(stream)
    assert start_ack.operation_start_ack.allowed
    metadata = await store.get_operation(result.operation_id)
    assert metadata is not None
    assert metadata.status is RuntimeOperationStatus.RUNNING

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="start:req-1-retry",
            generation=accepted.register_accepted.generation,
            operation_start=runtime_runner_control_pb2.RunnerOperationStart(
                runtime_id="runtime-1",
                operation_id=result.operation_id,
            ),
        )
    )
    retry_ack = await anext(stream)
    assert not retry_ack.operation_start_ack.allowed
    await stream.aclose()


@pytest.mark.asyncio
async def test_runner_grpc_rejects_late_final_after_cancel() -> None:
    """Late Runner finals must not overwrite a canceled final cursor."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="file.stat",
            owner_session_id="session-1",
            payload={"path": "/workspace/agent"},
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )
    await anext(stream)
    canceled = await store.append_reply_for_operation(
        result.reply_stream_id,
        RuntimeReplyEvent(
            request_id="req-1",
            runtime_id="runtime-1",
            generation=accepted.register_accepted.generation,
            event_type=RuntimeReplyEventType.FINAL_ERROR,
            payload={"error_code": "canceled", "error_message": "cancelled"},
            created_at=_now(),
            final=True,
        ),
        operation_id=result.operation_id,
    )
    assert canceled is not None
    cancel_cursor, _ = canceled

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="req-1",
            generation=accepted.register_accepted.generation,
            operation_event=runtime_runner_control_pb2.RunnerOperationEvent(
                runtime_id="runtime-1",
                operation_id=result.operation_id,
                generation=accepted.register_accepted.generation,
                event_type="final_success",
                created_at=_timestamp(_now()),
                final=True,
                final_success=(
                    runtime_runner_control_pb2.RunnerOperationFinalSuccessPayload(
                        bash=runtime_runner_control_pb2.BashFinalSuccess(
                            exit_code=0,
                        )
                    )
                ),
            ),
        )
    )
    await asyncio.sleep(0)
    metadata = await store.get_operation(result.operation_id)
    assert metadata is not None
    assert metadata.status is RuntimeOperationStatus.FINAL
    assert metadata.final_event_cursor == cancel_cursor
    replies = await service.read_replies(
        reply_stream_id=result.reply_stream_id,
        after_cursor=None,
        limit=10,
    )
    assert len(replies) == 1
    assert replies[0].event.event_type is RuntimeReplyEventType.FINAL_ERROR
    await stream.aclose()


def test_connect_runner_outbound_queue_is_bounded() -> None:
    """ConnectRunner constructs a maxsize=1 outbound queue for backpressure."""
    source = inspect.getsource(RuntimeRunnerControlGrpcServicer.ConnectRunner)
    assert "asyncio.Queue(maxsize=1)" in source


def _servicer(
    service: RuntimeControlProtocolService,
    store: InMemoryRuntimeCoordinationStore,
    sink: FakeStateSink,
    *,
    control_auth_token: str | None = None,
) -> RuntimeRunnerControlGrpcServicer:
    return RuntimeRunnerControlGrpcServicer(
        control_protocol=service,
        coordination_store=store,
        state_sink=sink,
        owner_replica_id="control-a",
        consumer_id="runner-consumer-a",
        control_auth_token=control_auth_token,
        operation_block_ms=1,
    )


def _register_message(
    connection_id: str = "connection-1",
) -> runtime_runner_control_pb2.RunnerMessage:
    return runtime_runner_control_pb2.RunnerMessage(
        connection_id=connection_id,
        request_id="register",
        register=runtime_runner_control_pb2.RunnerRegister(
            runtime_id="runtime-1",
            runner_id="runner-1",
            protocol_version="agent-runtime-runner.v1",
            capabilities=("bash", "file.read"),
            health="ok",
            workspace_path="/workspace/agent",
            auth_credential_id="credential-1",
        ),
    )


def _state_report_message() -> runtime_runner_control_pb2.RunnerStateReport:
    return runtime_runner_control_pb2.RunnerStateReport(
        runtime_id="runtime-1",
        runner_id="runner-1",
        runner_generation=1,
        runner_state="ready",
        capabilities=("bash", "file.read"),
        health="ok",
        workspace_path="/workspace/agent",
        reported_at=_timestamp(_now()),
    )


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _now() -> datetime:
    return datetime(2026, 5, 25, tzinfo=UTC)
