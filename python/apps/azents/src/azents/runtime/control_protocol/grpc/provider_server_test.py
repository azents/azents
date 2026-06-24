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
from azents_runtime_control.provider import RuntimeProviderReport
from google.protobuf import timestamp_pb2

from azents.core.enums import RuntimeLifecycleCommandType
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
            command_type=RuntimeLifecycleCommandType.START,
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


def _servicer(
    service: RuntimeControlProtocolService,
    sink: FakeReportSink,
) -> RuntimeProviderControlGrpcServicer:
    return RuntimeProviderControlGrpcServicer(
        control_protocol=service,
        report_sink=sink,
        owner_replica_id="control-a",
        consumer_id="provider-consumer-a",
        command_block_ms=1,
    )


def _register_message() -> runtime_provider_control_pb2.ProviderMessage:
    return runtime_provider_control_pb2.ProviderMessage(
        connection_id="connection-1",
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
