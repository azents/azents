"""gRPC Runner Control client tests."""

# pyright: reportAttributeAccessIssue=false
# protobuf generated modules expose dynamic message attributes.

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from azents_runtime_control.grpc_runner_client import (
    GrpcRunnerControlClient,
    RuntimeRunnerControlStreamClosed,
)
from azents_runtime_control.proto import runtime_runner_control_pb2
from azents_runtime_control.runner import (
    RunnerOperationEvent,
    RunnerRegistration,
    RuntimeRunnerEventType,
)


@pytest.mark.asyncio
async def test_grpc_client_registers_heartbeats_claims_and_appends_events() -> None:
    """The client maps the gRPC stream onto the RunnerControlClient protocol."""
    sent: list[runtime_runner_control_pb2.RunnerMessage] = []

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        register = await anext(requests)
        sent.append(register)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=register.register.runtime_id,
                runner_id=register.register.runner_id,
                connection_id=register.connection_id,
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="req-1",
            operation_request=runtime_runner_control_pb2.RunnerOperationRequest(
                runtime_id="runtime-1",
                runner_generation=7,
                operation_type="process.start",
                process_start=runtime_runner_control_pb2.ProcessStartOperationPayload(
                    command="python -m http.server",
                    workdir="/workspace/agent",
                    yield_time_ms=1000,
                    max_output_bytes=4096,
                    owner_session_id="session-1",
                    env={"PYTHONUNBUFFERED": "1"},
                ),
                reply_stream_id="reply:req-1",
            ),
        )
        heartbeat = await anext(requests)
        sent.append(heartbeat)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=heartbeat.request_id,
            heartbeat_ack=runtime_runner_control_pb2.RunnerHeartbeatAck(
                monotonic_sequence=heartbeat.heartbeat.monotonic_sequence,
            ),
        )
        event = await anext(requests)
        sent.append(event)

    client = GrpcRunnerControlClient(stream)
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    operation = await client.claim_next_runner_operation(
        runtime_id="runtime-1",
        generation=accepted.generation,
        consumer_id="consumer-1",
        block_ms=100,
    )

    assert accepted.generation == 7
    assert operation is not None
    assert operation.request_id == "req-1"
    assert operation.operation_type == "process.start"
    assert operation.payload == {
        "command": "python -m http.server",
        "workdir": "/workspace/agent",
        "yield_time_ms": 1000,
        "max_output_bytes": 4096,
        "owner_session_id": "session-1",
        "env": {"PYTHONUNBUFFERED": "1"},
    }
    assert await client.heartbeat_runner(
        runtime_id="runtime-1",
        generation=accepted.generation,
        heartbeat_at=_now(),
    )

    await client.append_runner_event(
        RunnerOperationEvent(
            request_id="req-1",
            runtime_id="runtime-1",
            generation=accepted.generation,
            event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
            payload={
                "process_id": "proc_123",
                "status": "running",
                "stdout": "Serving HTTP",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "stdout_omitted_bytes": 0,
                "stderr_omitted_bytes": 0,
            },
            created_at=_now(),
            final=True,
        )
    )
    for _ in range(10):
        if len(sent) >= 3:
            break
        await asyncio.sleep(0)

    assert sent[0].WhichOneof("payload") == "register"
    assert sent[0].register.workspace_path == "/workspace/agent"
    assert sent[1].WhichOneof("payload") == "heartbeat"
    event = sent[2].operation_event
    assert event.event_type == "final_success"
    assert event.WhichOneof("payload") == "final_success"
    assert event.final_success.WhichOneof("result") == "process"
    assert event.final_success.process.process_id == "proc_123"
    assert event.final_success.process.status == "running"
    assert not event.final_success.process.HasField("exit_code")
    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_close_suppresses_completed_stream_failure() -> None:
    """A control-plane stream close should not escape during client cleanup."""
    closed = asyncio.Event()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        register = await anext(requests)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=register.register.runtime_id,
                runner_id=register.register.runner_id,
                connection_id=register.connection_id,
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        closed.set()
        raise RuntimeRunnerControlStreamClosed("stream closed")

    client = GrpcRunnerControlClient(stream)
    await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await asyncio.wait_for(closed.wait(), timeout=1)
    await asyncio.sleep(0)

    await client.close()


def _registration() -> RunnerRegistration:
    return RunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="agent-runtime-runner.v1",
        capabilities=("bash", "file.read"),
        health="ok",
        workspace_path="/workspace/agent",
        metadata={"workspace_path_source": "provider"},
        auth_credential_id="credential-1",
    )


def _now() -> datetime:
    return datetime(2026, 5, 25, tzinfo=UTC)
