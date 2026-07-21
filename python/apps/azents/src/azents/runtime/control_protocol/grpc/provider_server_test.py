"""Agent Runtime Provider Control gRPC server tests."""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# protobuf generated modules expose dynamic message attributes.

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import grpc
import pytest
from azents_runtime_control.proto import runtime_provider_control_pb2
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)
from azents_runtime_control.provider import RuntimeProviderReport
from google.protobuf import timestamp_pb2

from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProviderCommand,
)
from azents.runtime.control_protocol.grpc.provider_server import (
    RuntimeProviderControlGrpcServicer,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import RuntimeReplyEventType
from azents.runtime.coordination.memory import (
    InMemoryRuntimeCoordinationStore,
)


@dataclasses.dataclass
class FakeReportSink:
    """Collect Provider reports delivered by the gRPC bridge."""

    reports: list[RuntimeProviderReport] = dataclasses.field(default_factory=list)

    async def record_provider_report(self, report: RuntimeProviderReport) -> None:
        """Record one Provider report."""
        self.reports.append(report)


class QueueIterator:
    """Async iterator backed by a queue."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[
            runtime_provider_control_pb2.ProviderMessage | None
        ] = asyncio.Queue()

    async def put(
        self,
        message: runtime_provider_control_pb2.ProviderMessage | None,
    ) -> None:
        """Append an inbound message."""
        await self._queue.put(message)

    def __aiter__(self) -> "QueueIterator":
        """Return self."""
        return self

    async def __anext__(self) -> runtime_provider_control_pb2.ProviderMessage:
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


@pytest.mark.asyncio
async def test_provider_grpc_registers_and_acks_heartbeat() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(RuntimeControlProtocolService(store), FakeReportSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())
    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="heartbeat-1",
            generation=1,
            heartbeat=runtime_provider_control_pb2.ProviderHeartbeat(
                monotonic_sequence=7,
            ),
        )
    )
    await inbound.put(None)

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    heartbeat_ack = await anext(stream)
    await stream.aclose()

    assert accepted.register_accepted.provider_id == "provider-1"
    assert accepted.register_accepted.generation == 1
    assert heartbeat_ack.heartbeat_ack.monotonic_sequence == 7


@pytest.mark.asyncio
async def test_provider_grpc_rejects_stream_generation_mismatch() -> None:
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeReportSink()
    servicer = _servicer(RuntimeControlProtocolService(store), sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())
    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="report-1",
            generation=2,
            report=_report_message(),
        )
    )

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    error = await anext(stream)
    await stream.aclose()

    assert accepted.register_accepted.generation == 1
    assert error.error.code == "STALE_PROVIDER_GENERATION"
    assert sink.reports == []


@pytest.mark.asyncio
async def test_provider_grpc_rejects_report_after_newer_registration() -> None:
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    sink = FakeReportSink()
    servicer = _servicer(service, sink)
    old_inbound = QueueIterator()
    await old_inbound.put(_register_message("connection-1"))
    old_stream = servicer.ConnectProvider(old_inbound, FakeGrpcContext())
    old_accepted = await anext(old_stream)
    new_inbound = QueueIterator()
    await new_inbound.put(_register_message("connection-2"))
    new_stream = servicer.ConnectProvider(new_inbound, FakeGrpcContext())
    new_accepted = await anext(new_stream)
    await old_inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="report-1",
            generation=old_accepted.register_accepted.generation,
            report=_report_message(),
        )
    )

    error = await anext(old_stream)
    await old_stream.aclose()
    await new_stream.aclose()

    assert old_accepted.register_accepted.generation == 1
    assert new_accepted.register_accepted.generation == 2
    assert error.error.code == "STALE_PROVIDER_GENERATION"
    assert sink.reports == []


@pytest.mark.asyncio
async def test_provider_grpc_rejects_report_generation_mismatch() -> None:
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeReportSink()
    servicer = _servicer(RuntimeControlProtocolService(store), sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())
    report = _report_message()
    report.provider_generation = 2
    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="report-1",
            generation=1,
            report=report,
        )
    )

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    error = await anext(stream)
    await stream.aclose()

    assert accepted.register_accepted.generation == 1
    assert error.error.code == "STALE_PROVIDER_GENERATION"
    assert sink.reports == []


@pytest.mark.asyncio
async def test_provider_grpc_relays_commands_and_records_completion() -> None:
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    sink = FakeReportSink()
    servicer = _servicer(service, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_provider_command(
        RuntimeProviderCommand(
            provider_id="provider-1",
            provider_generation=accepted.register_accepted.generation,
            runtime_id="runtime-1",
            desired_generation=5,
            command_type=RuntimeProviderCommandType.START,
            reset_final_desired_state=None,
            payload={
                "identity": {
                    "agent_id": "agent-1",
                    "workspace_id": "workspace-1",
                },
                "runner_image": "runner:latest",
                "auth": {
                    "control_endpoint": "runtime-control:8020",
                    "runner_auth_token": "runner-token",
                },
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        ),
        created_at=_now(),
    )

    command = await anext(stream)
    assert isinstance(result, RuntimeDispatchResult)
    assert command.provider_command.runtime_id == "runtime-1"
    assert command.provider_command.runner_image == "runner:latest"

    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="req-1",
            generation=accepted.register_accepted.generation,
            command_completion=runtime_provider_control_pb2.ProviderCommandCompletion(
                request_id="req-1",
                runtime_id="runtime-1",
                generation=accepted.register_accepted.generation,
                success=True,
                report=_report_message(),
                completed_at=_timestamp(_now()),
            ),
        )
    )
    await asyncio.sleep(0)
    replies = await service.read_replies(
        reply_stream_id=result.reply_stream_id,
        after_cursor=None,
        limit=10,
    )

    assert replies[0].event.event_type is RuntimeReplyEventType.FINAL_SUCCESS
    assert replies[0].event.payload["workspace_path"] == "/workspace/agent"
    assert sink.reports[0].workspace_path == "/workspace/agent"
    await stream.aclose()


@pytest.mark.asyncio
async def test_provider_grpc_rejects_missing_control_token() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(
        RuntimeControlProtocolService(store),
        FakeReportSink(),
        control_auth_token="control-token",
    )
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())

    with pytest.raises(RuntimeError, match="UNAUTHENTICATED"):
        await anext(stream)


@pytest.mark.asyncio
async def test_provider_grpc_rejects_wrong_control_token() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(
        RuntimeControlProtocolService(store),
        FakeReportSink(),
        control_auth_token="control-token",
    )
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectProvider(
        inbound,
        FakeGrpcContext((("x-azents-runtime-control-token", "wrong"),)),
    )

    with pytest.raises(RuntimeError, match="UNAUTHENTICATED"):
        await anext(stream)


@pytest.mark.asyncio
async def test_provider_grpc_accepts_control_token_metadata() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(
        RuntimeControlProtocolService(store),
        FakeReportSink(),
        control_auth_token="control-token",
    )
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectProvider(
        inbound,
        FakeGrpcContext((("x-azents-runtime-control-token", "control-token"),)),
    )
    accepted = await anext(stream)
    await stream.aclose()

    assert accepted.register_accepted.provider_id == "provider-1"


def _servicer(
    service: RuntimeControlProtocolService,
    sink: FakeReportSink,
    *,
    control_auth_token: str | None = None,
) -> RuntimeProviderControlGrpcServicer:
    return RuntimeProviderControlGrpcServicer(
        control_protocol=service,
        report_sink=sink,
        owner_replica_id="control-a",
        consumer_id="provider-consumer-a",
        control_auth_token=control_auth_token,
        command_block_ms=1,
    )


def _register_message(
    connection_id: str = "connection-1",
) -> runtime_provider_control_pb2.ProviderMessage:
    return runtime_provider_control_pb2.ProviderMessage(
        connection_id=connection_id,
        request_id="register",
        register=runtime_provider_control_pb2.ProviderRegister(
            provider_id="provider-1",
            provider_type="docker",
            scope="system",
            protocol_version="agent-runtime-provider.v1",
            capabilities=("lifecycle", "observe"),
            config_schema_version="v1",
            auth_credential_id="credential-1",
        ),
    )


def _report_message() -> runtime_provider_control_pb2.RuntimeProviderReport:
    return runtime_provider_control_pb2.RuntimeProviderReport(
        runtime_id="runtime-1",
        provider_id="provider-1",
        provider_generation=1,
        observed_state="running",
        observed_desired_generation=5,
        provider_runtime_id="provider-runtime-1",
        workspace_path="/workspace/agent",
        reason="container_running",
        reported_at=_timestamp(_now()),
    )


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _now() -> datetime:
    return datetime(2026, 5, 25, tzinfo=UTC)
