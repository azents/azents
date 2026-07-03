"""Agent Runtime Runner Control gRPC server tests."""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# protobuf generated modules expose dynamic message attributes.

import asyncio
import dataclasses
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
    RuntimeRunnerOperation,
)
from azents.runtime.control_protocol.grpc.runner_server import (
    RuntimeRunnerControlGrpcServicer,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import RuntimeReplyEventType
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

    async def abort(
        self,
        code: grpc.StatusCode,
        details: str,
    ) -> NoReturn:
        """Raise a RuntimeError instead of aborting a real RPC."""
        raise RuntimeError(f"{code.name}: {details}")


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
            payload={
                "command": "python -m http.server",
                "workdir": "/workspace/agent",
                "yield_time_ms": 1000,
                "max_output_bytes": 4096,
                "owner_session_id": "session-1",
                "env": {"PYTHONUNBUFFERED": "1"},
            },
            deadline_at=_now() + timedelta(seconds=30),
            body_stream_id=None,
            background=False,
        ),
        created_at=_now(),
    )

    command = await anext(stream)
    assert isinstance(result, RuntimeDispatchResult)
    assert command.operation_request.runtime_id == "runtime-1"
    assert command.operation_request.operation_type == "process.start"
    assert command.operation_request.WhichOneof("payload") == "process_start"
    assert command.operation_request.process_start.command == "python -m http.server"
    assert command.operation_request.process_start.workdir == "/workspace/agent"
    assert command.operation_request.process_start.yield_time_ms == 1000
    assert command.operation_request.process_start.max_output_bytes == 4096
    assert command.operation_request.process_start.owner_session_id == "session-1"
    assert command.operation_request.process_start.env == {"PYTHONUNBUFFERED": "1"}

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
            payload={
                "source_project_path": "/workspace/agent/repo",
                "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
                "branch_name": "azents/session",
                "starting_ref": "main",
            },
            deadline_at=_now() + timedelta(seconds=30),
            body_stream_id=None,
            background=False,
        ),
        created_at=_now(),
    )

    command = await anext(stream)
    assert command.operation_request.operation_type == "create_git_worktree"
    assert command.operation_request.WhichOneof("payload") == "git_create_worktree"
    assert command.operation_request.git_create_worktree.source_project_path == (
        "/workspace/agent/repo"
    )
    assert command.operation_request.git_create_worktree.branch_name == "azents/session"
    await stream.aclose()


def _servicer(
    service: RuntimeControlProtocolService,
    store: InMemoryRuntimeCoordinationStore,
    sink: FakeStateSink,
) -> RuntimeRunnerControlGrpcServicer:
    return RuntimeRunnerControlGrpcServicer(
        control_protocol=service,
        coordination_store=store,
        state_sink=sink,
        owner_replica_id="control-a",
        consumer_id="runner-consumer-a",
        operation_block_ms=1,
    )


def _register_message() -> runtime_runner_control_pb2.RunnerMessage:
    return runtime_runner_control_pb2.RunnerMessage(
        connection_id="connection-1",
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


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _now() -> datetime:
    return datetime(2026, 5, 25, tzinfo=UTC)
