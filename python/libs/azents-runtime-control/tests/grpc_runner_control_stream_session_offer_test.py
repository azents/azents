"""Runner Control replacement Runtime Web session offer tests."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import grpc
import pytest

from azents_runtime_control.grpc_runner_client import (
    GrpcRunnerControlClient,
    runner_session_offer_from_message,
    runner_session_offer_to_message,
)
from azents_runtime_control.proto import (
    runtime_runner_control_pb2,
    runtime_runner_control_pb2_grpc,
    runtime_stream_session_pb2,
    runtime_stream_session_pb2_grpc,
)
from azents_runtime_control.runner import RunnerRegistration
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from azents_runtime_control.runtime_stream_session import (
    RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
    OwnerSessionEpoch,
    RunnerSessionOffer,
)


@pytest.mark.asyncio
async def test_runner_control_delivers_exact_stream_session_offer() -> None:
    """Deliver the one replacement offer through the ordinary control stream."""
    received: list[RunnerSessionOffer] = []
    offer_received = asyncio.Event()
    release_stream = asyncio.Event()
    offer = _offer()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        assert metadata == (("authorization", "Bearer runner-token"),)
        register = await anext(requests)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id="runtime-1",
                runner_id="runner-1",
                connection_id="connection-1",
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="stream-session-offer-1",
            stream_session_offer=runner_session_offer_to_message(offer),
        )
        offer_received.set()
        await release_stream.wait()

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")

    async def on_offer(value: RunnerSessionOffer) -> None:
        received.append(value)

    client.set_stream_session_offer_handler(on_offer)
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=datetime.now(UTC),
    )
    await asyncio.wait_for(offer_received.wait(), timeout=1)

    assert accepted.generation == 7
    assert received == [offer]

    release_stream.set()
    await client.close()


@pytest.mark.asyncio
async def test_runner_web_rpc_shares_the_live_control_channel() -> None:
    """Run both authenticated RPC streams through one live gRPC channel."""
    control_servicer = _ControlServicer()
    stream_servicer = _StreamServicer()
    server = grpc.aio.server()
    runtime_runner_control_pb2_grpc.add_RuntimeRunnerControlServicer_to_server(
        control_servicer,
        server,
    )
    runtime_stream_session_pb2_grpc.add_RuntimeRunnerStreamSessionServicer_to_server(
        stream_servicer,
        server,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    assert port != 0
    await server.start()
    client = GrpcRunnerControlClient.from_endpoint(
        f"127.0.0.1:{port}",
        runner_auth_token="runner-token",
        tls=None,
        allow_insecure=True,
    )
    stream_client = None
    try:
        accepted = await client.register_runner(
            _registration(),
            connection_id="connection-1",
            registered_at=datetime.now(UTC),
        )
        stream_client = client.create_stream_session_client(outbound_resources=None)
        session_accepted = await stream_client.start(
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
                stream_id=0,
                hello=runtime_stream_session_pb2.RuntimeStreamSessionHello(),
            ),
            _ignore_stream_envelope,
            _ignore_stream_failure,
            timeout_seconds=1,
        )
        stream_client.activate()

        assert accepted.generation == 7
        assert session_accepted.WhichOneof("payload") == "session_accepted"
        assert control_servicer.peers == stream_servicer.peers
        assert stream_client.metadata == (("authorization", "Bearer runner-token"),)

        await stream_client.close()
        heartbeat = await client.heartbeat_runner(
            runtime_id="runtime-1",
            generation=accepted.generation,
            heartbeat_at=datetime.now(UTC),
        )
        assert heartbeat.accepted
    finally:
        if stream_client is not None:
            await stream_client.close()
        await client.close()
        await server.stop(None)


def test_stream_session_offer_round_trip_preserves_exact_authority() -> None:
    """Preserve every Owner, generation, nonce, fingerprint, and deadline field."""
    offer = _offer()

    message = runner_session_offer_to_message(offer)

    assert message.join_nonce == "join-nonce-1"
    assert message.protocol_fingerprint == RUNTIME_STREAM_PROTOCOL_FINGERPRINT
    fields = runtime_runner_control_pb2.RunnerSessionOffer.DESCRIPTOR.fields_by_name
    assert "owner_replica_id" not in fields
    assert "connect_address" not in fields
    assert "tls_server_name" not in fields
    assert runner_session_offer_from_message(message) == offer


def test_stream_session_offer_requires_registration_deadline() -> None:
    """Reject an offer that cannot enforce the bounded join window."""
    message = runner_session_offer_to_message(_offer())
    message.ClearField("registration_deadline_at")

    with pytest.raises(ValueError, match="registration deadline"):
        runner_session_offer_from_message(message)


def _offer() -> RunnerSessionOffer:
    return RunnerSessionOffer(
        owner=OwnerSessionEpoch(
            owner_boot_id="owner-boot-1",
            session_lease_id="session-lease-1",
            lease_generation=3,
            runtime_id="runtime-1",
            desired_generation=5,
            runner_generation=7,
        ),
        session_nonce="join-nonce-1",
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        deadline_at=datetime(2026, 9, 14, tzinfo=UTC) + timedelta(seconds=10),
    )


def _registration() -> RunnerRegistration:
    return RunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="agent-runtime-runner.v1",
        capabilities=("runtime-web-http",),
        health="ok",
        workspace_path="/workspace/agent",
        metadata={},
        auth_credential_id="credential-1",
        runtime_configuration=RuntimeConfigurationEvidence(
            configuration_sequence=1,
            digest="d" * 64,
            desired_generation=5,
        ),
    )


class _ControlServicer(runtime_runner_control_pb2_grpc.RuntimeRunnerControlServicer):
    def __init__(self) -> None:
        self.peers: list[str] = []

    async def ConnectRunner(
        self,
        request_iterator: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        context: grpc.aio.ServicerContext[
            runtime_runner_control_pb2.RunnerMessage,
            runtime_runner_control_pb2.RunnerControlMessage,
        ],
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        self.peers.append(context.peer())
        registration = await anext(request_iterator)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=registration.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id="runtime-1",
                runner_id="runner-1",
                connection_id="connection-1",
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        async for message in request_iterator:
            if message.WhichOneof("payload") == "heartbeat":
                yield runtime_runner_control_pb2.RunnerControlMessage(
                    request_id=message.request_id,
                    heartbeat_ack=runtime_runner_control_pb2.RunnerHeartbeatAck(
                        monotonic_sequence=message.heartbeat.monotonic_sequence,
                    ),
                )


class _StreamServicer(
    runtime_stream_session_pb2_grpc.RuntimeRunnerStreamSessionServicer
):
    def __init__(self) -> None:
        self.peers: list[str] = []

    async def Connect(
        self,
        request_iterator: AsyncIterator[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ],
        context: grpc.aio.ServicerContext[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope,
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope,
        ],
    ) -> AsyncIterator[runtime_stream_session_pb2.RuntimeStreamSessionEnvelope]:
        self.peers.append(context.peer())
        await anext(request_iterator)
        yield runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
            stream_id=0,
            session_accepted=runtime_stream_session_pb2.RuntimeStreamSessionAccepted(),
        )
        async for _ in request_iterator:
            pass


async def _ignore_stream_envelope(
    envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope,
) -> None:
    del envelope


async def _ignore_stream_failure() -> None:
    pass
