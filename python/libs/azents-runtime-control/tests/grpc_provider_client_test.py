"""gRPC Provider Control client tests."""

# pyright: reportAttributeAccessIssue=false
# protobuf generated modules expose dynamic message attributes.

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest

from azents_runtime_control.grpc_provider_client import (
    GrpcProviderControlClient,
    RuntimeProviderControlStreamClosed,
)
from azents_runtime_control.proto import runtime_provider_control_pb2
from azents_runtime_control.provider import (
    ProviderCommandCompletion,
    ProviderRegistration,
    RuntimeProviderObservedState,
    RuntimeProviderReport,
)


@pytest.mark.asyncio
async def test_grpc_client_registers_heartbeats_claims_and_completes() -> None:
    """The client maps the gRPC stream onto the ProviderControlClient protocol."""
    sent: list[runtime_provider_control_pb2.ProviderMessage] = []

    async def stream(
        requests: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
        del metadata
        register = await anext(requests)
        sent.append(register)
        yield runtime_provider_control_pb2.ControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_provider_control_pb2.ProviderRegisterAccepted(
                provider_id=register.register.provider_id,
                connection_id=register.connection_id,
                generation=3,
                heartbeat_interval_seconds=20,
            ),
        )
        yield runtime_provider_control_pb2.ControlMessage(
            request_id="req-1",
            provider_command=runtime_provider_control_pb2.ProviderCommand(
                runtime_id="runtime-1",
                agent_id="agent-1",
                workspace_id="workspace-1",
                desired_generation=5,
                provider_generation=3,
                command_type="start",
                runner_image="runner:latest",
                control_endpoint="runtime-control:8020",
                runner_auth_token="runner-token",
            ),
        )
        heartbeat = await anext(requests)
        sent.append(heartbeat)
        yield runtime_provider_control_pb2.ControlMessage(
            request_id=heartbeat.request_id,
            heartbeat_ack=runtime_provider_control_pb2.ProviderHeartbeatAck(
                monotonic_sequence=heartbeat.heartbeat.monotonic_sequence,
            ),
        )
        completion = await anext(requests)
        sent.append(completion)

    client = GrpcProviderControlClient(stream, provider_credential="provider-secret")
    accepted = await client.register_provider(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    command = await client.claim_next_provider_command(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="consumer-1",
        block_ms=100,
    )

    assert accepted.generation == 3
    assert command is not None
    assert command.command.identity.runtime_id == "runtime-1"
    assert command.command.auth.control_endpoint == "runtime-control:8020"
    assert await client.heartbeat_provider(
        provider_id="provider-1",
        generation=accepted.generation,
        heartbeat_at=_now(),
    )

    await client.complete_provider_command(
        ProviderCommandCompletion(
            request_id=command.request_id,
            generation=accepted.generation,
            success=True,
            report=_report(),
            error_code=None,
            error_message=None,
            completed_at=_now(),
        )
    )
    for _ in range(10):
        if len(sent) >= 3:
            break
        await asyncio.sleep(0)

    assert sent[0].WhichOneof("payload") == "register"
    assert sent[1].WhichOneof("payload") == "heartbeat"
    assert sent[2].command_completion.runtime_id == "runtime-1"
    assert sent[2].command_completion.report.workspace_path == "/workspace/agent"
    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_close_suppresses_completed_stream_failure() -> None:
    """A control-plane stream close should not escape during client cleanup."""
    closed = asyncio.Event()

    async def stream(
        requests: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
        del metadata
        register = await anext(requests)
        yield runtime_provider_control_pb2.ControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_provider_control_pb2.ProviderRegisterAccepted(
                provider_id=register.register.provider_id,
                connection_id=register.connection_id,
                generation=3,
                heartbeat_interval_seconds=20,
            ),
        )
        closed.set()
        raise RuntimeProviderControlStreamClosed("stream closed")

    client = GrpcProviderControlClient(stream, provider_credential="provider-secret")
    await client.register_provider(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await asyncio.wait_for(closed.wait(), timeout=1)
    await asyncio.sleep(0)

    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_sends_control_token_metadata() -> None:
    """The client sends the shared Runtime Control token as bearer metadata."""
    observed_metadata: list[tuple[str, str]] = []

    async def stream(
        requests: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
        del requests
        observed_metadata.extend(metadata or ())
        yield runtime_provider_control_pb2.ControlMessage(
            request_id="register",
            register_accepted=runtime_provider_control_pb2.ProviderRegisterAccepted(
                provider_id="provider-1",
                connection_id="connection-1",
                generation=3,
                heartbeat_interval_seconds=20,
            ),
        )

    client = GrpcProviderControlClient(stream, provider_credential="provider-secret")
    await client.register_provider(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await client.close()

    assert ("authorization", "Bearer provider-secret") in observed_metadata


def _registration() -> ProviderRegistration:
    return ProviderRegistration(
        provider_id="provider-1",
        provider_type="docker",
        scope="system",
        workspace_id=None,
        protocol_version="agent-runtime-provider.v1",
        capabilities=("lifecycle", "observe"),
        config_schema_version="v1",
        metadata={"workspace_path_source": "provider"},
        auth_credential_id="credential-1",
    )


def _report() -> RuntimeProviderReport:
    return RuntimeProviderReport(
        runtime_id="runtime-1",
        provider_id="provider-1",
        provider_generation=3,
        observed_state=RuntimeProviderObservedState.RUNNING,
        observed_desired_generation=5,
        provider_runtime_id="runtime-provider-id",
        workspace_path="/workspace/agent",
        reason="container_running",
        diagnostic={},
        reported_at=_now(),
        terminal_delete_acknowledged=False,
    )


def _now() -> datetime:
    return datetime(2026, 5, 25, tzinfo=UTC)
